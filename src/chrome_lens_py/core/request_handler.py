# src/chrome_lens_py/core/request_handler.py
"""Transport for the Lens crupload endpoint.

The retry policy, in one place, because "why did it hang / why did it retry"
was the most common support question:

  * One logical request has an overall ``deadline`` (seconds, wall clock). It
    bounds every attempt, every backoff sleep and every fallback together, so a
    stalled server can never hold a caller forever.
  * Transient failures (connection errors, timeouts, HTTP 429/500/502/503/504)
    are retried up to ``max_retries`` times with jittered exponential backoff:
    ``min(backoff_max, backoff_base * 2**attempt)`` scaled by a random factor in
    [0.5, 1.0]. ``Retry-After`` on 429/503 replaces the computed delay. If the
    server asks for longer than the remaining deadline we stop immediately
    instead of sleeping towards a guaranteed timeout.
  * Fallbacks do not consume the retry budget: the next API key (on a key
    rejection), the next endpoint (on a connection failure) and, only when
    explicitly enabled, a direct connection when the *environment* proxy is
    unreachable.
"""

import asyncio
import email.utils
import importlib.util
import logging
import os
import random
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

import httpx

from ..constants import (
    DEFAULT_BACKOFF_BASE,
    DEFAULT_BACKOFF_MAX,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_ENDPOINTS,
    DEFAULT_HEADERS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_POOL_TIMEOUT,
    LENS_ENDPOINT_ENV,
    RETRY_AFTER_STATUS_CODES,
    RETRYABLE_STATUS_CODES,
)
from ..exceptions import (
    LensAPIError,
    LensAuthError,
    LensConfigError,
    LensConnectionError,
    LensProtobufError,
    LensRateLimitError,
    LensTimeoutError,
)
from ..utils.lens_betterproto import (
    LensOverlayClusterInfo,
    LensOverlayServerResponse,
)
from .aio import LoopLocal

logger = logging.getLogger(__name__)

_ENV_PROXY_VARS = ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy")

# Statuses that can mean "this API key is no good" (Google answers a malformed
# key with 400 and a revoked or restricted one with 401/403).
_KEY_STATUS_CODES = frozenset({400, 401, 403})
_KEY_BODY_MARKERS = ("api key", "api_key", "apikey")


def detect_env_proxy() -> Optional[str]:
    """Return the proxy httpx would silently pick up from the environment."""
    for var in _ENV_PROXY_VARS:
        value = os.environ.get(var)
        if value:
            return f"{var}={value}"
    return None


@lru_cache(maxsize=1)
def _has_brotli() -> bool:
    return any(
        importlib.util.find_spec(name) is not None for name in ("brotli", "brotlicffi")
    )


def accept_encoding() -> str:
    """Encodings we can really decode.

    Advertising ``br`` without brotli installed makes httpx raise as soon as the
    server accepts the offer, so it is only listed when a decoder is importable.
    """
    base = DEFAULT_HEADERS["Accept-Encoding"]
    return f"{base}, br" if _has_brotli() else base


def resolve_endpoints(
    endpoints: Optional[Union[str, Sequence[str]]] = None,
) -> Tuple[str, ...]:
    """Explicit argument, else $LENS_ENDPOINT (comma separated), else the default."""
    source = "endpoints"
    if endpoints is None:
        env = os.environ.get(LENS_ENDPOINT_ENV, "").strip()
        if env:
            endpoints, source = env.split(","), f"${LENS_ENDPOINT_ENV}"
    if endpoints is None:
        return tuple(DEFAULT_ENDPOINTS)
    if isinstance(endpoints, str):
        endpoints = [endpoints]

    resolved: List[str] = []
    for raw in endpoints:
        url = str(raw).strip()
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise LensConfigError(
                f"Invalid Lens endpoint in {source}: {url!r} "
                "(expected an absolute http(s) URL)."
            )
        if url not in resolved:
            resolved.append(url)
    if not resolved:
        raise LensConfigError(f"No Lens endpoint given in {source}.")
    return tuple(resolved)


