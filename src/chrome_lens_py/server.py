"""A small local HTTP daemon around LensAPI.

Why this exists: importing Pillow, protobuf and httpx costs roughly a second,
and ShareX pays it on every single screenshot. Keeping one warm process turns
that into a socket write.

Deliberately built on asyncio directly rather than a web framework: the whole
point is to start fast, and adding FastAPI/uvicorn would put back the import
cost we are removing.

Security posture. This daemon holds an API key and will talk to Google on
behalf of whoever reaches it, so the one thing it must never become is an open
relay. Three rules enforce that, and they are why the defaults look strict:

  * Browsers are shut out by default. Any request carrying an Origin header is
    refused unless that exact origin was named on the command line. The check
    is on the request, not the response, because a page can send a POST it is
    forbidden to read and still get the side effect it was after.
  * POSTs must be JSON. A page cannot set application/json without a CORS
    preflight, which closes the same hole from the other side.
  * Binding anywhere but loopback requires a token, and then accepts only
    inline pixels - no paths to read, no URLs to go fetch.

Routes
  GET  /health, /        liveness (never needs the token)
  GET  /v1/version       version and capabilities
  POST /v1/ocr           OCR / translate one image
  POST /v1/region        re-read one region at native resolution

Status codes: 200 ok; 400 bad JSON, bad field or undecodable image; 401 bad
token; 403 origin refused; 404 no such route; 405 wrong method; 413 body over
the limit; 415 not application/json; 429 upstream rate limit (Retry-After is
forwarded); 502 Lens unreachable or erroring; 504 timeout (upstream, or this
daemon's own per-request limit); 500 anything else.

Every response carries X-Request-ID (the caller's, if it sent a sane one), and
every request is logged with it.

Remote clients cannot read the daemon's disk, so they ask for the rendered
translation in the response with ``"return_overlay": true`` (base64 PNG, or
WEBP via ``"overlay_format": "webp"``, under ``overlay_image``).
"""

import asyncio
import base64
import binascii
import contextlib
import hmac
import ipaddress
import json
import logging
import math
import re
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from functools import partial
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from .api import LensAPI
from .core.request_handler import accept_encoding
from .exceptions import (
    LensAPIError,
    LensConnectionError,
    LensException,
    LensImageError,
    LensRateLimitError,
    LensTimeoutError,
)

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 32 * 1024 * 1024
MAX_HEADER_LINE_BYTES = 16 * 1024
MAX_HEADER_COUNT = 100
HEADER_TIMEOUT = 15.0
BODY_TIMEOUT = 120.0
REQUEST_TIMEOUT = 300.0
SHUTDOWN_GRACE = 10.0
_DRAIN_LIMIT = 1024 * 1024

_STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    415: "Unsupported Media Type",
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    500: "Internal Server Error",
    502: "Bad Gateway",
    504: "Gateway Timeout",
}
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})


def is_loopback(host: str) -> bool:
    """True if a listener on `host` can only be reached from this machine."""
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def json_safe(value: Any) -> Any:
    """Make an API result JSON-serializable.

    Results carry raw protobuf objects and image bytes; the former is dropped,
    the latter base64-encoded so a browser can use it as a data: URL.
    """
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, dict):
        return {
            k: json_safe(v) for k, v in value.items() if k != "raw_response_objects"
        }
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _choice(
    body: Dict[str, Any], key: str, allowed: Tuple[str, ...], default: str
) -> Any:
    """Read an enum-ish field, rejecting anything not on the list."""
    value = body.get(key, default)
    if value not in allowed:
        raise ValueError(f"'{key}' must be one of {', '.join(allowed)}; got {value!r}")
    return value


def _number(body: Dict[str, Any], key: str, default: float) -> float:
    value = body.get(key, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"'{key}' must be a number; got {value!r}")
    return float(value)


def _bool(body: Dict[str, Any], key: str, default: bool) -> bool:
    """Strict boolean field.

    ``bool("false")`` is True, which silently turned "manga_mode": "false" into
    manga mode. Accept real booleans, 0/1, and the obvious string spellings;
    reject everything else instead of guessing.
    """
    value = body.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
    raise ValueError(f"'{key}' must be true or false; got {value!r}")


