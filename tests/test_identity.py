"""Signed-in requests (core/identity.py) and how the transport uses them."""

import base64
import os
from typing import Dict, List

import httpx
import pytest

from chrome_lens_py.api import LensAPI
from chrome_lens_py.core import identity
from chrome_lens_py.core import search as lens_search
from chrome_lens_py.core.request_handler import LensRequestHandler, LensSession
from chrome_lens_py.exceptions import LensConfigError, LensIdentityRejected
from chrome_lens_py.utils.lens_betterproto import LensOverlayServerResponse
from chrome_lens_py.utils.protobufs.lens_overlay_server_pb2 import (
    LensOverlayServerClusterInfoResponse,
)

COOKIES = {"SID": "sid-value", "SAPISID": "AbCdEf/123", "HSID": "h"}
ANON = "https://lensfrontend-pa.googleapis.com/v1/crupload"
SIGNED = "https://lensfrontend-pa.clients6.google.com/v1/crupload"
ACCOUNTS = '["gaia.l.a.r",[["gaia.l.a",1,"Jo Doe","jo@example.org","https://x",1,1,0]]]'


# ------------------------------------------------------------------ the hash


def test_the_hash_matches_the_known_vector():
    # Checked independently with hashlib by the lens-kmp port.
    assert identity.sapisid_hash(
        "user@example.com", "AbCdEf/123", "https://www.google.com", 1700000000
    ) == ("SAPISIDHASH 1700000000_63f76c6071122477af7276366dbbfc60e05b8200_e")


def test_the_headers_are_the_ones_chrome_sends():
    headers = identity.GoogleIdentity(COOKIES, auth_user=1).headers(
        "user@example.com", now=1700000000
    )
    assert headers["Origin"] == "https://www.google.com"
    assert headers["X-Goog-AuthUser"] == "1"
    # Without it clients6 answers 400 "Request unsafe for trusted domain".
    assert headers["X-Goog-Encode-Response-If-Executable"] == "base64"
    assert headers["Authorization"].endswith("_e")
    assert "SAPISID=AbCdEf/123" in headers["Cookie"].split("; ")


# ------------------------------------------------------------------ cookies


def test_cookies_are_read_from_a_header_line():
    jar = identity.parse_cookies("Cookie: SID=a; SAPISID=b=c ;  junk")
    assert jar == {"SID": "a", "SAPISID": "b=c"}


def test_cookies_are_read_from_a_netscape_file_keeping_only_google_com():
    text = "\n".join(
        [
            "# Netscape HTTP Cookie File",
            ".google.com\tTRUE\t/\tTRUE\t0\tSAPISID\tsap",
            "#HttpOnly_.google.com\tTRUE\t/\tTRUE\t0\tSID\tsid",
            "accounts.google.com\tFALSE\t/\tTRUE\t0\tLSID\tlsid",
            ".google.co.uk\tTRUE\t/\tTRUE\t0\tNID\tnope",
            ".notgoogle.com\tTRUE\t/\tTRUE\t0\tX\tnope",
        ]
    )
    assert identity.parse_cookies(text) == {
        "SAPISID": "sap",
        "SID": "sid",
        "LSID": "lsid",
    }


def test_cookies_are_read_from_a_json_export():
    text = (
        '[{"name":"SAPISID","value":"sap","domain":".google.com"},'
        '{"name":"NID","value":"no","domain":".youtube.com"}]'
    )
    assert identity.parse_cookies(text) == {"SAPISID": "sap"}


def test_a_partitioned_twin_stands_in_for_a_missing_sapisid():
    # Embedded-browser sign-ins can lack the plain cookie (seen in lens-kmp).
    for name in ("__Secure-3PAPISID", "__Secure-1PAPISID"):
        ident = identity.GoogleIdentity({"SID": "x", name: "AbCdEf/123"})
        headers = ident.headers("user@example.com", now=1700000000)
        assert headers["Authorization"] == (
            "SAPISIDHASH 1700000000_63f76c6071122477af7276366dbbfc60e05b8200_e"
        )


