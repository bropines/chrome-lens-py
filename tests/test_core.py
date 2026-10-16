"""Offline tests for the transport, retry policy and session model."""

import asyncio
import warnings
from typing import Callable, List

import httpx
import pytest

from chrome_lens_py.core import request_handler as rh
from chrome_lens_py.core.request_handler import (
    LensRequestHandler,
    LensSession,
    accept_encoding,
    is_key_rejection,
    parse_retry_after,
    resolve_endpoints,
)
from chrome_lens_py.exceptions import (
    LensAPIError,
    LensAuthError,
    LensConfigError,
    LensConnectionError,
    LensRateLimitError,
    LensTimeoutError,
)
from chrome_lens_py.utils.lens_betterproto import LensOverlayServerResponse

OK_BODY = LensOverlayServerResponse().SerializeToString()


def make_handler(
    responder: Callable[[httpx.Request], httpx.Response], **kwargs
) -> LensRequestHandler:
    """A handler wired to an in-memory transport, with sleeping stubbed out."""
    kwargs.setdefault("api_key", "KEY")
    kwargs.setdefault("trust_env", False)
    kwargs.setdefault("proxy", {"all://": httpx.MockTransport(responder)})
    handler = LensRequestHandler(**kwargs)
    handler.sleeps = []  # type: ignore[attr-defined]

    async def fake_sleep(delay: float) -> None:
        handler.sleeps.append(delay)  # type: ignore[attr-defined]

    handler._sleep = fake_sleep
    handler._random = lambda: 1.0  # no jitter reduction: delay == nominal
    return handler


# ------------------------------------------------------------------ headers


def test_accept_encoding_omits_brotli_without_a_decoder(monkeypatch):
    monkeypatch.setattr(rh, "_has_brotli", lambda: False)
    assert "br" not in accept_encoding().split(", ")
    monkeypatch.setattr(rh, "_has_brotli", lambda: True)
    assert accept_encoding().split(", ")[-1] == "br"


@pytest.mark.asyncio
async def test_request_headers_carry_the_current_key_and_negotiated_encoding(
    monkeypatch,
):
    monkeypatch.setattr(rh, "_has_brotli", lambda: False)
    seen = {}

    def responder(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, content=OK_BODY)

    handler = make_handler(responder, api_key="abc")
    await handler.post_raw(b"x")
    assert seen["x-goog-api-key"] == "abc"
    assert seen["accept-encoding"] == "gzip, deflate"
    await handler.aclose()


# ---------------------------------------------------------------- endpoints


def test_resolve_endpoints_precedence(monkeypatch):
    monkeypatch.delenv("LENS_ENDPOINT", raising=False)
    assert resolve_endpoints() == (
        "https://lensfrontend-pa.googleapis.com/v1/crupload",
    )
    monkeypatch.setenv("LENS_ENDPOINT", "https://a.example/x, https://b.example/y")
    assert resolve_endpoints() == ("https://a.example/x", "https://b.example/y")
    # An explicit argument beats the environment.
    assert resolve_endpoints("https://c.example/z") == ("https://c.example/z",)
    assert resolve_endpoints(["https://c.example/z", "https://c.example/z"]) == (
        "https://c.example/z",
    )


@pytest.mark.parametrize("bad", ["lens.example", "ftp://x/y", "https://", ""])
def test_resolve_endpoints_rejects_garbage(bad):
    with pytest.raises(LensConfigError):
        resolve_endpoints([bad])


def test_empty_key_list_is_a_config_error():
    with pytest.raises(LensConfigError):
        LensRequestHandler(api_key=[""])


# -------------------------------------------------------------- retry-after


def test_parse_retry_after_forms():
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after("0.5") == 0.5
    assert parse_retry_after(None) is None
    assert parse_retry_after("soon") is None
    # A date in the past means "now", never a negative sleep.
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
    assert parse_retry_after("-5") == 0.0


