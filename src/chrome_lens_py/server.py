"""A small local HTTP daemon around LensAPI.

Why this exists: importing Pillow, protobuf and httpx costs roughly a second,
and ShareX pays it on every single screenshot. Keeping one warm process turns
that into a socket write. The same endpoint doubles as a backend for browser
userscripts, which is why CORS is handled here.

Deliberately built on asyncio directly rather than a web framework: the whole
point is to start fast, and adding FastAPI/uvicorn would put back the import
cost we are removing. Bound to loopback by default.
"""

import asyncio
import base64
import binascii
import json
import logging
from typing import Any, Dict, Optional, Tuple

from .api import LensAPI
from .exceptions import LensException

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 32 * 1024 * 1024
_STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    500: "Internal Server Error",
}


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


class LensServer:
    def __init__(
        self,
        api: LensAPI,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: Optional[str] = None,
        allow_origin: str = "*",
    ):
        self.api = api
        self.host = host
        self.port = port
        self.token = token
        self.allow_origin = allow_origin

    # ------------------------------------------------------------------ routes

    async def handle_ocr(self, body: Dict[str, Any]) -> Dict[str, Any]:
        source = self._resolve_source(body)
        return await self.api.process_image(
            source,
            ocr_language=body.get("ocr_language"),
            target_translation_language=body.get("translate_to"),
            source_translation_language=body.get("translate_from"),
            output_overlay_path=body.get("overlay_path"),
            output_format=body.get("output_format", "full_text"),
            overlay_mode=body.get("overlay_mode", "chromium"),
            vertical_text=body.get("vertical_text", "auto"),
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
        )

    def _resolve_source(self, body: Dict[str, Any]) -> Any:
        """Accept either a path/URL or inline base64 image bytes."""
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
        return source

    # ----------------------------------------------------------------- plumbing

    def _cors_headers(self) -> Dict[str, str]:
        return {
            "Access-Control-Allow-Origin": self.allow_origin,
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400",
        }

    def _respond(
        self, status: int, payload: Any, extra: Optional[Dict[str, str]] = None
    ) -> bytes:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body)),
            "Connection": "close",
            **self._cors_headers(),
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

            if method == "OPTIONS":
                writer.write(self._respond(200, {"ok": True}))
                await writer.drain()
                return

            if route in ("/health", "/"):
                writer.write(
                    self._respond(200, {"status": "ok", "service": "chrome-lens-py"})
                )
                await writer.drain()
                return

            if self.token:
                supplied = (
                    headers.get("authorization", "").removeprefix("Bearer ").strip()
                )
                if supplied != self.token:
                    writer.write(
                        self._respond(401, {"error": "Invalid or missing token"})
                    )
                    await writer.drain()
                    return

            handlers = {"/v1/ocr": self.handle_ocr, "/v1/region": self.handle_region}
            handler = handlers.get(route)
            if handler is None:
                writer.write(self._respond(404, {"error": f"No such route: {route}"}))
                await writer.drain()
                return
            if method != "POST":
                writer.write(self._respond(405, {"error": "Use POST"}))
                await writer.drain()
                return

            try:
                parsed = json.loads(body or b"{}")
                if not isinstance(parsed, dict):
                    raise ValueError("Body must be a JSON object")
                result = await handler(parsed)
                writer.write(self._respond(200, json_safe(result)))
            except (json.JSONDecodeError, ValueError) as e:
                writer.write(self._respond(400, {"error": str(e)}))
            except LensException as e:
                logger.warning("Lens error on %s: %s", route, e)
                writer.write(
                    self._respond(500, {"error": str(e), "type": type(e).__name__})
                )
            except Exception as e:
                logger.exception("Unhandled error on %s", route)
                writer.write(
                    self._respond(500, {"error": str(e), "type": type(e).__name__})
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
        async with server:
            await server.serve_forever()


async def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    token: Optional[str] = None,
    allow_origin: str = "*",
    **api_kwargs: Any,
) -> None:
    async with LensAPI(**api_kwargs) as api:
        # Resolve the font once at boot rather than on the first request.
        api._get_font_path()
        await LensServer(
            api, host=host, port=port, token=token, allow_origin=allow_origin
        ).serve_forever()
