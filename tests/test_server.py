"""Route-level tests for the daemon, over real asyncio streams.

Each test starts a LensServer on an ephemeral loopback port and speaks raw HTTP
to it, so the request parsing, status codes and headers are the real ones.
"""

import asyncio
import base64
import contextlib
import io
import json
import signal
import threading
import time
from typing import Any, Dict, Optional, Tuple

import httpx
import pytest
from PIL import Image

from chrome_lens_py import api as api_module
from chrome_lens_py.api import LensAPI
from chrome_lens_py.exceptions import (
    LensAPIError,
    LensConnectionError,
    LensException,
    LensImageError,
    LensRateLimitError,
    LensTimeoutError,
)
from chrome_lens_py.server import LensServer, _bool, _number, _opt_str
from chrome_lens_py.utils.lens_betterproto import (
    LensOverlayServerResponse,
    TranslationDataStatusCode,
)


class FakeAPI:
    """Stands in for LensAPI: records calls, returns or raises on demand."""

    def __init__(self) -> None:
        self.calls = []
        self.result: Dict[str, Any] = {"ocr_text": "hello", "word_data": []}
        self.exc: Optional[BaseException] = None
        self.delay = 0.0

    async def _answer(self, kind: str, source: Any, kwargs: Dict[str, Any]):
        self.calls.append((kind, source, kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        return self.result

    async def process_image(self, source, **kwargs):
        return await self._answer("ocr", source, kwargs)

    async def process_region(self, source, **kwargs):
        return await self._answer("region", source, kwargs)


@contextlib.asynccontextmanager
async def running(api: Any = None, remote: bool = False, **kwargs):
    server = LensServer(api or FakeAPI(), port=0, **kwargs)
    if remote:
        # Pretend to be network-facing without binding a public interface.
        server.local_only = False
    await server.start()
    try:
        yield server
    finally:
        await server.stop(grace=1)


async def http(
    server: LensServer,
    method: str,
    path: str,
    json_body: Any = None,
    headers: Optional[Dict[str, str]] = None,
    raw_body: Optional[bytes] = None,
    content_length: Optional[str] = None,
    content_type: Optional[str] = "application/json",
    send_body: bool = True,
) -> Tuple[int, Dict[str, str], Any]:
    body = raw_body if raw_body is not None else b""
    if json_body is not None:
        body = json.dumps(json_body).encode()
    head = f"{method} {path} HTTP/1.1\r\nHost: test\r\n"
    if content_type and method == "POST":
        head += f"Content-Type: {content_type}\r\n"
    if content_length is not None:
        head += f"Content-Length: {content_length}\r\n"
    elif body:
        head += f"Content-Length: {len(body)}\r\n"
    for key, value in (headers or {}).items():
        head += f"{key}: {value}\r\n"
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(head.encode("latin-1") + b"\r\n" + (body if send_body else b""))
    await writer.drain()
    data = await asyncio.wait_for(reader.read(), timeout=20)
    writer.close()
    head_bytes, _, payload = data.partition(b"\r\n\r\n")
    lines = head_bytes.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    response_headers = {
        k.strip().lower(): v.strip()
        for k, _, v in (line.partition(":") for line in lines[1:])
    }
    parsed = json.loads(payload) if payload else None
    return status, response_headers, parsed


def png_b64(size=(16, 16)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


# ------------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_health_needs_no_token_and_says_who_it_is():
    async with running(token="secret") as server:
        status, headers, body = await http(server, "GET", "/health")
    assert status == 200 and body["status"] == "ok"
    assert body["service"] == "chrome-lens-py"
    assert headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_ocr_returns_the_api_result_and_forwards_typed_options():
    api = FakeAPI()
    async with running(api) as server:
        status, _, body = await http(
            server,
            "POST",
            "/v1/ocr",
            {
                "image_b64": "AQI=",
                "translate_to": "ru",
                "manga_mode": True,
                "hull_padding": 0.5,
                "erase_mode": "hull",
            },
        )
    assert status == 200 and body["ocr_text"] == "hello"
    kind, source, kwargs = api.calls[0]
    assert source == b"\x01\x02"
    assert kwargs["target_translation_language"] == "ru"
    assert kwargs["manga_mode"] is True
    assert kwargs["erase_mode"] == "hull" and kwargs["hull_padding"] == 0.5


@pytest.mark.asyncio
async def test_region_route():
    api = FakeAPI()
    async with running(api) as server:
        status, _, _ = await http(
            server,
            "POST",
            "/v1/region",
            {"image_b64": "AQI=", "region": [0.5, 0.5, 0.2, 0.2], "text_query": "q"},
        )
    assert status == 200
    assert api.calls[0][0] == "region" and api.calls[0][2]["text_query"] == "q"


@pytest.mark.asyncio
async def test_version_route_describes_the_daemon():
    async with running() as server:
        status, _, body = await http(server, "GET", "/v1/version")
    assert status == 200
    assert body["service"] == "chrome-lens-py" and body["version"]
    assert body["limits"]["max_body_bytes"] == server.max_body_bytes
    assert "png" in body["features"]["return_overlay"]


@pytest.mark.asyncio
async def test_version_route_requires_the_token_when_one_is_set():
    async with running(token="secret") as server:
        denied, _, _ = await http(server, "GET", "/v1/version")
        ok, _, _ = await http(
            server, "GET", "/v1/version", headers={"Authorization": "Bearer secret"}
        )
    assert (denied, ok) == (401, 200)


# --------------------------------------------------------------- request ids


@pytest.mark.asyncio
async def test_every_response_has_a_request_id_and_errors_repeat_it():
    async with running() as server:
        _, headers, _ = await http(server, "GET", "/health")
        assert len(headers["x-request-id"]) >= 8
        status, headers, body = await http(server, "GET", "/nope")
    assert status == 404
    assert body["request_id"] == headers["x-request-id"]


@pytest.mark.asyncio
async def test_a_sane_caller_request_id_is_kept_and_a_hostile_one_is_replaced():
    async with running() as server:
        _, kept, _ = await http(
            server, "GET", "/health", headers={"X-Request-ID": "trace-123"}
        )
        _, replaced, _ = await http(
            server, "GET", "/health", headers={"X-Request-ID": "bad id\x01;drop"}
        )
    assert kept["x-request-id"] == "trace-123"
    assert replaced["x-request-id"] != "bad id\x01;drop"


@pytest.mark.asyncio
async def test_requests_are_logged_with_their_id(caplog):
    caplog.set_level("INFO", logger="chrome_lens_py.server")
    async with running() as server:
        await http(server, "GET", "/health", headers={"X-Request-ID": "log-me"})
    assert any(
        "[log-me]" in r.getMessage() and "-> 200" in r.getMessage()
        for r in caplog.records
    )


# -------------------------------------------------------------------------- 400


@pytest.mark.asyncio
async def test_malformed_json_is_400():
    async with running() as server:
        status, _, body = await http(server, "POST", "/v1/ocr", raw_body=b"{nope")
    assert status == 400 and "error" in body


@pytest.mark.asyncio
async def test_json_that_is_not_an_object_is_400():
    async with running() as server:
        status, _, body = await http(server, "POST", "/v1/ocr", raw_body=b"[1]")
    assert status == 400 and "JSON object" in body["error"]


@pytest.mark.asyncio
async def test_invalid_utf8_body_is_400_not_500():
    async with running() as server:
        status, _, _ = await http(server, "POST", "/v1/ocr", raw_body=b"\xff\xfe{}")
    assert status == 400


@pytest.mark.parametrize("length", ["abc", "-5", "1e3", "12 34", "\u00b2"])
@pytest.mark.asyncio
async def test_invalid_content_length_is_400_not_413(length):
    async with running() as server:
        status, _, body = await http(
            server, "POST", "/v1/ocr", content_length=length, send_body=False
        )
    assert status == 400 and "Content-Length" in body["error"]


@pytest.mark.asyncio
async def test_non_string_image_b64_is_400_not_500():
    async with running() as server:
        for bad in (123, ["x"], {"a": 1}, True):
            status, _, _ = await http(server, "POST", "/v1/ocr", {"image_b64": bad})
            assert status == 400


@pytest.mark.asyncio
async def test_invalid_base64_and_missing_image_are_400():
    async with running() as server:
        a, _, _ = await http(server, "POST", "/v1/ocr", {"image_b64": "%%%"})
        b, _, _ = await http(server, "POST", "/v1/ocr", {})
        c, _, _ = await http(server, "POST", "/v1/ocr", {"image": 5})
    assert (a, b, c) == (400, 400, 400)


@pytest.mark.asyncio
async def test_field_validation_errors_are_400():
    async with running() as server:
        for body in (
            {"image_b64": "AQI=", "outline_scale": "big"},
            {"image_b64": "AQI=", "erase_mode": "rm -rf"},
            {"image_b64": "AQI=", "translate_to": 5},
            {"image_b64": "AQI=", "manga_mode": "maybe"},
            {"image_b64": "AQI=", "return_overlay": []},
            {"image_b64": "AQI=", "hull_padding": float("nan")},
        ):
            status, _, _ = await http(server, "POST", "/v1/ocr", body)
            assert status == 400, body


@pytest.mark.asyncio
async def test_region_validation_is_400():
    async with running() as server:
        for region in ([1, 2, 3], "x", [0.5, 0.5, "a", 0.1], [0.5, 0.5, 0, 0.1]):
            status, _, _ = await http(
                server, "POST", "/v1/region", {"image_b64": "AQI=", "region": region}
            )
            assert status == 400, region


@pytest.mark.asyncio
async def test_string_false_is_false_not_true():
    api = FakeAPI()
    async with running(api) as server:
        status, _, _ = await http(
            server,
            "POST",
            "/v1/ocr",
            {"image_b64": "AQI=", "manga_mode": "false", "ocr_preserve_line_breaks": 0},
        )
    assert status == 200
    assert api.calls[0][2]["manga_mode"] is False
    assert api.calls[0][2]["ocr_preserve_line_breaks"] is False


@pytest.mark.asyncio
async def test_oversized_header_line_is_431():
    async with running() as server:
        status, _, _ = await http(
            server, "GET", "/health", headers={"X-Junk": "a" * 40000}
        )
    assert status == 431


@pytest.mark.asyncio
async def test_chunked_transfer_encoding_is_refused_clearly():
    async with running() as server:
        status, _, body = await http(
            server,
            "POST",
            "/v1/ocr",
            headers={"Transfer-Encoding": "chunked"},
            send_body=False,
        )
    assert status == 400 and "Transfer-Encoding" in body["error"]


# ---------------------------------------------------------------------- 401/403


@pytest.mark.asyncio
async def test_missing_and_wrong_tokens_are_401():
    async with running(token="s3cret") as server:
        missing, headers, _ = await http(server, "POST", "/v1/ocr", {})
        wrong, _, _ = await http(
            server, "POST", "/v1/ocr", {}, headers={"Authorization": "Bearer nope"}
        )
    assert (missing, wrong) == (401, 401)
    assert "Bearer" in headers["www-authenticate"]


@pytest.mark.asyncio
async def test_non_ascii_token_header_is_401_not_a_crash():
    async with running(token="s3cret") as server:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        writer.write(
            b"POST /v1/ocr HTTP/1.1\r\nContent-Type: application/json\r\n"
            b"Authorization: Bearer caf\xc3\xa9\r\nContent-Length: 0\r\n\r\n"
        )
        await writer.drain()
        data = await reader.read()
        writer.close()
    assert data.startswith(b"HTTP/1.1 401")


@pytest.mark.asyncio
async def test_a_non_ascii_configured_token_works():
    token = "pässwörd-é"
    async with running(token=token) as server:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        body = json.dumps({"image_b64": "AQI="}).encode()
        writer.write(
            b"POST /v1/ocr HTTP/1.1\r\nContent-Type: application/json\r\n"
            b"Authorization: Bearer " + token.encode("utf-8") + b"\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        await writer.drain()
        data = await reader.read()
        writer.close()
    assert data.startswith(b"HTTP/1.1 200")


@pytest.mark.asyncio
async def test_browser_origins_are_refused_unless_allowed():
    async with running() as server:
        status, _, body = await http(
            server,
            "POST",
            "/v1/ocr",
            {"image_b64": "AQI="},
            headers={"Origin": "https://evil.example"},
        )
    assert status == 403 and "--allow-origin" in body["error"]


@pytest.mark.asyncio
async def test_an_allowed_origin_gets_cors_headers():
    origin = "https://mine.example"
    async with running(allowed_origins=frozenset({origin})) as server:
        status, headers, _ = await http(
            server, "POST", "/v1/ocr", {"image_b64": "AQI="}, headers={"Origin": origin}
        )
        preflight, pre_headers, _ = await http(
            server, "OPTIONS", "/v1/ocr", headers={"Origin": origin}
        )
    assert status == 200 and headers["access-control-allow-origin"] == origin
    assert preflight == 200 and "POST" in pre_headers["access-control-allow-methods"]


# ------------------------------------------------------- 404 / 405 / 413 / 415


@pytest.mark.asyncio
async def test_unknown_route_is_404():
    async with running() as server:
        status, _, _ = await http(server, "POST", "/v2/ocr", {})
    assert status == 404


@pytest.mark.asyncio
async def test_wrong_method_is_405_with_allow_header():
    async with running() as server:
        get_ocr, headers, _ = await http(server, "GET", "/v1/ocr")
        post_version, _, _ = await http(server, "POST", "/v1/version", {})
    assert get_ocr == 405 and "POST" in headers["allow"]
    assert post_version == 405


@pytest.mark.asyncio
async def test_body_over_the_limit_is_413_before_it_is_read():
    async with running(max_body_bytes=1000) as server:
        status, _, body = await http(
            server, "POST", "/v1/ocr", content_length="1001", send_body=False
        )
        ok, _, _ = await http(server, "POST", "/v1/ocr", {"image_b64": "AQI="})
    assert status == 413 and "1000" in body["error"]
    assert ok == 200


@pytest.mark.parametrize("content_type", ["text/plain", "multipart/form-data", None])
@pytest.mark.asyncio
async def test_non_json_content_type_is_415(content_type):
    async with running() as server:
        status, _, _ = await http(
            server,
            "POST",
            "/v1/ocr",
            raw_body=b"{}",
            content_type=content_type,
        )
    assert status == 415


@pytest.mark.asyncio
async def test_content_type_parameters_and_case_are_tolerated():
    async with running() as server:
        status, _, _ = await http(
            server,
            "POST",
            "/v1/ocr",
            {"image_b64": "AQI="},
            content_type="Application/JSON; charset=utf-8",
        )
    assert status == 200


# ------------------------------------------------------- remote-only restrictions


@pytest.mark.asyncio
async def test_remote_daemon_rejects_paths_and_overlay_paths_but_takes_pixels():
    async with running(remote=True, token="t") as server:
        auth = {"Authorization": "Bearer t"}
        path, _, _ = await http(
            server, "POST", "/v1/ocr", {"image": "C:/secret.png"}, headers=auth
        )
        overlay, _, body = await http(
            server,
            "POST",
            "/v1/ocr",
            {"image_b64": "AQI=", "overlay_path": "C:/x.png"},
            headers=auth,
        )
        pixels, _, _ = await http(
            server, "POST", "/v1/ocr", {"image_b64": "AQI="}, headers=auth
        )
    assert (path, overlay, pixels) == (400, 400, 200)
    assert "return_overlay" in body["error"]


# ---------------------------------------------------------- upstream error mapping


@pytest.mark.parametrize(
    "exc,status",
    [
        (LensImageError("cannot decode"), 400),
        (LensTimeoutError("slow"), 504),
        (LensConnectionError("down"), 502),
        (LensAPIError("HTTP error: 500", status_code=500), 502),
        (LensException("other"), 500),
    ],
)
@pytest.mark.asyncio
async def test_lens_errors_map_to_http_statuses(exc, status):
    api = FakeAPI()
    api.exc = exc
    async with running(api) as server:
        got, _, body = await http(server, "POST", "/v1/ocr", {"image_b64": "AQI="})
    assert got == status
    assert str(exc) in body["error"]


@pytest.mark.asyncio
async def test_rate_limit_is_429_and_forwards_retry_after():
    api = FakeAPI()
    api.exc = LensRateLimitError("slow down", status_code=429, retry_after=2.4)
    async with running(api) as server:
        status, headers, body = await http(
            server, "POST", "/v1/ocr", {"image_b64": "AQI="}
        )
    assert status == 429 and headers["retry-after"] == "3"
    assert body["type"] == "LensRateLimitError"


@pytest.mark.asyncio
async def test_unexpected_errors_are_500_and_do_not_leak_details():
    api = FakeAPI()
    api.exc = RuntimeError("/home/secret/path exploded")
    async with running(api) as server:
        status, headers, body = await http(
            server, "POST", "/v1/ocr", {"image_b64": "AQI="}
        )
    assert status == 500
    assert "secret" not in json.dumps(body)
    assert body["request_id"] == headers["x-request-id"]


@pytest.mark.asyncio
async def test_per_request_time_limit_is_504():
    api = FakeAPI()
    api.delay = 5
    async with running(api, request_timeout=0.2) as server:
        started = time.monotonic()
        status, _, body = await http(server, "POST", "/v1/ocr", {"image_b64": "AQI="})
    assert status == 504 and "limit" in body["error"]
    assert time.monotonic() - started < 3


# --------------------------------------------------------------- return_overlay


@pytest.mark.asyncio
async def test_return_overlay_is_base64_in_the_response():
    api = FakeAPI()
    api.result = {
        "translated_text": "hola",
        "overlay_image": b"\x89PNGfake",
        "overlay_mime_type": "image/png",
    }
    async with running(api) as server:
        status, _, body = await http(
            server,
            "POST",
            "/v1/ocr",
            {"image_b64": "AQI=", "translate_to": "es", "return_overlay": True},
        )
    assert status == 200
    assert base64.b64decode(body["overlay_image"]) == b"\x89PNGfake"
    assert body["overlay_mime_type"] == "image/png"
    assert api.calls[0][2]["return_overlay"] is True
    assert api.calls[0][2]["overlay_format"] == "png"


# ----------------------------------------------------- the event loop stays free


def _translated_response() -> bytes:
    response = LensOverlayServerResponse()
    gleam = response.objects_response.deep_gleams.add()
    gleam.translation.translation = "hola"
    gleam.translation.status.code = TranslationDataStatusCode.SUCCESS
    return response.SerializeToString()


@pytest.mark.asyncio
async def test_health_answers_while_a_slow_render_runs(monkeypatch):
    render_threads = []

    def slow_render(original, objects_response, **kwargs):
        render_threads.append(threading.current_thread())
        time.sleep(1.2)  # a blocking render: would freeze the loop if run on it
        return Image.new("RGBA", original.size, (0, 0, 0, 255))

    monkeypatch.setattr(api_module, "render_translation_overlay", slow_render)
    monkeypatch.setattr(LensAPI, "_get_font_path", lambda self: None)

    api = LensAPI(
        proxy={
            "all://": httpx.MockTransport(
                lambda r: httpx.Response(200, content=_translated_response())
            )
        },
        trust_env=False,
        max_retries=0,
    )
    async with running(api) as server:
        ocr = asyncio.create_task(
            http(
                server,
                "POST",
                "/v1/ocr",
                {
                    "image_b64": png_b64(),
                    "translate_to": "es",
                    "return_overlay": True,
                },
            )
        )
        # Wait until the render is genuinely in progress.
        for _ in range(100):
            if render_threads:
                break
            await asyncio.sleep(0.02)
        assert render_threads, "the render never started"

        started = time.monotonic()
        status, _, _ = await http(server, "GET", "/health")
        health_latency = time.monotonic() - started
        assert status == 200
        assert not ocr.done(), "render finished too early to prove anything"
        assert health_latency < 0.6, f"/health blocked for {health_latency:.2f}s"

        ocr_status, _, ocr_body = await ocr
    assert ocr_status == 200 and ocr_body["overlay_image"]
    assert render_threads[0] is not threading.main_thread()
    await api.aclose()


# ------------------------------------------------------------ graceful shutdown


@pytest.mark.asyncio
async def test_shutdown_lets_an_in_flight_request_finish_then_refuses_new_ones():
    api = FakeAPI()
    api.delay = 0.5
    server = LensServer(api, port=0, shutdown_grace=5)
    serving = asyncio.create_task(server.serve_forever(install_signal_handlers=False))
    for _ in range(100):
        if server._server is not None:
            break
        await asyncio.sleep(0.02)

    slow = asyncio.create_task(http(server, "POST", "/v1/ocr", {"image_b64": "AQI="}))
    await asyncio.sleep(0.15)  # request is now in flight
    server.request_stop()

    status, _, _ = await slow
    assert status == 200  # not cut off
    await asyncio.wait_for(serving, timeout=5)
    with pytest.raises(OSError):
        await asyncio.open_connection("127.0.0.1", server.port)


@pytest.mark.asyncio
async def test_shutdown_cancels_requests_that_outlive_the_grace_period():
    api = FakeAPI()
    api.delay = 30
    server = LensServer(api, port=0, shutdown_grace=0.2)
    serving = asyncio.create_task(server.serve_forever(install_signal_handlers=False))
    for _ in range(100):
        if server._server is not None:
            break
        await asyncio.sleep(0.02)
    stuck = asyncio.create_task(http(server, "POST", "/v1/ocr", {"image_b64": "AQI="}))
    await asyncio.sleep(0.15)
    started = time.monotonic()
    server.request_stop()
    await asyncio.wait_for(serving, timeout=5)
    assert time.monotonic() - started < 4
    stuck.cancel()
    with contextlib.suppress(BaseException):
        await stuck


@pytest.mark.asyncio
async def test_signal_handlers_are_installed_and_restored():
    server = LensServer(FakeAPI(), port=0)
    await server.start()
    before = signal.getsignal(signal.SIGINT)
    undo = server._install_signal_handlers(asyncio.get_running_loop())
    assert signal.getsignal(signal.SIGINT) is not before or hasattr(
        asyncio.get_running_loop(), "_signal_handlers"
    )
    undo()
    assert signal.getsignal(signal.SIGINT) is before
    await server.stop(grace=0)


@pytest.mark.asyncio
async def test_sigint_requests_a_graceful_stop():
    server = LensServer(FakeAPI(), port=0)
    serving = asyncio.create_task(server.serve_forever())
    for _ in range(100):
        if server._server is not None:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.1)
    signal.raise_signal(signal.SIGINT)  # handled, so no KeyboardInterrupt
    await asyncio.wait_for(serving, timeout=5)


# --------------------------------------------------------------- field helpers


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        ("false", False),
        ("TRUE", True),
        ("0", False),
        (1, True),
        (0, False),
    ],
)
def test_bool_accepts_real_booleans_and_unambiguous_spellings(value, expected):
    assert _bool({"k": value}, "k", not expected) is expected


@pytest.mark.parametrize("value", ["maybe", 2, -1, 1.5, [], {}, None, ""])
def test_bool_rejects_everything_else(value):
    with pytest.raises(ValueError, match="true or false"):
        _bool({"k": value}, "k", False)


def test_bool_default_applies_when_absent():
    assert _bool({}, "k", True) is True


def test_number_rejects_nan_and_infinity():
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            _number({"k": bad}, "k", 1.0)


def test_opt_str():
    assert _opt_str({}, "k") is None
    assert _opt_str({"k": None}, "k") is None
    assert _opt_str({"k": "en"}, "k") == "en"
    with pytest.raises(ValueError):
        _opt_str({"k": 5}, "k")
    with pytest.raises(ValueError):
        _opt_str({"k": "x" * 5000}, "k")
