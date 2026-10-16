"""The routes a managed daemon adds: /v1/ocr/raw, /v1/cli, /v1/status, /v1/shutdown,
plus the idle timeout and the AF_UNIX transport."""

import asyncio
import json
import os
import time
from typing import Dict, Optional, Tuple

import pytest

from chrome_lens_py.exceptions import LensImageError, LensRateLimitError
from chrome_lens_py.server import LensServer

from .test_server import FakeAPI, png_b64, running

POSIX = os.name == "posix"
TOKEN = "t" * 24
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f0005fe02fea7d6c9a00000000049454e44ae426082"
)


async def request(
    server: LensServer,
    method: str,
    path: str,
    body: bytes = b"",
    content_type: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    unix: bool = False,
) -> Tuple[int, Dict[str, str], bytes]:
    head = f"{method} {path} HTTP/1.1\r\nHost: test\r\n"
    if content_type:
        head += f"Content-Type: {content_type}\r\n"
    if body or method == "POST":
        head += f"Content-Length: {len(body)}\r\n"
    for key, value in (headers or {}).items():
        head += f"{key}: {value}\r\n"
    if unix:
        reader, writer = await asyncio.open_unix_connection(server.unix_path)
    else:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(head.encode("latin-1") + b"\r\n" + body)
    await writer.drain()
    data = await asyncio.wait_for(reader.read(), timeout=20)
    writer.close()
    head_bytes, _, payload = data.partition(b"\r\n\r\n")
    lines = head_bytes.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    out = {
        k.strip().lower(): v.strip()
        for k, _, v in (line.partition(":") for line in lines[1:])
    }
    return status, out, payload


async def cli_ok(**kwargs):
    return {"exit_code": 0, "stdout": "", "stderr": ""}


# ---------------------------------------------------------------- /v1/ocr/raw


async def raw(server, query="", body=PNG, content_type="image/png", headers=None):
    return await request(
        server,
        "POST",
        "/v1/ocr/raw" + query,
        body,
        content_type,
        AUTH if headers is None else headers,
    )


@pytest.mark.asyncio
async def test_raw_returns_the_ocr_text_as_plain_text():
    api = FakeAPI()
    api.result = {"ocr_text": "привет\nмир", "word_data": []}
    async with running(api, token=TOKEN) as server:
        status, headers, body = await raw(server)
    assert status == 200
    assert headers["content-type"] == "text/plain; charset=utf-8"
    assert body.decode("utf-8") == "привет\nмир"
    kind, source, kwargs = api.calls[0]
    assert source == PNG  # the bytes themselves, not a path
    assert kwargs["target_translation_language"] is None


@pytest.mark.asyncio
async def test_raw_returns_the_translation_when_one_was_asked_for():
    api = FakeAPI()
    api.result = {"ocr_text": "hello", "translated_text": "привет"}
    async with running(api, token=TOKEN) as server:
        _, _, body = await raw(
            server, "?translate_to=ru&translate_from=en&ocr_language=en"
        )
    assert body.decode() == "привет"
    kwargs = api.calls[0][2]
    assert kwargs["target_translation_language"] == "ru"
    assert kwargs["source_translation_language"] == "en"
    assert kwargs["ocr_language"] == "en"


@pytest.mark.asyncio
async def test_raw_falls_back_to_ocr_text_when_no_translation_came_back():
    api = FakeAPI()
    api.result = {"ocr_text": "hello", "translated_text": None}
    async with running(api, token=TOKEN) as server:
        _, _, body = await raw(server, "?translate_to=ru")
    assert body == b"hello"


@pytest.mark.asyncio
async def test_raw_with_nothing_recognised_is_an_empty_200():
    api = FakeAPI()
    api.result = {"ocr_text": None}
    async with running(api, token=TOKEN) as server:
        status, _, body = await raw(server)
    assert (status, body) == (200, b"")


@pytest.mark.asyncio
async def test_raw_json_format_returns_the_structured_result():
    api = FakeAPI()
    api.result = {"ocr_text": "hello", "word_data": []}
    async with running(api, token=TOKEN) as server:
        status, headers, body = await raw(server, "?format=json")
    assert status == 200 and headers["content-type"].startswith("application/json")
    assert json.loads(body)["ocr_text"] == "hello"


@pytest.mark.asyncio
async def test_raw_line_breaks_can_be_joined():
    api = FakeAPI()
    async with running(api, token=TOKEN) as server:
        await raw(server, "?preserve_line_breaks=false")
    assert api.calls[0][2]["ocr_preserve_line_breaks"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["?format=xml", "?preserve_line_breaks=maybe"])