def _describe(exc: BaseException) -> str:
    """str(exc) is empty for most httpx timeouts, which made for blank errors."""
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Retry-After as seconds: either delta-seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if seconds != seconds or seconds < 0:  # NaN or in the past
        return 0.0 if seconds == seconds else None
    return seconds


def is_key_rejection(status_code: int, body_text: str) -> bool:
    """Does this error response mean the API key itself was refused?"""
    if status_code == 401:
        return True
    if status_code not in _KEY_STATUS_CODES:
        return False
    lowered = body_text.lower()
    return any(marker in lowered for marker in _KEY_BODY_MARKERS)


def raise_for_response(response: httpx.Response, body: bytes) -> None:
    """Translate an HTTP error status into the matching Lens exception."""
    status = response.status_code
    if status < 400:
        return
    text = body.decode(errors="replace")
    retry_after = parse_retry_after(response.headers.get("retry-after"))

    if status == 429 or (status == 503 and retry_after is not None):
        wait = f" Retry after {retry_after:g}s." if retry_after is not None else ""
        raise LensRateLimitError(
            f"Lens is rate limiting this client (HTTP {status}).{wait} "
            "Lower the concurrency or space the requests out.",
            status_code=status,
            response_body=text,
            retry_after=retry_after,
        )
    if is_key_rejection(status, text):
        raise LensAuthError(
            "The Lens API key was rejected. Pass a different key "
            "(LensAPI(api_key=[...]) accepts a fallback list).",
            status_code=status,
            response_body=text,
        )
    raise LensAPIError(f"HTTP error: {status}", status_code=status, response_body=text)


class _Transient(Exception):
    """Internal: one attempt failed in a way that is worth retrying."""

    def __init__(self, error: LensAPIError, cause: Optional[BaseException]):
        super().__init__(str(error))
        self.error = error
        self.cause = cause


class _ConnectFailure(Exception):
    """Internal: could not reach one endpoint, so try the next."""

    def __init__(self, exc: httpx.TransportError):
        super().__init__(str(exc))
        self.exc = exc


@dataclass
class LensSession:
    """Per-conversation state.

    These counters used to live on the handler itself, so every concurrent
    process_image call mutated the same three integers. Keeping them in a value
    object gives each request its own sequence.
    """

    uuid: Optional[int] = None
    sequence_id: int = 0
    image_sequence_id: int = 0
    cluster_info: Optional["LensOverlayClusterInfo"] = None
    _lock: LoopLocal[asyncio.Lock] = field(
        default_factory=lambda: LoopLocal(asyncio.Lock), repr=False
    )
    _exchange_lock: LoopLocal[asyncio.Lock] = field(
        default_factory=lambda: LoopLocal(asyncio.Lock), repr=False
    )

    async def next_ids(
        self, is_new_image_payload: bool
    ) -> Tuple[Optional[int], int, int]:
        async with self._lock.get():
            self.sequence_id += 1
            if is_new_image_payload:
                self.image_sequence_id += 1
            return self.uuid, self.sequence_id, self.image_sequence_id

    def exclusive(self) -> asyncio.Lock:
        """Hold across build-request -> response when a session is shared.

        The routing info of one reply feeds the next request, so two exchanges
        interleaving on one session would overwrite each other's cluster_info.
        A private session never contends for this.
        """
        return self._exchange_lock.get()