def test_signing_needs_a_sapisid():
    with pytest.raises(LensConfigError, match="SAPISID"):
        identity.GoogleIdentity({"SID": "x"})


def test_the_repr_shows_no_secret():
    text = repr(identity.GoogleIdentity(COOKIES, email="jo@example.com"))
    for secret in ("AbCdEf", "sid-value", "jo@example.com"):
        assert secret not in text


def test_a_cookie_file_is_re_read_when_it_changes(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text("SAPISID=one; SID=s", encoding="utf-8")
    ident = identity.GoogleIdentity(str(path))
    assert ident.jar["SAPISID"] == "one"

    path.write_text("SAPISID=two; SID=s", encoding="utf-8")
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))
    assert ident.jar["SAPISID"] == "two"


def test_a_missing_cookie_file_is_a_config_error(tmp_path):
    with pytest.raises(LensConfigError, match="cookies file"):
        identity.GoogleIdentity(str(tmp_path / "absent.txt"))


# ------------------------------------------------------------------ helpers


def test_only_googles_own_host_is_ever_signed_for():
    assert identity.signed_url(ANON + "?gsessionid=x") == SIGNED + "?gsessionid=x"
    # A LENS_ENDPOINT mirror would otherwise receive the whole account.
    assert identity.signed_url("https://mirror.example/v1/crupload") is None
    assert (
        identity.signed_url("http://lensfrontend-pa.googleapis.com/v1/crupload") is None
    )


def test_a_base64_reply_is_unwrapped_and_anything_else_kept():
    raw = bytes(range(256))
    assert identity.decode_body(base64.b64encode(raw) + b"\r\n") == raw
    assert identity.decode_body(base64.urlsafe_b64encode(raw)) == raw
    assert identity.decode_body(b"<html>Error 400</html>") == b"<html>Error 400</html>"


def test_a_page_names_the_account_but_not_googles_own_addresses():
    page = (
        '<a href="mailto:support@google.com">help</a> noreply@accounts.google.com '
        'user@example.com <div data-email="jo\\u0040example.org">Jo</div>'
    )
    assert identity.email_from_page(page) == "jo@example.org"
    assert identity.email_from_page("<html>no one here</html>") is None


def test_the_email_is_the_first_account_listed():
    assert identity.email_from_list_accounts(ACCOUNTS) == "jo@example.org"
    assert identity.email_from_list_accounts('["gaia.l.a.r",[]]') is None
    assert identity.email_from_list_accounts("not json") is None


# ---------------------------------------------------------------- transport


class Recorder:
    """An in-memory Google: records requests, answers by host."""

    def __init__(
        self,
        signed_status: int = 200,
        accounts_status: int = 200,
        accounts_body: str = ACCOUNTS,
        widget_status: int = 200,
    ):
        self.requests: List[httpx.Request] = []
        self.signed_status = signed_status
        self.accounts_status = accounts_status
        self.accounts_body = accounts_body
        self.widget_status = widget_status
        self.body = b"\x08\x01payload"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "accounts.google.com":
            return httpx.Response(self.accounts_status, text=self.accounts_body)
        if request.url.host == "ogs.google.com":
            return httpx.Response(
                self.widget_status,
                text="<div>Google Account</div><div>jo@example.org</div>",
            )
        if request.url.host == identity.SIGNED_HOST:
            if self.signed_status != 200:
                return httpx.Response(self.signed_status, text="denied")
            return httpx.Response(200, content=base64.b64encode(self.body))
        return httpx.Response(200, content=self.body)

    def hosts(self) -> List[str]:
        return [r.url.host for r in self.requests]