async def test_raw_rejects_bad_query_values(query):
    async with running(FakeAPI(), token=TOKEN) as server:
        status, _, body = await raw(server, query)
    assert status == 400 and b"error" in body


@pytest.mark.asyncio
async def test_raw_rejects_an_empty_body():
    async with running(FakeAPI(), token=TOKEN) as server:
        status, _, _ = await raw(server, body=b"")
    assert status == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain",
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
        "application/octet-stream",
        "image/gif",
        "image/svg+xml",
        None,
    ],
)
async def test_raw_accepts_only_the_four_image_types(content_type):
    api = FakeAPI()
    async with running(api, token=TOKEN) as server:
        status, _, _ = await raw(server, content_type=content_type)
    assert status == 415 and api.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type",
    ["image/png", "image/jpeg", "image/webp", "image/bmp", "IMAGE/PNG; x=y"],
)
async def test_raw_accepts_png_jpeg_webp_and_bmp(content_type):
    async with running(FakeAPI(), token=TOKEN) as server:
        status, _, _ = await raw(server, content_type=content_type)
    assert status == 200


@pytest.mark.asyncio
async def test_json_routes_still_refuse_an_image_content_type():
    async with running(FakeAPI(), token=TOKEN) as server:
        status, _, _ = await request(
            server, "POST", "/v1/ocr", b"{}", "image/png", AUTH
        )
    assert status == 415


@pytest.mark.asyncio
async def test_raw_needs_the_token():
    api = FakeAPI()
    async with running(api, token=TOKEN) as server:
        no_token = await raw(server, headers={})
        wrong = await raw(server, headers={"Authorization": "Bearer nope"})
    assert no_token[0] == 401 and wrong[0] == 401 and api.calls == []


@pytest.mark.asyncio
async def test_a_web_page_cannot_reach_raw_even_with_a_valid_looking_request():
    """No Origin from our clients; a browser always sends one.

    A page cannot send image/png (or Authorization) without a preflight, and the
    Origin rule refuses both the preflight and the request itself.
    """
    api = FakeAPI()
    evil = {**AUTH, "Origin": "https://evil.example"}
    async with running(api, token=TOKEN) as server:
        post = await raw(server, headers=evil)
        preflight = await request(
            server,
            "OPTIONS",
            "/v1/ocr/raw",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type, authorization",
            },
        )
    assert post[0] == 403 and preflight[0] == 403
    assert "access-control-allow-origin" not in preflight[1]
    assert api.calls == []


@pytest.mark.asyncio
async def test_raw_errors_are_json_with_the_right_status():
    api = FakeAPI()
    async with running(api, token=TOKEN) as server:
        api.exc = LensImageError("not an image")
        bad = await raw(server)
        api.exc = LensRateLimitError("slow down", retry_after=7)
        limited = await raw(server)
    assert bad[0] == 400 and json.loads(bad[2])["error"] == "not an image"
    assert limited[0] == 429 and limited[1]["retry-after"] == "7"


# ---------------------------------------------------------------- managed routes


@pytest.mark.asyncio
async def test_managed_routes_do_not_exist_on_a_plain_server():
    async with running(FakeAPI(), token=TOKEN) as server:
        for method, path in (
            ("POST", "/v1/cli"),
            ("GET", "/v1/status"),
            ("POST", "/v1/shutdown"),
        ):
            status, _, _ = await request(
                server,
                method,
                path,
                b"{}" if method == "POST" else b"",
                "application/json" if method == "POST" else None,
                AUTH,
            )
            assert status == 404, path


def test_the_cli_route_refuses_to_exist_without_a_token_or_off_loopback():
    with pytest.raises(ValueError, match="token"):
        LensServer(FakeAPI(), port=0, cli_handler=cli_ok)
    with pytest.raises(ValueError):
        LensServer(FakeAPI(), host="0.0.0.0", token=TOKEN, cli_handler=cli_ok)


async def post_json(server, path, payload, headers=AUTH):
    status, h, body = await request(
        server, "POST", path, json.dumps(payload).encode(), "application/json", headers
    )
    return status, json.loads(body) if body else None