def test_is_key_rejection():
    assert is_key_rejection(401, "")
    assert is_key_rejection(400, "API key not valid. Please pass a valid API key.")
    assert is_key_rejection(403, '{"reason": "API_KEY_HTTP_REFERRER_BLOCKED"}')
    assert not is_key_rejection(403, "region not supported")
    assert not is_key_rejection(400, "malformed protobuf")
    assert not is_key_rejection(500, "api key")


# -------------------------------------------------------------------- retry


@pytest.mark.asyncio
async def test_retries_5xx_with_exponential_backoff_then_succeeds():
    calls: List[int] = []

    def responder(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=OK_BODY)

    handler = make_handler(responder, max_retries=3, backoff_base=1.0)
    response = await handler.post_raw(b"x")
    assert response.status_code == 200
    assert handler.sleeps == [1.0, 2.0]
    await handler.aclose()


@pytest.mark.asyncio
async def test_backoff_is_capped_and_jittered():
    handler = make_handler(lambda r: httpx.Response(200), backoff_base=1, backoff_max=5)
    handler._random = lambda: 0.0
    assert handler._backoff(0) == 0.5  # lower edge of the jitter band
    handler._random = lambda: 1.0
    assert handler._backoff(10) == 5.0  # capped
    await handler.aclose()


@pytest.mark.asyncio
async def test_retry_after_replaces_the_computed_delay():
    calls: List[int] = []

    def responder(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, content=OK_BODY)

    handler = make_handler(responder, max_retries=2, backoff_base=1.0)
    await handler.post_raw(b"x")
    assert len(handler.sleeps) == 1
    assert 7.0 <= handler.sleeps[0] <= 7.71  # Retry-After plus up to 10% spread
    await handler.aclose()


@pytest.mark.asyncio
async def test_exhausted_429_raises_rate_limit_error_with_retry_after():
    handler = make_handler(
        lambda r: httpx.Response(429, headers={"Retry-After": "2"}),
        max_retries=1,
    )
    with pytest.raises(LensRateLimitError) as info:
        await handler.send_interaction(b"x", LensSession())
    assert info.value.retry_after == 2.0
    assert info.value.status_code == 429
    assert isinstance(info.value, LensAPIError)
    assert len(handler.sleeps) == 1
    await handler.aclose()


@pytest.mark.asyncio
async def test_retry_after_longer_than_the_deadline_fails_fast_without_sleeping():
    handler = make_handler(
        lambda r: httpx.Response(429, headers={"Retry-After": "3600"}),
        max_retries=5,
        deadline=30,
    )
    with pytest.raises(LensRateLimitError) as info:
        await handler.send_interaction(b"x", LensSession())
    assert info.value.retry_after == 3600.0
    assert handler.sleeps == []
    await handler.aclose()


@pytest.mark.asyncio
async def test_503_without_retry_after_is_a_plain_api_error():
    handler = make_handler(lambda r: httpx.Response(503), max_retries=0)
    with pytest.raises(LensAPIError) as info:
        await handler.send_interaction(b"x", LensSession())
    assert not isinstance(info.value, LensRateLimitError)
    assert info.value.status_code == 503
    await handler.aclose()


@pytest.mark.asyncio
async def test_non_retryable_status_is_not_retried():
    calls: List[int] = []

    def responder(request):
        calls.append(1)
        return httpx.Response(404)

    handler = make_handler(responder, max_retries=3)
    with pytest.raises(LensAPIError) as info:
        await handler.send_interaction(b"x", LensSession())
    assert info.value.status_code == 404
    assert len(calls) == 1
    await handler.aclose()


# -------------------------------------------------- failure classification


@pytest.mark.asyncio
async def test_connect_failure_becomes_lens_connection_error():
    def responder(request):
        raise httpx.ConnectError("refused")

    handler = make_handler(responder, max_retries=1)
    with pytest.raises(LensConnectionError, match="refused"):
        await handler.post_raw(b"x")
    assert len(handler.sleeps) == 1
    await handler.aclose()