class LensRequestHandler:
    def __init__(
        self,
        api_key: Union[str, Sequence[str]],
        proxy: Optional[Union[str, Dict[str, httpx.AsyncBaseTransport]]] = None,
        timeout: float = 60,
        trust_env: bool = True,
        max_connections: int = 32,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_max: float = DEFAULT_BACKOFF_MAX,
        deadline: Optional[float] = None,
        endpoints: Optional[Union[str, Sequence[str]]] = None,
        direct_fallback: bool = False,
    ):
        keys = [api_key] if isinstance(api_key, str) else list(api_key)
        self.api_keys: List[str] = list(dict.fromkeys(k for k in keys if k))
        if not self.api_keys:
            raise LensConfigError("At least one non-empty API key is required.")
        self._key_index = 0

        if max_retries < 0:
            raise LensConfigError("max_retries must be >= 0.")
        if backoff_base < 0 or backoff_max < 0:
            raise LensConfigError("backoff_base and backoff_max must be >= 0.")

        self.endpoints = resolve_endpoints(endpoints)
        self._endpoint_index = 0

        self.timeout = timeout
        self.trust_env = trust_env
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        # Three full-length attempts by default; backoff sleeps come out of the
        # same budget rather than adding to it.
        self.deadline: float = deadline if deadline is not None else timeout * 3
        if self.deadline <= 0:
            raise LensConfigError("deadline must be > 0 seconds.")
        self.direct_fallback = direct_fallback
        self.proxy_settings: Dict[str, Any] = {}

        # Injection points, so tests can run the policy without waiting.
        self._sleep: Callable[[float], Any] = asyncio.sleep
        self._random: Callable[[], float] = random.random

        if proxy:
            if isinstance(proxy, str):
                self.proxy_settings["proxy"] = proxy
                logger.info("Using single proxy URL: %s", proxy)
            elif isinstance(proxy, dict):
                self.proxy_settings["mounts"] = proxy
                logger.info("Using proxy mounts configuration: %s", proxy)
            else:
                logger.warning(
                    "Invalid proxy type: %s. Proxy will not be used.", type(proxy)
                )
        elif trust_env:
            env_proxy = detect_env_proxy()
            if env_proxy:
                # The most confusing failure mode of this tool: no --proxy was
                # given, yet every request still goes through one.
                logger.warning(
                    "No proxy was configured, but httpx will use the proxy from the "
                    "environment (%s). Pass trust_env=False (CLI: --no-env-proxy) "
                    "to connect directly.",
                    env_proxy,
                )

        self._timeout_config = httpx.Timeout(
            connect=min(DEFAULT_CONNECT_TIMEOUT, timeout),
            read=timeout,
            write=timeout,
            pool=DEFAULT_POOL_TIMEOUT,
        )
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._direct_client: Optional[httpx.AsyncClient] = None
        self._prefer_direct = False
        self._client_lock = LoopLocal(asyncio.Lock)

        # Kept so callers written against the old single-session handler work.
        self.default_session = LensSession()

    # ----------------------------------------------------------------- clients

    @property
    def api_key(self) -> str:
        """The key currently in use (the first one that has not been rejected)."""
        return self.api_keys[self._key_index]

    @property
    def endpoint(self) -> str:
        return self.endpoints[self._endpoint_index]

    def _build_client(self, **extra: Any) -> httpx.AsyncClient:
        kwargs: Dict[str, Any] = dict(
            trust_env=self.trust_env,
            timeout=self._timeout_config,
            limits=self._limits,
        )
        kwargs.update(extra)
        try:
            return httpx.AsyncClient(http2=True, **kwargs)
        except ImportError:
            # h2 missing (a stripped-down install): HTTP/1.1 works fine.
            logger.warning("HTTP/2 support (h2) is not installed; using HTTP/1.1.")
            return httpx.AsyncClient(http2=False, **kwargs)

    async def get_client(self) -> httpx.AsyncClient:
        """One pooled client for the whole handler.

        A fresh AsyncClient per request meant a new TCP + TLS + HTTP/2 handshake
        every time, which dominates wall clock when scanning a directory.
        """
        if self._client is None or self._client.is_closed:
            async with self._client_lock.get():
                if self._client is None or self._client.is_closed:
                    # Built off the event loop: creating the SSL context loads
                    # the whole CA bundle, which blocked the daemon for long
                    # enough that a status probe right after start timed out.
                    self._client = await asyncio.to_thread(
                        lambda: self._build_client(**self.proxy_settings)
                    )
        return self._client

    async def _get_direct_client(self) -> httpx.AsyncClient:
        if self._direct_client is None or self._direct_client.is_closed:
            async with self._client_lock.get():
                if self._direct_client is None or self._direct_client.is_closed:
                    self._direct_client = await asyncio.to_thread(
                        lambda: self._build_client(trust_env=False)
                    )
        return self._direct_client

    async def aclose(self) -> None:
        for client in (self._client, self._direct_client):
            if client is not None and not client.is_closed:
                await client.aclose()
        self._client = None
        self._direct_client = None

    # ----------------------------------------------------------------- helpers

    def _headers(self, api_key: str) -> Dict[str, str]:
        headers = DEFAULT_HEADERS.copy()
        headers["Accept-Encoding"] = accept_encoding()
        headers["X-Goog-Api-Key"] = api_key
        return headers

    def new_session(self) -> LensSession:
        return LensSession()

    def start_new_session(self) -> LensSession:
        """Reset the shared session.

        Deprecated: sessions are values now. Use ``new_session()`` and pass the
        result to ``send_request``/``send_interaction``.
        """
        warnings.warn(
            "start_new_session() is deprecated; use new_session() and pass the "
            "session explicitly.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.default_session = LensSession()
        logger.info("LensRequestHandler: New session initiated (state reset).")
        return self.default_session

    def _can_fall_back_to_direct(self) -> bool:
        """Only ever for a proxy nobody asked for by name.

        An explicit ``proxy=`` is a statement of intent (egress policy, geo,
        anonymity) and is never bypassed. The environment proxy is ambient, so
        an opt-in direct retry is a reasonable convenience.
        """
        return (
            self.direct_fallback
            and not self.proxy_settings
            and self.trust_env
            and detect_env_proxy() is not None
        )

    def _connect_error_hint(self, exc: Optional[BaseException]) -> str:
        if not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return ""
        env_proxy = detect_env_proxy()
        if env_proxy and not self.proxy_settings and self.trust_env:
            return (
                f" The connection went through the environment proxy ({env_proxy}); "
                "retry with --no-env-proxy if that proxy is not running."
            )
        return ""

    def _classify(self, exc: httpx.RequestError) -> LensAPIError:
        hint = self._connect_error_hint(exc)
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return LensConnectionError(f"Network error: {_describe(exc)}.{hint}")
        if isinstance(exc, httpx.TimeoutException):
            return LensTimeoutError(
                f"Timed out waiting for Lens ({type(exc).__name__}, "
                f"timeout={self.timeout:g}s). Raise the timeout or check the network."
            )
        if isinstance(exc, httpx.TransportError):
            return LensConnectionError(f"Network error: {_describe(exc)}")
        return LensAPIError(f"Request failed: {_describe(exc)}")

    def _backoff(self, attempt: int) -> float:
        delay = min(self.backoff_max, self.backoff_base * (2**attempt))
        return delay * (0.5 + 0.5 * self._random())

    def _deadline_error(self, last: Optional[LensAPIError]) -> LensTimeoutError:
        detail = f" Last failure: {last}" if last is not None else ""
        return LensTimeoutError(
            f"Lens request exceeded its overall deadline of {self.deadline:g}s "
            f"(including retries).{detail}"
        )

    @staticmethod
    def _url(endpoint: str, session: Optional[LensSession]) -> str:
        # Follow-up requests must land on the same backend as the one that
        # created the session, which Chromium arranges with this query param.
        if session is not None and session.cluster_info is not None:
            server_session_id = session.cluster_info.server_session_id
            if server_session_id:
                sep = "&" if "?" in endpoint else "?"
                return f"{endpoint}{sep}gsessionid={server_session_id}"
        return endpoint

    # ---------------------------------------------------------------- the send

    async def _post_once(
        self, url: str, payload: bytes, api_key: str
    ) -> httpx.Response:
        """One POST, with the optional direct retry around an unreachable env proxy."""
        headers = self._headers(api_key)
        if self._prefer_direct:
            client = await self._get_direct_client()
            return await client.post(url, content=payload, headers=headers)

        client = await self.get_client()
        try:
            return await client.post(url, content=payload, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError) as exc:
            if not self._can_fall_back_to_direct():
                raise
            logger.warning(
                "The environment proxy (%s) is unreachable (%s). Retrying once "
                "without a proxy; all further requests in this process connect "
                "directly. Disable with direct_fallback=False.",
                detect_env_proxy(),
                type(exc).__name__,
            )
            direct = await self._get_direct_client()
            response = await direct.post(url, content=payload, headers=headers)
            self._prefer_direct = True
            return response

    async def _post_with_keys(self, url: str, payload: bytes) -> httpx.Response:
        """Try the keys in order, starting from the last one that worked."""
        count = len(self.api_keys)
        start = self._key_index
        response: Optional[httpx.Response] = None
        for step in range(count):
            index = (start + step) % count
            response = await self._post_once(url, payload, self.api_keys[index])
            if not is_key_rejection(response.status_code, response.text):
                if index != self._key_index:
                    logger.warning(
                        "API key #%d was rejected; switched to fallback key #%d.",
                        start + 1,
                        index + 1,
                    )
                    self._key_index = index
                return response
            logger.warning(
                "API key #%d of %d was rejected (HTTP %d).",
                index + 1,
                count,
                response.status_code,
            )
        assert response is not None
        return response

    async def _send_once(
        self, payload: bytes, session: Optional[LensSession]
    ) -> httpx.Response:
        """One attempt: walk the endpoints, and within each the keys."""
        count = len(self.endpoints)
        start = self._endpoint_index
        last_failure: Optional[httpx.TransportError] = None
        for step in range(count):
            index = (start + step) % count
            url = self._url(self.endpoints[index], session)
            try:
                response = await self._post_with_keys(url, payload)
            except httpx.TransportError as exc:
                if isinstance(exc, httpx.UnsupportedProtocol):
                    raise LensConnectionError(
                        f"Invalid Lens endpoint {self.endpoints[index]!r}: {exc}"
                    ) from exc
                if isinstance(
                    exc,
                    (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError),
                ):
                    last_failure = exc
                    if step < count - 1:
                        logger.warning(
                            "Cannot reach %s (%s); falling back to %s.",
                            self.endpoints[index],
                            type(exc).__name__,
                            self.endpoints[(index + 1) % count],
                        )
                    continue
                raise
            if index != self._endpoint_index:
                self._endpoint_index = index
            return response
        assert last_failure is not None
        raise last_failure

    async def post_raw(
        self, protobuf_payload: bytes, session: Optional[LensSession] = None
    ) -> httpx.Response:
        """POST the payload under the retry policy and return the response.

        Transport failures raise LensConnectionError / LensTimeoutError. HTTP
        error statuses are *returned* (after retries on the retryable ones) so
        callers can read the body; use ``raise_for_response`` to convert.
        """
        loop = asyncio.get_running_loop()
        started = loop.time()
        deadline_at = started + self.deadline
        last_error: Optional[LensAPIError] = None

        for attempt in range(self.max_retries + 1):
            remaining = deadline_at - loop.time()
            if remaining <= 0:
                raise self._deadline_error(last_error)

            retry_after: Optional[float] = None
            pending: Optional[httpx.Response] = None
            try:
                response = await asyncio.wait_for(
                    self._send_once(protobuf_payload, session), timeout=remaining
                )
            except asyncio.TimeoutError:
                raise self._deadline_error(last_error) from None
            except httpx.RequestError as exc:
                error = self._classify(exc)
                if isinstance(exc, httpx.UnsupportedProtocol) or not isinstance(
                    exc, httpx.TransportError
                ):
                    raise error from exc
                last_error = error
                failure = f"{type(exc).__name__}"
                cause: Optional[BaseException] = exc
            else:
                if (
                    response.status_code not in RETRYABLE_STATUS_CODES
                    or attempt >= self.max_retries
                ):
                    return response
                await response.aread()
                if response.status_code in RETRY_AFTER_STATUS_CODES:
                    retry_after = parse_retry_after(response.headers.get("retry-after"))
                failure = f"HTTP {response.status_code}"
                pending = response
                cause = None
                last_error = LensAPIError(
                    f"HTTP error: {response.status_code}",
                    status_code=response.status_code,
                )

            if attempt >= self.max_retries:
                assert last_error is not None
                raise last_error from cause

            if retry_after is not None:
                # Spread out clients that were all told to come back at once.
                delay = retry_after * (1 + 0.1 * self._random())
            else:
                delay = self._backoff(attempt)
            remaining = deadline_at - loop.time()
            if delay >= remaining:
                # Sleeping would only burn the budget; surface the real cause.
                if pending is not None:
                    return pending
                assert last_error is not None
                raise last_error from cause
            logger.warning(
                "Lens request failed (%s), retrying in %.1fs (attempt %d/%d).",
                failure,
                delay,
                attempt + 1,
                self.max_retries,
            )
            await self._sleep(delay)

        raise AssertionError("unreachable")  # pragma: no cover

    async def _exchange(
        self, protobuf_payload: bytes, session: LensSession
    ) -> Tuple[httpx.Response, bytes]:
        response = await self.post_raw(protobuf_payload, session=session)
        body = await response.aread()
        raise_for_response(response, body)
        return response, body

    @staticmethod
    def _parse_response(body: bytes) -> "LensOverlayServerResponse":
        try:
            return LensOverlayServerResponse.FromString(body)
        except Exception as e_parse:
            raise LensProtobufError(
                f"Protobuf response parsing error: {e_parse}",
                response_body=body.decode(errors="replace"),
            ) from e_parse

    async def send_interaction(
        self, protobuf_payload: bytes, session: LensSession
    ) -> "LensOverlayServerResponse":
        """Send a follow-up interaction on an established session."""
        _, body = await self._exchange(protobuf_payload, session)
        return self._parse_response(body)

    async def send_request(
        self,
        protobuf_payload: bytes,
        request_uuid_used: int,
        session: Optional[LensSession] = None,
    ) -> "LensOverlayServerResponse":
        session = session if session is not None else self.default_session

        if session.uuid is None:
            session.uuid = request_uuid_used

        logger.info(
            "Sending request to %s (UUID: %s, SeqID: %s) with payload size: %d bytes.",
            self.endpoint,
            session.uuid,
            session.sequence_id,
            len(protobuf_payload),
        )

        response, body = await self._exchange(protobuf_payload, session)
        server_response_proto = self._parse_response(body)

        if (
            server_response_proto.HasField("error")
            and server_response_proto.error.error_type != 0
        ):
            error_msg = (
                f"Lens API server error. Type: {server_response_proto.error.error_type}"
            )
            logger.error(error_msg)
            raise LensAPIError(
                error_msg,
                status_code=response.status_code,
                response_body=body.decode(errors="replace"),
            )

        if server_response_proto.HasField(
            "objects_response"
        ) and server_response_proto.objects_response.HasField("cluster_info"):
            session.cluster_info = server_response_proto.objects_response.cluster_info
        else:
            session.cluster_info = None

        return server_response_proto


__all__ = [
    "LensRequestHandler",
    "LensSession",
    "accept_encoding",
    "detect_env_proxy",
    "is_key_rejection",
    "parse_retry_after",
    "raise_for_response",
    "resolve_endpoints",
]