@pytest.mark.asyncio
async def test_cli_runs_the_handler_with_validated_arguments(tmp_path):
    seen = {}

    async def handler(**kwargs):
        seen.update(kwargs)
        return {"exit_code": 3, "stdout": "o", "stderr": "e"}

    async with running(FakeAPI(), token=TOKEN, cli_handler=handler) as server:
        status, reply = await post_json(
            server,
            "/v1/cli",
            {
                "argv": ["a.png", "-t", "ru"],
                "cwd": str(tmp_path),
                "env": {"LENS_TIMEOUT": "9", "PATH": "/x", "HTTPS_PROXY": "p"},
                "stdout_is_tty": True,
                "columns": 100,
            },
        )
    assert status == 200 and reply == {"exit_code": 3, "stdout": "o", "stderr": "e"}
    assert seen["argv"] == ["a.png", "-t", "ru"]
    assert seen["cwd"] == str(tmp_path)
    assert seen["env"] == {"LENS_TIMEOUT": "9"}  # filtered again on this side
    assert seen["stdout_is_tty"] is True and seen["stderr_is_tty"] is False
    assert seen["columns"] == 100


@pytest.mark.asyncio
async def test_cli_needs_the_token():
    called = []

    async def handler(**kwargs):
        called.append(kwargs)
        return {}

    async with running(FakeAPI(), token=TOKEN, cli_handler=handler) as server:
        body = {"argv": [], "cwd": os.getcwd()}
        assert (await post_json(server, "/v1/cli", body, {}))[0] == 401
        assert (
            await post_json(server, "/v1/cli", body, {"Authorization": "Bearer x"})
        )[0] == 401
    assert called == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"cwd": os.getcwd()},
        {"argv": "a.png", "cwd": os.getcwd()},
        {"argv": [1], "cwd": os.getcwd()},
        {"argv": ["a\0b"], "cwd": os.getcwd()},
        {"argv": ["x"] * 600, "cwd": os.getcwd()},
        {"argv": [], "cwd": "relative/dir"},
        {"argv": [], "cwd": 5},
        {"argv": [], "cwd": os.getcwd(), "env": {"LENS_X": 1}},
        {"argv": [], "cwd": os.getcwd(), "env": []},
        {"argv": [], "cwd": os.getcwd(), "columns": "wide"},
        {"argv": [], "cwd": os.getcwd(), "stdin_is_tty": "maybe"},
    ],
)
async def test_cli_rejects_malformed_requests(payload):
    async with running(FakeAPI(), token=TOKEN, cli_handler=cli_ok) as server:
        status, reply = await post_json(server, "/v1/cli", payload)
    assert status == 400 and "error" in reply


@pytest.mark.asyncio
async def test_cli_must_be_json():
    async with running(FakeAPI(), token=TOKEN, cli_handler=cli_ok) as server:
        status, _, _ = await request(
            server, "POST", "/v1/cli", b"{}", "text/plain", AUTH
        )
    assert status == 415


@pytest.mark.asyncio
async def test_cli_work_is_cancelled_when_the_client_hangs_up():
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def slow(**kwargs):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async with running(FakeAPI(), token=TOKEN, cli_handler=slow) as server:
        body = json.dumps({"argv": [], "cwd": os.getcwd()}).encode()
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        writer.write(
            (
                "POST /v1/cli HTTP/1.1\r\nHost: t\r\nContent-Type: application/json\r\n"
                f"Authorization: Bearer {TOKEN}\r\nContent-Length: {len(body)}\r\n\r\n"
            ).encode()
            + body
        )
        await writer.drain()
        await asyncio.wait_for(started.wait(), 5)
        writer.close()
        await asyncio.wait_for(cancelled.wait(), 5)


@pytest.mark.asyncio
async def test_concurrent_cli_requests_are_independent():
    async def handler(**kwargs):
        await asyncio.sleep(0.05 if kwargs["argv"] == ["slow"] else 0)
        return {"exit_code": 0, "stdout": kwargs["argv"][0], "stderr": ""}

    async with running(FakeAPI(), token=TOKEN, cli_handler=handler) as server:
        results = await asyncio.gather(
            post_json(server, "/v1/cli", {"argv": ["slow"], "cwd": os.getcwd()}),
            post_json(server, "/v1/cli", {"argv": ["fast"], "cwd": os.getcwd()}),
        )
    assert [r[1]["stdout"] for r in results] == ["slow", "fast"]


# ----------------------------------------------------------- status / shutdown


@pytest.mark.asyncio
async def test_status_counts_work_not_probes():
    api = FakeAPI()
    async with running(
        api, token=TOKEN, cli_handler=cli_ok, idle_timeout=100
    ) as server:
        await raw(server)
        await post_json(server, "/v1/cli", {"argv": [], "cwd": os.getcwd()})
        await request(server, "GET", "/health")
        status, _, body = await request(server, "GET", "/v1/status", headers=AUTH)
    info = json.loads(body)
    assert status == 200
    assert info["pid"] == os.getpid() and info["requests"] == 2
    assert info["idle_timeout"] == 100 and 0 < info["idle_remaining"] <= 100
    assert info["uptime"] >= 0


