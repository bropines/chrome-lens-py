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