@pytest.mark.asyncio
async def test_read_timeout_becomes_lens_timeout_error_with_a_message():
    def responder(request):
        raise httpx.ReadTimeout("")

    handler = make_handler(responder, max_retries=0)
    with pytest.raises(LensTimeoutError, match="Timed out"):
        await handler.post_raw(b"x")
    await handler.aclose()


@pytest.mark.asyncio
async def test_env_proxy_hint_is_kept_on_connect_errors(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:2080")

    def responder(request):
        raise httpx.ConnectError("refused")

    handler = LensRequestHandler(api_key="k", max_retries=0, trust_env=True)
    handler._client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    with pytest.raises(LensConnectionError, match="--no-env-proxy"):
        await handler.post_raw(b"x")
    await handler.aclose()


@pytest.mark.asyncio
async def test_a_stalled_server_cannot_outlive_the_deadline():
    async def hang(request):
        await asyncio.sleep(30)
        return httpx.Response(200)

    handler = make_handler(hang, max_retries=3, deadline=0.3, timeout=60)
    started = asyncio.get_running_loop().time()
    with pytest.raises(LensTimeoutError, match="deadline"):
        await handler.post_raw(b"x")
    assert asyncio.get_running_loop().time() - started < 5
    await handler.aclose()


# --------------------------------------------------------------- key fallback


@pytest.mark.asyncio
async def test_rejected_key_falls_back_and_the_working_one_is_remembered():
    seen: List[str] = []

    def responder(request):
        key = request.headers["x-goog-api-key"]
        seen.append(key)
        if key == "bad":
            return httpx.Response(400, text="API key not valid.")
        return httpx.Response(200, content=OK_BODY)

    handler = make_handler(responder, api_key=["bad", "good"])
    await handler.post_raw(b"x")
    await handler.post_raw(b"x")
    # The second request goes straight to the key that worked.
    assert seen == ["bad", "good", "good"]
    assert handler.api_key == "good"
    await handler.aclose()


@pytest.mark.asyncio
async def test_key_fallback_does_not_spend_the_retry_budget():
    def responder(request):
        if request.headers["x-goog-api-key"] != "c":
            return httpx.Response(403, text='{"reason":"API_KEY_INVALID"}')
        return httpx.Response(200, content=OK_BODY)

    handler = make_handler(responder, api_key=["a", "b", "c"], max_retries=0)
    assert (await handler.post_raw(b"x")).status_code == 200
    await handler.aclose()


@pytest.mark.asyncio
async def test_all_keys_rejected_raises_auth_error():
    handler = make_handler(lambda r: httpx.Response(401), api_key=["a", "b"])
    with pytest.raises(LensAuthError):
        await handler.send_interaction(b"x", LensSession())
    await handler.aclose()


@pytest.mark.asyncio
async def test_unrelated_403_does_not_burn_through_keys():
    seen: List[str] = []

    def responder(request):
        seen.append(request.headers["x-goog-api-key"])
        return httpx.Response(403, text="region not supported")

    handler = make_handler(responder, api_key=["a", "b"])
    with pytest.raises(LensAPIError) as info:
        await handler.send_interaction(b"x", LensSession())
    assert not isinstance(info.value, LensAuthError)
    assert seen == ["a"]
    await handler.aclose()


# ---------------------------------------------------------- endpoint fallback


@pytest.mark.asyncio
async def test_connection_failure_moves_to_the_next_endpoint_and_sticks():
    hosts: List[str] = []

    def responder(request):
        hosts.append(request.url.host)
        if request.url.host == "primary.example":
            raise httpx.ConnectError("down")
        return httpx.Response(200, content=OK_BODY)

    handler = make_handler(
        responder,
        endpoints=["https://primary.example/c", "https://backup.example/c"],
        max_retries=0,
    )
    await handler.post_raw(b"x")
    await handler.post_raw(b"x")
    assert hosts == ["primary.example", "backup.example", "backup.example"]
    assert handler.endpoint == "https://backup.example/c"
    await handler.aclose()


@pytest.mark.asyncio
async def test_http_errors_do_not_trigger_endpoint_fallback():
    hosts: List[str] = []

    def responder(request):
        hosts.append(request.url.host)
        return httpx.Response(404)

    handler = make_handler(
        responder,
        endpoints=["https://a.example/c", "https://b.example/c"],
        max_retries=0,
    )
    await handler.post_raw(b"x")
    assert hosts == ["a.example"]
    await handler.aclose()


@pytest.mark.asyncio
async def test_gsessionid_is_appended_per_endpoint():
    urls: List[str] = []

    def responder(request):
        urls.append(str(request.url))
        return httpx.Response(200, content=OK_BODY)

    handler = make_handler(responder, endpoints="https://a.example/c?x=1")
    session = LensSession()
    session.cluster_info = rh.LensOverlayClusterInfo(server_session_id="SID")
    await handler.post_raw(b"x", session=session)
    assert urls == ["https://a.example/c?x=1&gsessionid=SID"]
    await handler.aclose()


# ------------------------------------------------------------- proxy handling


@pytest.mark.asyncio
async def test_explicit_proxy_is_never_bypassed(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")

    def responder(request):
        raise httpx.ConnectError("proxy down")

    handler = make_handler(responder, max_retries=0, direct_fallback=True)
    assert handler._can_fall_back_to_direct() is False
    with pytest.raises(LensConnectionError):
        await handler.post_raw(b"x")
    await handler.aclose()


async def _serve_ok():
    """A tiny HTTP/1.1 server that answers every request with an empty 200."""

    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.mark.asyncio
async def test_unreachable_env_proxy_falls_back_direct_when_enabled(monkeypatch):
    for var in ("NO_PROXY", "no_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")  # nothing listens there
    server, port = await _serve_ok()
    try:
        handler = LensRequestHandler(
            api_key="k",
            endpoints=f"http://127.0.0.1:{port}/crupload",
            max_retries=0,
            direct_fallback=True,
        )
        response = await handler.post_raw(b"x")
        assert response.status_code == 200
        assert handler._prefer_direct is True
        await handler.aclose()
    finally:
        server.close()


@pytest.mark.asyncio
async def test_unreachable_env_proxy_fails_loudly_by_default(monkeypatch):
    for var in ("NO_PROXY", "no_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    server, port = await _serve_ok()
    try:
        handler = LensRequestHandler(
            api_key="k",
            endpoints=f"http://127.0.0.1:{port}/crupload",
            max_retries=0,
        )
        with pytest.raises(LensConnectionError, match="--no-env-proxy"):
            await handler.post_raw(b"x")
        await handler.aclose()
    finally:
        server.close()


# ------------------------------------------------------------------ sessions


def test_start_new_session_is_deprecated():
    handler = LensRequestHandler(api_key="k", trust_env=False)
    with pytest.warns(DeprecationWarning):
        session = handler.start_new_session()
    assert handler.default_session is session


@pytest.mark.asyncio
async def test_new_image_payloads_advance_the_image_sequence():
    session = LensSession()
    assert (await session.next_ids(True))[1:] == (1, 1)
    assert (await session.next_ids(True))[1:] == (2, 2)
    assert (await session.next_ids(False))[1:] == (3, 2)


@pytest.mark.asyncio
async def test_no_warning_noise_from_normal_use():
    handler = make_handler(lambda r: httpx.Response(200, content=OK_BODY))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        handler.new_session()
        await handler.post_raw(b"x")
    await handler.aclose()


# =============================================================== image encoding

import io  # noqa: E402

from PIL import Image  # noqa: E402

from chrome_lens_py import api as api_module  # noqa: E402
from chrome_lens_py.api import LensAPI  # noqa: E402
from chrome_lens_py.core import image_processor as ip  # noqa: E402
from chrome_lens_py.core.image_processor import (  # noqa: E402
    MIME_JPEG,
    MIME_WEBP,
    encode_image_for_api,
    has_meaningful_alpha,
    prepare_image_for_api,
)
from chrome_lens_py.core.protobuf_builder import (  # noqa: E402
    create_ocr_translate_request,
    create_region_request,
)
from chrome_lens_py.exceptions import LensImageError  # noqa: E402
from chrome_lens_py.utils.lens_betterproto import (  # noqa: E402
    LensOverlayServerRequest,
    TranslationDataStatusCode,
)


def _text_on_transparent(color):
    img = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (10, 10), color), (5, 5))
    return img


def test_opaque_images_stay_jpeg():
    for img in (
        Image.new("RGB", (30, 30), "red"),
        Image.new("RGBA", (30, 30), (255, 0, 0, 255)),  # alpha channel, but solid
        Image.new("L", (30, 30), 90),
    ):
        encoded = encode_image_for_api(img)
        assert encoded.mime_type == MIME_JPEG
        assert encoded.data[:2] == b"\xff\xd8"


def test_images_with_real_transparency_are_uploaded_as_webp():
    encoded = encode_image_for_api(_text_on_transparent((0, 0, 0, 255)))
    assert encoded.mime_type == MIME_WEBP
    assert encoded.data[:4] == b"RIFF" and encoded.data[8:12] == b"WEBP"
    decoded = Image.open(io.BytesIO(encoded.data))
    assert decoded.mode == "RGBA"  # alpha survived the trip
    assert decoded.getchannel("A").getextrema()[0] == 0


def test_palette_transparency_counts_as_alpha():
    img = Image.new("P", (10, 10))
    img.info["transparency"] = 0
    assert has_meaningful_alpha(img)
    assert not has_meaningful_alpha(Image.new("P", (10, 10)))


def test_flatten_and_contrast_modes_keep_text_visible():
    dark = _text_on_transparent((0, 0, 0, 255))
    light = _text_on_transparent((255, 255, 255, 255))
    for mode in ("flatten", "contrast"):
        assert encode_image_for_api(dark, alpha_mode=mode).mime_type == MIME_JPEG

    def background_pixel(img, mode):
        encoded = encode_image_for_api(img, alpha_mode=mode)
        return Image.open(io.BytesIO(encoded.data)).getpixel((35, 15))[0]

    assert background_pixel(dark, "flatten") > 200  # white
    assert background_pixel(dark, "contrast") > 200  # dark text -> white
    assert background_pixel(light, "flatten") > 200  # white text lost: the old bug
    assert background_pixel(light, "contrast") < 50  # light text -> black


@pytest.mark.asyncio
async def test_prepare_image_for_api_keeps_its_jpeg_contract():
    data, width, height, original = await prepare_image_for_api(
        _text_on_transparent((0, 0, 0, 255)), keep_original=True
    )
    assert data[:2] == b"\xff\xd8" and (width, height) == (40, 20)
    assert original is not None and original.mode == "RGBA"


@pytest.mark.asyncio
async def test_encoding_runs_off_the_event_loop_thread(monkeypatch):
    import threading

    seen = []
    real = ip.encode_image_for_api

    def spy(*args, **kwargs):
        seen.append(threading.current_thread())
        return real(*args, **kwargs)

    monkeypatch.setattr(ip, "encode_image_for_api", spy)
    await ip.prepare_image(Image.new("RGB", (10, 10)))
    assert seen and seen[0] is not threading.main_thread()


# ============================================================ request building


def test_request_id_carries_time_usec_and_mime_type_only_for_webp():
    import time

    before = int(time.time() * 1_000_000)
    payload, _ = create_ocr_translate_request(b"img", 10, 10, "en")
    plain = LensOverlayServerRequest.FromString(payload).objects_request.request_context
    assert before <= plain.request_id.time_usec <= int(time.time() * 1_000_000)
    assert plain.request_id.mime_type == ""

    payload, _ = create_ocr_translate_request(
        b"img", 10, 10, "en", mime_type="image/webp"
    )
    webp = LensOverlayServerRequest.FromString(payload).objects_request.request_context
    assert webp.request_id.mime_type == "image/webp"


def test_region_request_is_stamped_too():
    payload = create_region_request(
        b"crop", (0.5, 0.5, 0.2, 0.2), 100, 100, 20, "en", 7, 2, 1
    )
    request = LensOverlayServerRequest.FromString(payload)
    assert request.interaction_request.request_context.request_id.time_usec > 0


# ===================================================================== LensAPI


def _translated_response() -> bytes:
    response = LensOverlayServerResponse()
    gleam = response.objects_response.deep_gleams.add()
    gleam.translation.translation = "hola"
    gleam.translation.status.code = TranslationDataStatusCode.SUCCESS
    response.objects_response.text.content_language = "en"
    return response.SerializeToString()


def _api_with(responder, **kwargs) -> LensAPI:
    return LensAPI(
        proxy={"all://": httpx.MockTransport(responder)},
        trust_env=False,
        max_retries=0,
        **kwargs,
    )


@pytest.fixture
def fake_render(monkeypatch):
    calls = []

    def render(original, objects_response, **kwargs):
        calls.append(kwargs)
        return Image.new("RGBA", (original.width, original.height), (1, 2, 3, 255))

    monkeypatch.setattr(api_module, "render_translation_overlay", render)
    monkeypatch.setattr(LensAPI, "_get_font_path", lambda self: None)
    return calls


@pytest.mark.asyncio
async def test_overlay_save_failure_raises_instead_of_claiming_success(
    tmp_path, fake_render
):
    api = _api_with(lambda r: httpx.Response(200, content=_translated_response()))
    target = str(tmp_path / "missing_dir" / "out.png")
    with pytest.raises(LensImageError, match="missing_dir"):
        await api.process_image(
            Image.new("RGB", (20, 20)),
            target_translation_language="es",
            output_overlay_path=target,
        )
    await api.aclose()


@pytest.mark.asyncio
async def test_overlay_is_saved_and_returned(tmp_path, fake_render):
    api = _api_with(lambda r: httpx.Response(200, content=_translated_response()))
    out = tmp_path / "out.png"
    result = await api.process_image(
        Image.new("RGB", (20, 20)),
        target_translation_language="es",
        output_overlay_path=str(out),
        return_overlay=True,
        overlay_format="webp",
    )
    assert result["overlay_path"] == str(out) and out.exists()
    assert result["overlay_mime_type"] == "image/webp"
    assert result["overlay_image"][8:12] == b"WEBP"
    await api.aclose()


@pytest.mark.asyncio
async def test_no_overlay_without_translated_text(tmp_path, fake_render):
    api = _api_with(lambda r: httpx.Response(200, content=OK_BODY))
    out = tmp_path / "out.png"
    result = await api.process_image(
        Image.new("RGB", (20, 20)), output_overlay_path=str(out)
    )
    assert result["overlay_path"] is None and not out.exists()
    assert fake_render == []
    await api.aclose()


@pytest.mark.asyncio
async def test_legacy_overlay_mode_is_deprecated(tmp_path, fake_render):
    api = _api_with(lambda r: httpx.Response(200, content=_translated_response()))
    with pytest.warns(DeprecationWarning, match="legacy"):
        await api.process_image(
            Image.new("RGB", (20, 20)),
            target_translation_language="es",
            output_overlay_path=str(tmp_path / "o.png"),
            overlay_mode="legacy",
        )
    await api.aclose()


@pytest.mark.asyncio
async def test_shared_session_advances_image_sequence_for_every_image():
    seen = []

    def responder(request):
        parsed = LensOverlayServerRequest.FromString(request.content)
        ids = parsed.objects_request.request_context.request_id
        seen.append((ids.uuid, ids.sequence_id, ids.image_sequence_id))
        return httpx.Response(200, content=OK_BODY)

    api = _api_with(responder)
    for _ in range(3):
        await api.process_image(Image.new("RGB", (10, 10)), new_session=False)
    assert [s[1:] for s in seen] == [(1, 1), (2, 2), (3, 3)]
    assert len({s[0] for s in seen}) == 1  # one conversation, one uuid
    await api.aclose()


def _peak_tracking_responder():
    state = {"in_flight": 0, "peak": 0}

    async def responder(request):
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        await asyncio.sleep(0.05)
        state["in_flight"] -= 1
        return httpx.Response(200, content=OK_BODY)

    return responder, state


@pytest.mark.asyncio
async def test_concurrent_calls_on_a_shared_session_do_not_interleave():
    responder, state = _peak_tracking_responder()
    api = _api_with(responder)
    await asyncio.gather(
        *(
            api.process_image(Image.new("RGB", (10, 10)), new_session=False)
            for _ in range(4)
        )
    )
    assert state["peak"] == 1
    await api.aclose()


@pytest.mark.asyncio
async def test_private_sessions_still_run_in_parallel():
    responder, state = _peak_tracking_responder()
    api = _api_with(responder)
    await asyncio.gather(
        *(api.process_image(Image.new("RGB", (10, 10))) for _ in range(4))
    )
    assert state["peak"] > 1
    await api.aclose()


@pytest.mark.asyncio
async def test_process_region_encodes_the_full_image_only_once(monkeypatch):
    encodes = []
    real = api_module.encode_image_for_api

    def counting(*args, **kwargs):
        encodes.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(api_module, "encode_image_for_api", counting)
    api = _api_with(lambda r: httpx.Response(200, content=OK_BODY))
    result = await api.process_region(
        Image.new("RGB", (100, 100)), (0.5, 0.5, 0.4, 0.4)
    )
    assert result["crop_size"] == (40, 40)
    assert len(encodes) == 1  # the crop goes through crop_region, not this
    await api.aclose()


@pytest.mark.asyncio
async def test_call_raw_endpoint_is_deprecated_and_raises_lens_errors():
    api = _api_with(lambda r: httpx.Response(404, text="nope"))
    with pytest.warns(DeprecationWarning):
        with pytest.raises(LensAPIError) as info:
            await api.call_raw_endpoint(b"\x00")
    assert info.value.status_code == 404
    await api.aclose()


@pytest.mark.asyncio
async def test_call_raw_endpoint_follows_up_with_gsessionid():
    urls = []
    first = LensOverlayServerResponse()
    first.objects_response.cluster_info.server_session_id = "SID"

    def responder(request):
        urls.append(str(request.url))
        return httpx.Response(200, content=first.SerializeToString())

    api = _api_with(responder, endpoints="https://lens.example/crupload")
    with pytest.warns(DeprecationWarning):
        await api.call_raw_endpoint(b"a", new_session=True)
        await api.call_raw_endpoint(b"b")
    assert urls == [
        "https://lens.example/crupload",
        "https://lens.example/crupload?gsessionid=SID",
    ]
    await api.aclose()


def test_api_accepts_resilience_kwargs():
    api = LensAPI(
        api_key=["a", "b"],
        max_retries=5,
        backoff_base=0.1,
        backoff_max=2,
        deadline=9,
        endpoints=["https://x.example/y"],
        direct_fallback=True,
        trust_env=False,
    )
    handler = api.request_handler
    assert handler.api_keys == ["a", "b"] and handler.max_retries == 5
    assert (handler.backoff_base, handler.backoff_max, handler.deadline) == (0.1, 2, 9)
    assert handler.endpoints == ("https://x.example/y",) and handler.direct_fallback
    with pytest.raises(ValueError):
        LensAPI(alpha_mode="bogus")


@pytest.mark.asyncio
async def test_results_report_the_original_image_size():
    api = _api_with(lambda r: httpx.Response(200, content=OK_BODY))
    result = await api.process_image(Image.new("RGB", (2400, 1300)))
    assert result["image_size"] == [2400, 1300]  # not the downscaled upload size
    region = await api.process_region(Image.new("RGB", (100, 80)), (0.5, 0.5, 0.4, 0.4))
    assert region["image_size"] == [100, 80]
    await api.aclose()