@pytest.mark.asyncio
async def test_status_and_shutdown_need_the_token():
    async with running(FakeAPI(), token=TOKEN, cli_handler=cli_ok) as server:
        assert (await request(server, "GET", "/v1/status"))[0] == 401
        assert (
            await request(server, "POST", "/v1/shutdown", b"{}", "application/json")
        )[0] == 401


@pytest.mark.asyncio
async def test_shutdown_stops_serve_forever_after_replying():
    server = LensServer(
        FakeAPI(), port=0, token=TOKEN, cli_handler=cli_ok, shutdown_grace=2
    )
    serving = asyncio.ensure_future(server.serve_forever(install_signal_handlers=False))
    for _ in range(100):
        if server._server is not None:
            break
        await asyncio.sleep(0.01)
    status, reply = await post_json(server, "/v1/shutdown", {})
    assert status == 200 and reply["ok"] is True
    await asyncio.wait_for(serving, 5)


# ------------------------------------------------------------------ idle timeout


async def serve_until_stopped(server: LensServer, limit: float = 5.0) -> float:
    started = time.monotonic()
    await asyncio.wait_for(server.serve_forever(install_signal_handlers=False), limit)
    return time.monotonic() - started


@pytest.mark.asyncio
async def test_an_idle_server_stops_itself():
    server = LensServer(FakeAPI(), port=0, idle_timeout=0.3, idle_check_interval=0.05)
    elapsed = await serve_until_stopped(server)
    assert 0.25 <= elapsed < 3


@pytest.mark.asyncio
async def test_work_postpones_the_idle_stop_but_probes_do_not():
    server = LensServer(
        FakeAPI(), port=0, token=TOKEN, idle_timeout=0.5, idle_check_interval=0.05
    )
    serving = asyncio.ensure_future(server.serve_forever(install_signal_handlers=False))
    for _ in range(100):
        if server._server is not None:
            break
        await asyncio.sleep(0.01)
    start = time.monotonic()
    for _ in range(3):  # real work every 0.3 s keeps it alive past 0.5 s
        await asyncio.sleep(0.3)
        assert (await raw(server))[0] == 200
    assert not serving.done()
    for _ in range(10):  # probes do not
        # A probe that lands while the server is closing may never be
        # answered: on Windows the proactor can accept the socket at the very
        # moment the listener closes and then drop it (a CPython race in
        # _start_serving). Real clients time out and fall back; so does this.
        try:
            await asyncio.wait_for(request(server, "GET", "/health"), 1)
        except (asyncio.TimeoutError, ConnectionError, OSError):
            pass
        await asyncio.sleep(0.1)
        if serving.done():
            break
    await asyncio.wait_for(serving, 5)
    assert time.monotonic() - start > 0.9


@pytest.mark.asyncio
async def test_a_request_in_flight_is_never_cut_off_by_the_idle_timer():
    api = FakeAPI()
    api.delay = 0.6
    server = LensServer(
        api, port=0, token=TOKEN, idle_timeout=0.2, idle_check_interval=0.05
    )
    serving = asyncio.ensure_future(server.serve_forever(install_signal_handlers=False))
    for _ in range(100):
        if server._server is not None:
            break
        await asyncio.sleep(0.01)
    status, _, _ = await raw(server)
    assert status == 200
    await asyncio.wait_for(serving, 5)


# -------------------------------------------------------------------- unix socket


@pytest.mark.skipif(not POSIX, reason="AF_UNIX sockets")
@pytest.mark.asyncio
async def test_unix_socket_transport_is_private_and_removed_on_stop(short_tmp):
    path = os.path.join(short_tmp, "d.sock")
    api = FakeAPI()
    api.result = {"ocr_text": "over unix"}
    server = LensServer(api, port=0, token=TOKEN, unix_path=path, cli_handler=cli_ok)
    await server.start()
    try:
        assert server.local_only
        assert os.stat(path).st_mode & 0o777 == 0o600
        status, _, body = await request(
            server,
            "POST",
            "/v1/ocr/raw",
            PNG,
            "image/png",
            AUTH,
            unix=True,
        )
        assert (status, body) == (200, b"over unix")
        assert (
            await request(server, "POST", "/v1/ocr/raw", PNG, "image/png", unix=True)
        )[0] == 401
    finally:
        await server.stop(grace=1)
    assert not os.path.exists(path)


def test_png_fixture_is_a_real_png():
    import io

    from PIL import Image

    assert Image.open(io.BytesIO(PNG)).size == (1, 1)
    assert png_b64()  # keep the shared helper imported and exercised