def _opt_str(body: Dict[str, Any], key: str, max_length: int = 4096) -> Optional[str]:
    """A string field that may be absent or null (but not a number or object)."""
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{key}' must be a string; got {type(value).__name__}")
    if len(value) > max_length:
        raise ValueError(f"'{key}' is longer than {max_length} characters")
    return value


class _HttpError(Exception):
    """An error with a status code, raised while reading or routing a request."""

    def __init__(
        self, status: int, message: str, headers: Optional[Dict[str, str]] = None
    ):
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = headers or {}


@dataclass
class _Reply:
    status: int
    payload: Any
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class _RequestInfo:
    """What the access log needs to know, filled in as parsing proceeds."""

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    method: str = "-"
    route: str = "-"
    origin: Optional[str] = None


class LensServer:
    def __init__(
        self,
        api: LensAPI,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: Optional[str] = None,
        allowed_origins: FrozenSet[str] = frozenset(),
        max_body_bytes: int = MAX_BODY_BYTES,
        request_timeout: float = REQUEST_TIMEOUT,
        header_timeout: float = HEADER_TIMEOUT,
        body_timeout: float = BODY_TIMEOUT,
        shutdown_grace: float = SHUTDOWN_GRACE,
    ):
        self.api = api
        self.host = host
        self.port = port
        self.token = token
        self.allowed_origins = frozenset(allowed_origins)
        self.local_only = is_loopback(host)
        self.max_body_bytes = max_body_bytes
        self.request_timeout = request_timeout
        self.header_timeout = header_timeout
        self.body_timeout = body_timeout
        self.shutdown_grace = shutdown_grace

        self._server: Optional[asyncio.AbstractServer] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._connections: Set["asyncio.Task[None]"] = set()

        if not self.local_only and not token:
            raise ValueError(
                f"Refusing to listen on {host} without --token. A daemon reachable "
                "from the network would let anyone spend your API key on Google "
                "requests. Bind 127.0.0.1, or set a token."
            )

    # ------------------------------------------------------------------ routes

    async def handle_ocr(self, body: Dict[str, Any]) -> Dict[str, Any]:
        source = self._resolve_source(body)
        overlay_path = _opt_str(body, "overlay_path")
        if overlay_path and not self.local_only:
            # Writing a file is a local affair; a remote caller gets the
            # overlay back in the response instead.
            raise ValueError(
                "'overlay_path' is only accepted when the daemon is bound to "
                'loopback; use "return_overlay": true to receive the image.'
            )
        return await self.api.process_image(
            source,
            ocr_language=_opt_str(body, "ocr_language"),
            target_translation_language=_opt_str(body, "translate_to"),
            source_translation_language=_opt_str(body, "translate_from"),
            output_overlay_path=overlay_path,
            ocr_preserve_line_breaks=_bool(body, "ocr_preserve_line_breaks", True),
            output_format=_choice(
                body,
                "output_format",
                ("full_text", "blocks", "lines", "detailed"),
                "full_text",
            ),
            overlay_mode=_choice(
                body, "overlay_mode", ("chromium", "legacy"), "chromium"
            ),
            vertical_text=_choice(
                body, "vertical_text", ("keep", "auto", "horizontal"), "auto"
            ),
            erase_mode=_choice(body, "erase_mode", ("patch", "hull"), "patch"),
            hull_padding=_number(body, "hull_padding", 0.45),
            outline_scale=_number(body, "outline_scale", 1.0),
            min_readable_px=_number(body, "min_readable_px", 0.0),
            text_align=_choice(
                body, "text_align", ("auto", "left", "center", "right"), "auto"
            ),
            manga_mode=_bool(body, "manga_mode", False),
            manga_box_growth=_number(body, "manga_box_growth", 1.45),
            return_overlay=_bool(body, "return_overlay", False),
            overlay_format=_choice(body, "overlay_format", ("png", "webp"), "png"),
        )

    async def handle_region(self, body: Dict[str, Any]) -> Dict[str, Any]:
        source = self._resolve_source(body)
        region = body.get("region")
        if not (isinstance(region, (list, tuple)) and len(region) == 4):
            raise ValueError("'region' must be [center_x, center_y, width, height]")
        values: List[float] = []
        for v in region:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"'region' values must be numbers; got {v!r}")
            if not math.isfinite(v):
                raise ValueError("'region' values must be finite")
            values.append(float(v))
        if values[2] <= 0 or values[3] <= 0:
            raise ValueError("'region' width and height must be positive")
        return await self.api.process_region(
            source,
            region=(values[0], values[1], values[2], values[3]),
            ocr_language=_opt_str(body, "ocr_language"),
            text_query=_opt_str(body, "text_query"),
            ocr_preserve_line_breaks=_bool(body, "ocr_preserve_line_breaks", True),
        )

    async def handle_version(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "service": "chrome-lens-py",
            "version": _version(),
            "python": sys.version.split()[0],
            "local_only": self.local_only,
            "features": {
                "return_overlay": ["png", "webp"],
                "accept_encoding": accept_encoding(),
            },
            "limits": {
                "max_body_bytes": self.max_body_bytes,
                "request_timeout_seconds": self.request_timeout,
            },
        }

    def _resolve_source(self, body: Dict[str, Any]) -> Any:
        """Accept inline base64 pixels, or - only locally - a path or URL."""
        raw = body.get("image_b64")
        if raw is not None and raw != "":
            if not isinstance(raw, str):
                raise ValueError("'image_b64' must be a base64 string")
            # Tolerate a full data: URL, which is what a canvas toDataURL gives,
            # and line-wrapped base64.
            if raw.startswith("data:"):
                _, _, raw = raw.partition(",")
            raw = "".join(raw.split())
            try:
                return base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError) as e:
                raise ValueError(f"'image_b64' is not valid base64: {e}") from e

        source = body.get("image")
        if not source:
            raise ValueError("Provide either 'image' (path or URL) or 'image_b64'.")
        if not isinstance(source, str):
            raise ValueError("'image' must be a string (path or URL)")
        if not self.local_only:
            # 'image' is something the daemon opens itself: a path, and so this
            # machine's disk, or a URL, and so a fetch to a host of the caller's
            # choosing. Neither belongs on a network-facing listener.
            raise ValueError(
                "This daemon is not bound to loopback, so it only accepts "
                "'image_b64'. Send the pixels rather than something to go read."
            )
        return source

    # ----------------------------------------------------------------- plumbing

    def _cors_headers(self, origin: Optional[str]) -> Dict[str, str]:
        """CORS headers, and only for an origin that was explicitly allowed."""
        if not origin or origin not in self.allowed_origins:
            return {}
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Expose-Headers": "X-Request-ID",
            "Access-Control-Max-Age": "86400",
            "Vary": "Origin",
        }

    def _respond(
        self,
        status: int,
        payload: Any,
        origin: Optional[str] = None,
        extra: Optional[Dict[str, str]] = None,
    ) -> bytes:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body)),
            "Connection": "close",
            **self._cors_headers(origin),
            **(extra or {}),
        }
        head = f"HTTP/1.1 {status} {_STATUS_TEXT.get(status, 'Error')}\r\n"
        head += "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        return head.encode("latin-1") + b"\r\n" + body

    async def _read_head(
        self, reader: asyncio.StreamReader
    ) -> Tuple[str, str, Dict[str, str]]:
        """Request line plus headers, bounded in size, count and time."""
        try:
            request_line = await asyncio.wait_for(
                reader.readline(), timeout=self.header_timeout
            )
        except ValueError:
            raise _HttpError(431, "Request line too long") from None
        if not request_line:
            raise ConnectionResetError("empty request")
        parts = request_line.decode("latin-1").split()
        if len(parts) < 2:
            raise _HttpError(400, "Malformed request line")
        method, path = parts[0], parts[1]

        headers: Dict[str, str] = {}
        while True:
            try:
                line = await asyncio.wait_for(
                    reader.readline(), timeout=self.header_timeout
                )
            except ValueError:
                raise _HttpError(431, "Header line too long") from None
            if line in (b"\r\n", b"\n", b""):
                break
            if len(headers) >= MAX_HEADER_COUNT:
                raise _HttpError(431, "Too many headers")
            key, _, value = line.decode("latin-1").partition(":")
            headers[key.strip().lower()] = value.strip()
        return method.upper(), path, headers

    def _content_length(self, headers: Dict[str, str]) -> int:
        if "transfer-encoding" in headers:
            raise _HttpError(400, "Transfer-Encoding is not supported; send a length")
        raw = headers.get("content-length", "")
        if raw == "":
            return 0
        if not raw.isascii() or not raw.isdigit():
            raise _HttpError(400, f"Invalid Content-Length: {raw[:40]!r}")
        length = int(raw)
        if length > self.max_body_bytes:
            raise _HttpError(
                413,
                f"Body of {length} bytes exceeds the {self.max_body_bytes} limit",
            )
        return length

    async def _drain(self, reader: asyncio.StreamReader, length: int) -> None:
        """Swallow a small unread body so closing does not reset the peer.

        Answering before reading the body and then closing makes the OS send a
        reset, which can destroy the reply in flight. Bounded, so it is not a
        way to make the daemon read arbitrary amounts.
        """
        if 0 < length <= _DRAIN_LIMIT:
            try:
                await asyncio.wait_for(reader.readexactly(length), timeout=2)
            except Exception:
                pass

    def _token_ok(self, headers: Dict[str, str]) -> bool:
        if not self.token:
            return True
        supplied = headers.get("authorization", "").removeprefix("Bearer ").strip()
        # Compare bytes: compare_digest raises TypeError on non-ASCII str. The
        # header was decoded as latin-1, so encoding back recovers the raw
        # bytes the client sent. Constant-time, so a wrong token cannot be
        # narrowed down by timing the replies.
        return hmac.compare_digest(
            supplied.encode("latin-1", "replace"), self.token.encode("utf-8")
        )

    async def _process(
        self, reader: asyncio.StreamReader, info: _RequestInfo
    ) -> _Reply:
        method, path, headers = await self._read_head(reader)
        supplied_id = headers.get("x-request-id", "")
        if _REQUEST_ID_RE.match(supplied_id):
            info.request_id = supplied_id
        info.method = method
        info.route = path.split("?", 1)[0].rstrip("/") or "/"
        info.origin = headers.get("origin")
        route, origin = info.route, info.origin
        length = self._content_length(headers)

        # A page can fire a request it is forbidden to read and still get the
        # effect it wanted: a Google call on your key, or a file opened on your
        # disk. So the Origin is judged before anything runs, rather than merely
        # reflected back in the response.
        if origin and origin not in self.allowed_origins:
            logger.warning(
                "[%s] Refused a request from origin %s", info.request_id, origin
            )
            await self._drain(reader, length)
            raise _HttpError(
                403,
                f"Origin {origin} is not allowed. Start the daemon "
                f"with --allow-origin {origin} if this is yours.",
            )

        if method == "OPTIONS":
            return _Reply(200, {"ok": True})

        if route in ("/health", "/"):
            return _Reply(
                200,
                {"status": "ok", "service": "chrome-lens-py", "version": _version()},
            )

        if not self._token_ok(headers):
            await self._drain(reader, length)
            raise _HttpError(
                401,
                "Invalid or missing token",
                {"WWW-Authenticate": 'Bearer realm="chrome-lens-py"'},
            )

        handlers: Dict[str, Tuple[str, Callable[..., Any]]] = {
            "/v1/ocr": ("POST", self.handle_ocr),
            "/v1/region": ("POST", self.handle_region),
            "/v1/version": ("GET", self.handle_version),
        }
        entry = handlers.get(route)
        if entry is None:
            await self._drain(reader, length)
            raise _HttpError(404, f"No such route: {route}")
        allowed_method, handler = entry
        if method != allowed_method:
            await self._drain(reader, length)
            raise _HttpError(
                405, f"Use {allowed_method}", {"Allow": f"{allowed_method}, OPTIONS"}
            )

        body = b""
        if method == "POST":
            # The second half of the browser lock. text/plain, form-encoded and
            # multipart are the three types a page may post without asking
            # permission first; insisting on JSON forces a preflight, which the
            # Origin check above then refuses.
            media_type = headers.get("content-type", "").split(";", 1)[0].strip()
            if media_type.lower() != "application/json":
                await self._drain(reader, length)
                raise _HttpError(415, "Content-Type must be application/json")
            if length:
                try:
                    body = await asyncio.wait_for(
                        reader.readexactly(length), timeout=self.body_timeout
                    )
                except asyncio.IncompleteReadError:
                    raise _HttpError(400, "Body is shorter than Content-Length")
                except asyncio.TimeoutError:
                    raise _HttpError(400, "Timed out reading the request body")

        try:
            parsed = json.loads(body or b"{}")
            if not isinstance(parsed, dict):
                raise ValueError("Body must be a JSON object")
            result = await asyncio.wait_for(
                handler(parsed), timeout=self.request_timeout
            )
            return _Reply(200, json_safe(result))
        except asyncio.TimeoutError:
            raise _HttpError(
                504, f"Request exceeded the {self.request_timeout:g}s limit"
            )
        except (json.JSONDecodeError, ValueError) as e:
            raise _HttpError(400, str(e))
        except LensImageError as e:
            raise _HttpError(400, str(e))
        except LensRateLimitError as e:
            extra = {}
            if e.retry_after is not None:
                extra["Retry-After"] = str(max(0, math.ceil(e.retry_after)))
            raise _HttpError(429, str(e), extra)
        except LensTimeoutError as e:
            raise _HttpError(504, str(e))
        except (LensConnectionError, LensAPIError) as e:
            logger.warning("[%s] Lens upstream error: %s", info.request_id, e)
            raise _HttpError(502, str(e))
        except LensException as e:
            logger.warning("[%s] Lens error: %s", info.request_id, e)
            raise _HttpError(500, str(e))
        except Exception:
            logger.exception("[%s] Unhandled error on %s", info.request_id, route)
            raise _HttpError(500, "Internal server error")

    @staticmethod
    async def _linger(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        timeout: float = 0.5,
        limit: int = 1 << 20,
    ) -> None:
        """Let the client read an error reply before the socket goes away.

        An error is often sent before the request has been read to the end - a
        431 on an oversized header, a 413 on a big body. Closing a socket that
        still has unread input makes the kernel answer with RST instead of
        FIN, and on Linux the RST can overtake the reply: the client sees
        "connection reset" and never learns why. So half-close our side (FIN
        goes out after the reply), then swallow what the client is still
        sending, briefly and boundedly, before closing for real. The same thing
        nginx calls lingering_close.
        """
        try:
            if writer.can_write_eof():
                writer.write_eof()
            deadline = time.monotonic() + timeout
            drained = 0
            while drained < limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                chunk = await asyncio.wait_for(reader.read(65536), remaining)
                if not chunk:
                    break
                drained += len(chunk)
        except (asyncio.TimeoutError, ConnectionError, OSError):
            pass

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        info = _RequestInfo()
        started = time.monotonic()
        status = 0
        try:
            try:
                reply = await self._process(reader, info)
            except _HttpError as e:
                reply = _Reply(
                    e.status,
                    {"error": e.message, "request_id": info.request_id},
                    dict(e.headers),
                )
            except (
                asyncio.IncompleteReadError,
                ConnectionResetError,
                asyncio.TimeoutError,
            ):
                return
            status = reply.status
            if reply.status >= 400 and isinstance(reply.payload, dict):
                reply.payload.setdefault("request_id", info.request_id)
                if reply.status >= 500 or reply.status == 429:
                    reply.payload.setdefault("type", _error_type(reply.status))
            reply.headers["X-Request-ID"] = info.request_id
            writer.write(
                self._respond(reply.status, reply.payload, info.origin, reply.headers)
            )
            await writer.drain()
            if reply.status >= 400:
                await self._linger(reader, writer)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("[%s] connection failed", info.request_id, exc_info=True)
        finally:
            if status:
                logger.info(
                    "[%s] %s %s -> %d (%.0f ms)",
                    info.request_id,
                    info.method,
                    info.route,
                    status,
                    (time.monotonic() - started) * 1000,
                )
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            if task is not None:
                self._connections.discard(task)

    # --------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Bind and begin accepting. ``self.port`` is updated if it was 0."""
        self._stop_event = asyncio.Event()
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port,
            limit=MAX_HEADER_LINE_BYTES,
        )
        sockets: Sequence[Any] = self._server.sockets or []
        if sockets:
            self.port = sockets[0].getsockname()[1]
        addresses = ", ".join(str(s.getsockname()) for s in sockets)
        logger.info("chrome-lens-py daemon listening on %s", addresses)
        if not self.allowed_origins:
            logger.info(
                "No browser origin is allowed, so only local programs can use "
                "this. Pass --allow-origin https://example.com to open it up."
            )

    def request_stop(self) -> None:
        """Ask serve_forever to shut down (call from the event loop thread)."""
        if self._stop_event is not None:
            self._stop_event.set()

    async def stop(self, grace: Optional[float] = None) -> None:
        """Stop accepting, let in-flight requests finish for `grace` seconds."""
        grace = self.shutdown_grace if grace is None else grace
        if self._server is not None:
            self._server.close()
        pending = {t for t in self._connections if not t.done()}
        if pending:
            logger.info(
                "Shutting down; waiting up to %.0fs for %d request(s).",
                grace,
                len(pending),
            )
            _, still_running = await asyncio.wait(pending, timeout=grace)
            for task in still_running:
                task.cancel()
            if still_running:
                logger.warning(
                    "Cancelled %d request(s) still running.", len(still_running)
                )
                await asyncio.gather(*still_running, return_exceptions=True)
        if self._server is not None:
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=2)
            except (asyncio.TimeoutError, Exception):
                pass
            self._server = None

    def _install_signal_handlers(
        self, loop: asyncio.AbstractEventLoop
    ) -> Callable[[], None]:
        """SIGINT/SIGTERM (and Ctrl+Break on Windows) -> graceful stop.

        ``loop.add_signal_handler`` does not exist on Windows' proactor loop, so
        fall back to ``signal.signal`` plus a thread-safe hop onto the loop.
        Returns a function restoring the previous handlers; after the first
        signal they are restored so a second Ctrl+C still kills a stuck drain.
        """
        restore: List[Callable[[], Any]] = []

        def trigger() -> None:
            undo()
            self.request_stop()

        def undo() -> None:
            while restore:
                restore.pop()()

        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            # remove_signal_handler resets the signal to SIG_DFL/default_int_handler,
            # not to whatever was there before - under asyncio.run that is the
            # Runner's own SIGINT handler, and losing it means Ctrl+C no longer
            # cancels the host program cleanly once the server stops. Save the
            # Python-level handler and put it back after removing ours.
            previous_handler = signal.getsignal(sig)
            try:
                loop.add_signal_handler(sig, trigger)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
            else:

                def remove(sig: int = sig, previous: Any = previous_handler) -> None:
                    loop.remove_signal_handler(sig)
                    if previous is not None:
                        with contextlib.suppress(ValueError, OSError, TypeError):
                            signal.signal(sig, previous)

                restore.append(remove)
                continue
            try:
                previous = signal.signal(
                    sig, lambda *_: loop.call_soon_threadsafe(trigger)
                )
            except (ValueError, OSError):  # not the main thread
                continue
            restore.append(partial(signal.signal, sig, previous))
        return undo

    async def serve_forever(self, install_signal_handlers: bool = True) -> None:
        await self.start()
        assert self._stop_event is not None
        undo: Callable[[], None] = lambda: None  # noqa: E731
        if install_signal_handlers:
            undo = self._install_signal_handlers(asyncio.get_running_loop())
        try:
            await self._stop_event.wait()
            logger.info("Stop requested; shutting down.")
        finally:
            undo()
            await self.stop()


def _error_type(status: int) -> str:
    return {
        429: "LensRateLimitError",
        502: "LensAPIError",
        504: "LensTimeoutError",
    }.get(status, "Error")


def _version() -> str:
    from . import __version__

    return __version__


async def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    token: Optional[str] = None,
    allowed_origins: FrozenSet[str] = frozenset(),
    max_body_bytes: int = MAX_BODY_BYTES,
    request_timeout: float = REQUEST_TIMEOUT,
    **api_kwargs: Any,
) -> None:
    async with LensAPI(**api_kwargs) as api:
        # Resolve the font once at boot rather than on the first request.
        await asyncio.to_thread(api._get_font_path)
        await LensServer(
            api,
            host=host,
            port=port,
            token=token,
            allowed_origins=allowed_origins,
            max_body_bytes=max_body_bytes,
            request_timeout=request_timeout,
        ).serve_forever()