def handler_for(recorder: Recorder, **kwargs) -> LensRequestHandler:
    kwargs.setdefault(
        "identity", identity.GoogleIdentity(COOKIES, email="jo@example.com")
    )
    return LensRequestHandler(
        api_key="KEY",
        trust_env=False,
        max_retries=0,
        proxy={"all://": httpx.MockTransport(recorder)},
        **kwargs,
    )


def signed_headers(request: httpx.Request) -> Dict[str, str]:
    return {k: request.headers.get(k, "") for k in ("cookie", "authorization")}


@pytest.mark.asyncio
async def test_a_signed_request_goes_to_clients6_and_its_reply_is_decoded():
    google = Recorder()
    handler = handler_for(google)
    session = LensSession()
    body = await handler.exchange(b"x", session)

    assert body == google.body
    request = google.requests[0]
    assert request.url.host == identity.SIGNED_HOST
    assert request.headers["x-goog-api-key"] == "KEY"
    assert request.headers["authorization"].startswith("SAPISIDHASH ")
    assert session.signed is True and handler.signed_in
    await handler.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_first_request_goes_again_anonymously(status):
    google = Recorder(signed_status=status)
    handler = handler_for(google)
    session = LensSession()
    assert await handler.exchange(b"x", session) == google.body

    assert google.hosts() == [identity.SIGNED_HOST, identity.ANONYMOUS_HOST]
    assert signed_headers(google.requests[1]) == {"cookie": "", "authorization": ""}
    assert session.signed is False
    assert not handler.signed_in and handler.identity_refused == f"HTTP {status}"

    # ...and the handler stays anonymous rather than asking again each time.
    await handler.exchange(b"y", LensSession())
    assert google.hosts()[-1] == identity.ANONYMOUS_HOST
    assert len(google.requests) == 3
    await handler.aclose()


@pytest.mark.asyncio
async def test_a_signed_session_refused_later_must_start_over():
    google = Recorder()
    handler = handler_for(google)
    session = LensSession()
    await handler.exchange(b"x", session)

    google.signed_status = 401
    with pytest.raises(LensIdentityRejected):
        await handler.exchange(b"y", session)
    # Its ids belong to clients6; it is reset rather than sent elsewhere.
    assert session.signed is None and session.cluster_info is None
    assert google.hosts() == [identity.SIGNED_HOST, identity.SIGNED_HOST]

    # A fresh session then runs anonymously.
    await handler.exchange(b"z", session)
    assert google.hosts()[-1] == identity.ANONYMOUS_HOST
    await handler.aclose()


@pytest.mark.asyncio
async def test_the_email_is_looked_up_once_when_not_given():
    google = Recorder()
    handler = handler_for(google, identity=identity.GoogleIdentity(COOKIES))
    await handler.exchange(b"x", LensSession())
    await handler.exchange(b"y", LensSession())

    assert google.hosts() == [
        "accounts.google.com",
        identity.SIGNED_HOST,
        identity.SIGNED_HOST,
    ]
    lookup = google.requests[0]
    assert "SAPISID=AbCdEf/123" in lookup.headers["cookie"]
    # The hash is over the looked-up address.
    ts = google.requests[1].headers["authorization"].split()[1].split("_")[0]
    expected = identity.sapisid_hash("jo@example.org", "AbCdEf/123", now=int(ts))
    assert google.requests[1].headers["authorization"] == expected
    await handler.aclose()


@pytest.mark.asyncio
async def test_a_google_com_only_jar_is_named_by_the_account_widget():
    # ListAccounts answers 200 with no address without accounts.google.com's
    # own cookies (seen live in lens-kmp).
    google = Recorder(accounts_body='["gaia.l.a.r",[]]')
    handler = handler_for(google, identity=identity.GoogleIdentity(COOKIES))
    await handler.exchange(b"x", LensSession())
    assert google.hosts() == [
        "accounts.google.com",
        "ogs.google.com",
        identity.SIGNED_HOST,
    ]
    assert google.requests[1].headers["origin"] == "https://www.google.com"
    await handler.aclose()


