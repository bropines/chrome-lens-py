# src/chrome_lens_py/core/request_handler.py
import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Union

import httpx

from ..constants import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_HEADERS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_POOL_TIMEOUT,
    LENS_CRUPLOAD_ENDPOINT,
    RETRYABLE_STATUS_CODES,
)
from ..exceptions import LensAPIError, LensProtobufError
from ..utils.lens_betterproto import (
    LensOverlayClusterInfo,
    LensOverlayServerError,
    LensOverlayServerResponse,
)

logger = logging.getLogger(__name__)

_ENV_PROXY_VARS = ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy")


def detect_env_proxy() -> Optional[str]:
    """Return the proxy httpx would silently pick up from the environment."""
    for var in _ENV_PROXY_VARS:
        value = os.environ.get(var)
        if value:
            return f"{var}={value}"
    return None


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
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def next_ids(
        self, is_new_image_payload: bool
    ) -> Tuple[Optional[int], int, int]:
        async with self._lock:
            self.sequence_id += 1
            if is_new_image_payload:
                self.image_sequence_id += 1
            return self.uuid, self.sequence_id, self.image_sequence_id


class LensRequestHandler:
    def __init__(
        self,
        api_key: str,
        proxy: Optional[Union[str, Dict[str, httpx.AsyncBaseTransport]]] = None,
        timeout: int = 60,
        trust_env: bool = True,
        max_connections: int = 32,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.trust_env = trust_env
        self.max_retries = max_retries
        self.proxy_settings: Dict[str, Any] = {}

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
        self._client_lock = asyncio.Lock()

        # Kept so callers written against the old single-session handler work.
        self.default_session = LensSession()

    async def get_client(self) -> httpx.AsyncClient:
        """One pooled client for the whole handler.

        A fresh AsyncClient per request meant a new TCP + TLS + HTTP/2 handshake
        every time, which dominates wall clock when scanning a directory.
        """
        if self._client is None or self._client.is_closed:
            async with self._client_lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        **self.proxy_settings,
                        http2=True,
                        trust_env=self.trust_env,
                        timeout=self._timeout_config,
                        limits=self._limits,
                    )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _get_headers(self) -> dict:
        headers = DEFAULT_HEADERS.copy()
        headers["X-Goog-Api-Key"] = self.api_key
        return headers

    def new_session(self) -> LensSession:
        return LensSession()

    def start_new_session(self) -> LensSession:
        """Reset the shared session (kept for backwards compatibility)."""
        self.default_session = LensSession()
        logger.info("LensRequestHandler: New session initiated (state reset).")
        return self.default_session

    def _connect_error_hint(self, exc: Optional[Exception]) -> str:
        if not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return ""
        env_proxy = detect_env_proxy()
        if env_proxy and not self.proxy_settings and self.trust_env:
            return (
                f" The connection went through the environment proxy ({env_proxy}); "
                "retry with --no-env-proxy if that proxy is not running."
            )
        return ""

    async def post_raw(
        self, protobuf_payload: bytes, session: Optional[LensSession] = None
    ) -> httpx.Response:
        """POST the payload with bounded retries, returning the raw response."""
        client = await self.get_client()
        headers = self._get_headers()
        last_exc: Optional[Exception] = None

        # Follow-up requests must land on the same backend as the one that
        # created the session, which Chromium arranges with this query param.
        url = LENS_CRUPLOAD_ENDPOINT
        if session is not None and session.cluster_info is not None:
            server_session_id = session.cluster_info.server_session_id
            if server_session_id:
                url = f"{LENS_CRUPLOAD_ENDPOINT}?gsessionid={server_session_id}"

        for attempt in range(self.max_retries + 1):
            try:
                response = await client.post(
                    url, content=protobuf_payload, headers=headers
                )
                if (
                    response.status_code in RETRYABLE_STATUS_CODES
                    and attempt < self.max_retries
                ):
                    await response.aread()
                    delay = (2**attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "Lens API returned %s, retrying in %.1fs (attempt %d/%d).",
                        response.status_code,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue
                return response
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                delay = (2**attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "Network error (%s), retrying in %.1fs (attempt %d/%d).",
                    type(exc).__name__,
                    delay,
                    attempt + 1,
                    self.max_retries,
                )
                await asyncio.sleep(delay)

        raise LensAPIError(
            f"Network error: {last_exc}{self._connect_error_hint(last_exc)}"
        ) from last_exc

    async def send_interaction(
        self, protobuf_payload: bytes, session: LensSession
    ) -> "LensOverlayServerResponse":
        """Send a follow-up interaction on an established session."""
        response = await self.post_raw(protobuf_payload, session=session)
        response_bytes = await response.aread()

        if response.status_code >= 400:
            raise LensAPIError(
                f"HTTP error: {response.status_code}",
                status_code=response.status_code,
                response_body=response_bytes.decode(errors="replace"),
            )
        try:
            return LensOverlayServerResponse.FromString(response_bytes)
        except Exception as e_parse:
            raise LensProtobufError(
                f"Protobuf response parsing error: {e_parse}",
                response_body=response_bytes.decode(errors="replace"),
            ) from e_parse

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
            LENS_CRUPLOAD_ENDPOINT,
            session.uuid,
            session.sequence_id,
            len(protobuf_payload),
        )

        response = await self.post_raw(protobuf_payload, session=session)
        response_bytes = await response.aread()

        if response.status_code >= 400:
            raise LensAPIError(
                f"HTTP error: {response.status_code}",
                status_code=response.status_code,
                response_body=response_bytes.decode(errors="replace"),
            )

        # Only the parse itself is guarded. The old code wrapped this whole
        # block, so a LensAPIError raised below was caught and re-reported as a
        # protobuf parsing failure.
        try:
            server_response_proto = LensOverlayServerResponse.FromString(response_bytes)
        except Exception as e_parse:
            raise LensProtobufError(
                f"Protobuf response parsing error: {e_parse}",
                response_body=response_bytes.decode(errors="replace"),
            ) from e_parse

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
                response_body=response_bytes.decode(errors="replace"),
            )

        if server_response_proto.HasField(
            "objects_response"
        ) and server_response_proto.objects_response.HasField("cluster_info"):
            session.cluster_info = server_response_proto.objects_response.cluster_info
        else:
            session.cluster_info = None

        return server_response_proto
