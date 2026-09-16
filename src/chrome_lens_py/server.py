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
"""

import asyncio
import base64
import binascii
import hmac
import ipaddress
import json
import logging
from typing import Any, Dict, FrozenSet, Optional, Tuple

from .api import LensAPI
from .exceptions import LensException

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 32 * 1024 * 1024
_STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    415: "Unsupported Media Type",
    500: "Internal Server Error",
}


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


def _choice(body: Dict[str, Any], key: str, allowed: Tuple[str, ...], default: str):
    """Read an enum-ish field, rejecting anything not on the list."""
    value = body.get(key, default)
    if value not in allowed:
        raise ValueError(f"'{key}' must be one of {', '.join(allowed)}; got {value!r}")
    return value


def _number(body: Dict[str, Any], key: str, default: float) -> float:
    value = body.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{key}' must be a number; got {value!r}")
    return float(value)


class LensServer:
    def __init__(
        self,
        api: LensAPI,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: Optional[str] = None,
        allowed_origins: FrozenSet[str] = frozenset(),
    ):
        self.api = api
        self.host = host
        self.port = port
        self.token = token
        self.allowed_origins = frozenset(allowed_origins)
        self.local_only = is_loopback(host)

        if not self.local_only and not token:
            raise ValueError(
                f"Refusing to listen on {host} without --token. A daemon reachable "
                "from the network would let anyone spend your API key on Google "
                "requests. Bind 127.0.0.1, or set a token."
            )

    # ------------------------------------------------------------------ routes

    async def handle_ocr(self, body: Dict[str, Any]) -> Dict[str, Any]:
        source = self._resolve_source(body)
        return await self.api.process_image(
            source,
            ocr_language=body.get("ocr_language"),
            target_translation_language=body.get("translate_to"),
            source_translation_language=body.get("translate_from"),
            # Writing a file is a local affair; a remote caller gets the
            # overlay back in the response like everything else.
            output_overlay_path=body.get("overlay_path") if self.local_only else None,
            ocr_preserve_line_breaks=bool(body.get("ocr_preserve_line_breaks", True)),
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
            manga_mode=bool(body.get("manga_mode", False)),
            manga_box_growth=_number(body, "manga_box_growth", 1.45),
        )

    async def handle_region(self, body: Dict[str, Any]) -> Dict[str, Any]:
        source = self._resolve_source(body)
        region = body.get("region")
        if not (isinstance(region, (list, tuple)) and len(region) == 4):
            raise ValueError("'region' must be [center_x, center_y, width, height]")
        return await self.api.process_region(
            source,
            region=tuple(float(v) for v in region),
            ocr_language=body.get("ocr_language"),
            text_query=body.get("text_query"),
            ocr_preserve_line_breaks=bool(body.get("ocr_preserve_line_breaks", True)),
        )

    def _resolve_source(self, body: Dict[str, Any]) -> Any:
        """Accept inline base64 pixels, or - only locally - a path or URL."""
        if body.get("image_b64"):
            raw = body["image_b64"]
            # Tolerate a full data: URL, which is what a canvas toDataURL gives.
            if raw.startswith("data:"):
                _, _, raw = raw.partition(",")
            try:
                return base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError) as e:
                raise ValueError(f"'image_b64' is not valid base64: {e}") from e

        source = body.get("image")
        if not source:
            raise ValueError("Provide either 'image' (path or URL) or 'image_b64'.")
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

    async def _read_request(
        self, reader: asyncio.StreamReader
    ) -> Tuple[str, str, Dict[str, str], bytes]:
        request_line = await asyncio.wait_for(reader.readline(), timeout=15)
        if not request_line:
            raise ConnectionResetError("empty request")
        parts = request_line.decode("latin-1").split()
        method, path = (parts + ["", ""])[:2]

        headers: Dict[str, str] = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=15)
            if line in (b"\r\n", b"\n", b""):
                break
            key, _, value = line.decode("latin-1").partition(":")
            headers[key.strip().lower()] = value.strip()

        length = int(headers.get("content-length", "0") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError(
                f"Body of {length} bytes exceeds the {MAX_BODY_BYTES} limit"
            )
        body = (
            await asyncio.wait_for(reader.readexactly(length), timeout=120)
            if length
            else b""
        )
        return method.upper(), path, headers, body

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            try:
                method, path, headers, body = await self._read_request(reader)
            except (
                asyncio.IncompleteReadError,
                ConnectionResetError,
                asyncio.TimeoutError,
            ):
                return
            except ValueError as e:
                writer.write(self._respond(413, {"error": str(e)}))
                await writer.drain()
                return

            route = path.split("?", 1)[0].rstrip("/") or "/"
            origin = headers.get("origin")

            # A page can fire a request it is forbidden to read and still get
            # the effect it wanted: a Google call on your key, or a file opened
            # on your disk. So the Origin is judged before anything runs, rather
            # than merely reflected back in the response.
            if origin and origin not in self.allowed_origins:
                logger.warning("Refused a request from origin %s", origin)
                writer.write(
                    self._respond(
                        403,
                        {
                            "error": (
                                f"Origin {origin} is not allowed. Start the daemon "
                                f"with --allow-origin {origin} if this is yours."
                            )
                        },
                    )
                )
                await writer.drain()
                return

            if method == "OPTIONS":
                writer.write(self._respond(200, {"ok": True}, origin))
                await writer.drain()
                return

            if route in ("/health", "/"):
                writer.write(
                    self._respond(
                        200,
                        {
                            "status": "ok",
                            "service": "chrome-lens-py",
                            "version": _version(),
                        },
                        origin,
                    )
                )
                await writer.drain()
                return

            if self.token:
                supplied = (
                    headers.get("authorization", "").removeprefix("Bearer ").strip()
                )
                # Constant-time, so a wrong token cannot be narrowed down by
                # timing the replies.
                if not hmac.compare_digest(supplied, self.token):
                    writer.write(
                        self._respond(
                            401, {"error": "Invalid or missing token"}, origin
                        )
                    )
                    await writer.drain()
                    return

            handlers = {"/v1/ocr": self.handle_ocr, "/v1/region": self.handle_region}
            handler = handlers.get(route)
            if handler is None:
                writer.write(
                    self._respond(404, {"error": f"No such route: {route}"}, origin)
                )
                await writer.drain()
                return
            if method != "POST":
                writer.write(self._respond(405, {"error": "Use POST"}, origin))
                await writer.drain()
                return

            # The second half of the browser lock. text/plain, form-encoded and
            # multipart are the three types a page may post without asking
            # permission first; insisting on JSON forces a preflight, which the
            # Origin check above then refuses.
            media_type = headers.get("content-type", "").split(";", 1)[0].strip()
            if media_type != "application/json":
                writer.write(
                    self._respond(
                        415, {"error": "Content-Type must be application/json"}, origin
                    )
                )
                await writer.drain()
                return

            try:
                parsed = json.loads(body or b"{}")
                if not isinstance(parsed, dict):
                    raise ValueError("Body must be a JSON object")
                result = await handler(parsed)
                writer.write(self._respond(200, json_safe(result), origin))
            except (json.JSONDecodeError, ValueError) as e:
                writer.write(self._respond(400, {"error": str(e)}, origin))
            except LensException as e:
                logger.warning("Lens error on %s: %s", route, e)
                writer.write(
                    self._respond(
                        500, {"error": str(e), "type": type(e).__name__}, origin
                    )
                )
            except Exception as e:
                logger.exception("Unhandled error on %s", route)
                writer.write(
                    self._respond(
                        500, {"error": str(e), "type": type(e).__name__}, origin
                    )
                )
            await writer.drain()
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def serve_forever(self) -> None:
        server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        addresses = ", ".join(str(s.getsockname()) for s in server.sockets or [])
        logger.info("chrome-lens-py daemon listening on %s", addresses)
        if not self.allowed_origins:
            logger.info(
                "No browser origin is allowed, so only local programs can use "
                "this. Pass --allow-origin https://example.com to open it up."
            )
        async with server:
            await server.serve_forever()


def _version() -> str:
    from . import __version__

    return __version__


async def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    token: Optional[str] = None,
    allowed_origins: FrozenSet[str] = frozenset(),
    **api_kwargs: Any,
) -> None:
    async with LensAPI(**api_kwargs) as api:
        # Resolve the font once at boot rather than on the first request.
        api._get_font_path()
        await LensServer(
            api, host=host, port=port, token=token, allowed_origins=allowed_origins
        ).serve_forever()