@pytest.mark.asyncio
async def test_without_an_email_requests_go_anonymously():
    google = Recorder(accounts_status=401, widget_status=401)
    handler = handler_for(google, identity=identity.GoogleIdentity(COOKIES))
    await handler.exchange(b"x", LensSession())
    assert google.hosts() == [
        "accounts.google.com",
        "ogs.google.com",
        identity.ANONYMOUS_HOST,
    ]
    assert "google_email" in (handler.identity_refused or "")
    await handler.aclose()


@pytest.mark.asyncio
async def test_a_mirror_never_sees_the_cookies():
    google = Recorder()
    handler = handler_for(google, endpoints="https://mirror.example/v1/crupload")
    await handler.exchange(b"x", LensSession())
    assert google.hosts() == ["mirror.example"]
    assert signed_headers(google.requests[0]) == {"cookie": "", "authorization": ""}
    await handler.aclose()


@pytest.mark.asyncio
async def test_without_cookies_nothing_changes():
    google = Recorder()
    handler = handler_for(google, identity=None)
    await handler.exchange(b"x", LensSession())
    assert google.hosts() == [identity.ANONYMOUS_HOST]
    assert not handler.signed_in
    await handler.aclose()


# ------------------------------------------------------------------- search


class SearchGoogle(Recorder):
    """gsessionid, then uploads and interactions, refusing on cue."""

    def __init__(self, refuse_upload: bool):
        super().__init__()
        self.refuse_upload = refuse_upload

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        signed = request.url.host == identity.SIGNED_HOST
        if request.url.path.endswith("/gsessionid"):
            reply = LensOverlayServerClusterInfoResponse()
            reply.server_session_id = "SRV-signed" if signed else "SRV-anon"
            reply.search_session_id = "SRCH-signed" if signed else "SRCH-anon"
            body = reply.SerializeToString()
        else:
            if signed and self.refuse_upload:
                return httpx.Response(403, text="denied")
            body = bytes(LensOverlayServerResponse().SerializeToString())
        return httpx.Response(200, content=base64.b64encode(body) if signed else body)


@pytest.mark.asyncio
async def test_a_search_refused_at_the_upload_starts_over_anonymously():
    google = SearchGoogle(refuse_upload=True)
    handler = handler_for(google)
    search = lens_search.ImageSearch(
        handler, lens_search.UploadedImage(b"JPEG", 800, 600)
    )
    url = await search.search()

    assert google.hosts() == [
        identity.SIGNED_HOST,  # gsessionid, signed
        identity.SIGNED_HOST,  # upload, refused
        identity.ANONYMOUS_HOST,  # gsessionid again
        identity.ANONYMOUS_HOST,  # upload
        identity.ANONYMOUS_HOST,  # interaction
    ]
    # The anonymous session's ids, never the signed one's on the other host.
    assert "gsessionid=SRCH-anon" in url
    assert google.requests[3].url.params["gsessionid"] == "SRV-anon"
    assert not search.signed_in
    await handler.aclose()


@pytest.mark.asyncio
async def test_a_signed_search_stays_on_clients6():
    google = SearchGoogle(refuse_upload=False)
    handler = handler_for(google)
    search = lens_search.ImageSearch(
        handler, lens_search.UploadedImage(b"JPEG", 800, 600)
    )
    url = await search.search()
    assert set(google.hosts()) == {identity.SIGNED_HOST}
    assert "gsessionid=SRCH-signed" in url
    assert search.signed_in
    await handler.aclose()


# ---------------------------------------------------------------------- API


def test_the_api_takes_cookies_and_reports_being_signed_in():
    api = LensAPI(google_cookies=COOKIES, google_email="jo@example.com")
    assert api.signed_in
    assert not LensAPI().signed_in
    assert not LensAPI(google_cookies="  ").signed_in
