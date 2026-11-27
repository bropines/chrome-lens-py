# src/chrome_lens_py/core/identity.py
"""Signed-in Lens requests, the way desktop Chrome sends them.

Chrome's Identity Delegation mode (``kLensComposeboxIdentityDelegation``) signs
a Lens request with the user's google.com cookie session instead of an OAuth
token. Three things differ from an anonymous request:

* the host: ``lensfrontend-pa.clients6.google.com`` instead of
  ``lensfrontend-pa.googleapis.com``, same paths, same API key;
* the headers: ``Cookie``, ``Origin: https://www.google.com``,
  ``X-Goog-AuthUser`` and ``Authorization: SAPISIDHASH <ts>_<sha1>_e``;
* clients6 refuses a request without ``X-Goog-Encode-Response-If-Executable:
  base64`` ("400 Request unsafe for trusted domain"), so it is sent, and the
  reply comes back as base64 text to decode before parsing - checked live;
* the hash: SHA-1 of ``"<email> <ts> <SAPISID> <origin>"``, which binds the
  account's e-mail into it, unlike the web's ``"<ts> <SAPISID> <origin>"``.
  The trailing ``_e`` marks that variant.

When Google refuses a signed request (401/403) Chrome retries it anonymously
(``RetriedWithoutAuthOn401``), and so does the transport here.

The cookies are credentials for the whole Google account. Nothing in this
module logs them, the SAPISID or the e-mail, and ``GoogleIdentity``'s repr
leaves them out.
"""

import base64
import binascii
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union
from urllib.parse import urlsplit, urlunsplit

from ..exceptions import LensConfigError

logger = logging.getLogger(__name__)

ORIGIN = "https://www.google.com"
ANONYMOUS_HOST = "lensfrontend-pa.googleapis.com"
SIGNED_HOST = "lensfrontend-pa.clients6.google.com"
# Where Chrome itself learns which accounts a cookie jar belongs to.
LIST_ACCOUNTS_URL = (
    "https://accounts.google.com/ListAccounts"
    "?gpsia=1&source=ChromiumBrowser&json=standard"
)
# What Google answers a signed request it will not honour with.
REFUSAL_STATUS_CODES = frozenset({401, 403})

CookieSource = Union[str, os.PathLike, Mapping[str, str]]


def sapisid_hash(
    email: str, sapisid: str, origin: str = ORIGIN, now: Optional[int] = None
) -> str:
    """The ``Authorization`` value for one signed request."""
    ts = int(time.time()) if now is None else int(now)
    digest = hashlib.sha1(f"{email} {ts} {sapisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}_e"


# The cookie the hash is over. A jar from an embedded browser's sign-in can
# lack the plain one; Google sets the partitioned twins to the same value.
SAPISID_NAMES = ("SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID")


def sapisid_of(jar: Mapping[str, str]) -> Optional[str]:
    return next((jar[name] for name in SAPISID_NAMES if jar.get(name)), None)


def _google_domain(domain: str) -> bool:
    """Cookies a browser would send to clients6.google.com."""
    domain = domain.strip().lstrip(".").lower()
    return domain == "google.com" or domain.endswith(".google.com")


def _from_netscape(lines: Iterable[str]) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for line in lines:
        # curl and the export extensions mark HttpOnly cookies this way.
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif line.startswith("#") or not line.strip():
            continue
        parts = line.rstrip("\r\n").split("\t")
        if len(parts) == 7 and _google_domain(parts[0]) and parts[5]:
            cookies[parts[5]] = parts[6]
    return cookies


def _from_json(data: Any) -> Dict[str, str]:
    # Cookie-Editor / EditThisCookie export: a list of {name, value, domain}.
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    cookies: Dict[str, str] = {}
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        if _google_domain(str(item.get("domain", "google.com"))):
            cookies[str(item["name"])] = str(item.get("value", ""))
    return cookies


def _from_header(text: str) -> Dict[str, str]:
    text = text.strip()
    if text.lower().startswith("cookie:"):
        text = text[len("cookie:") :]
    cookies: Dict[str, str] = {}
    for pair in text.split(";"):
        name, sep, value = pair.strip().partition("=")
        if sep and name:
            cookies[name.strip()] = value.strip()
    return cookies


def parse_cookies(text: str) -> Dict[str, str]:
    """Cookies from a Netscape cookies.txt, a JSON export or a Cookie header."""
    stripped = text.lstrip()
    if stripped.startswith(("[", "{")):
        try:
            return _from_json(json.loads(stripped))
        except ValueError:
            pass
    lines = text.splitlines()
    if any(line.count("\t") == 6 for line in lines):
        return _from_netscape(lines)
    return _from_header(text)


def is_cookie_file(value: str) -> bool:
    """A cookies setting names a file unless it reads like a Cookie header."""
    return "=" not in value and "\n" not in value


@dataclass
class GoogleIdentity:
    """A google.com cookie session to sign Lens requests with.

    ``cookies`` is a mapping, a Cookie header string, or the path to a file
    holding either a Netscape cookies.txt, a JSON export or a header line. A
    file is re-read when it changes, so a long-running daemon picks up
    refreshed cookies without a restart.

    ``email`` is the account's address, which the hash includes. Left empty, it
    is asked of ``accounts.google.com/ListAccounts`` with the same cookies on
    first use, as Chrome does.
    """

    cookies: CookieSource
    email: Optional[str] = None
    auth_user: int = 0
    origin: str = ORIGIN
    _jar: Dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _path: Optional[str] = field(default=None, init=False, repr=False)
    _mtime: Optional[float] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        source = self.cookies
        if isinstance(source, Mapping):
            self._jar = {str(k): str(v) for k, v in source.items() if k}
        elif isinstance(source, os.PathLike) or (
            isinstance(source, str) and is_cookie_file(source.strip())
        ):
            self._path = os.path.expanduser(os.fspath(source).strip())
            self._reload(force=True)
        elif isinstance(source, str):
            self._jar = parse_cookies(source)
        else:
            raise LensConfigError(
                "Google cookies must be a mapping, a string or a path."
            )
        if self.auth_user < 0:
            raise LensConfigError("google_auth_user must be >= 0.")
        if not sapisid_of(self._jar):
            raise LensConfigError(
                "The Google cookies have no SAPISID, which signing needs. Export "
                "the cookies of google.com while signed in."
            )

    def __repr__(self) -> str:  # the dataclass one would print the cookies
        where = "file" if self._path else "inline"
        return f"GoogleIdentity(cookies=<{where}, {len(self._jar)} cookies>, auth_user={self.auth_user})"

    def _reload(self, force: bool = False) -> None:
        assert self._path is not None
        try:
            mtime = os.path.getmtime(self._path)
            if not force and mtime == self._mtime:
                return
            with open(self._path, encoding="utf-8-sig") as handle:
                jar = parse_cookies(handle.read())
        except OSError as e:
            if force:
                raise LensConfigError(
                    f"Cannot read the Google cookies file {self._path!r}: {e.strerror}"
                ) from e
            logger.warning(
                "Cannot re-read the Google cookies file; keeping the old ones."
            )
            return
        if not force and not sapisid_of(jar):
            logger.warning(
                "The Google cookies file lost its SAPISID; keeping the old one."
            )
            return
        self._jar, self._mtime = jar, mtime

    @property
    def jar(self) -> Dict[str, str]:
        if self._path is not None:
            self._reload()
        return dict(self._jar)

    def cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.jar.items() if k and v)

    def headers(self, email: str, now: Optional[int] = None) -> Dict[str, str]:
        """Cookie, Origin, X-Goog-AuthUser and Authorization for one request."""
        jar = self.jar
        return {
            "Cookie": "; ".join(f"{k}={v}" for k, v in jar.items() if k and v),
            "Origin": self.origin,
            "X-Goog-AuthUser": str(self.auth_user),
            "X-Goog-Encode-Response-If-Executable": "base64",
            "Authorization": sapisid_hash(
                email, sapisid_of(jar) or "", self.origin, now
            ),
        }


def decode_body(body: bytes) -> bytes:
    """A clients6 reply as raw bytes.

    Asked for base64, clients6 sends the protobuf as base64 text. An error page
    may come unwrapped, so anything that is not strict base64 is kept as is.
    """
    text = b"".join(body.split())
    if not text:
        return body
    # Either alphabet: map the URL-safe one onto the standard before checking.
    try:
        return base64.b64decode(text.translate(_URLSAFE), validate=True)
    except (binascii.Error, ValueError):
        return body


_URLSAFE = bytes.maketrans(b"-_", b"+/")


def signed_url(url: str) -> Optional[str]:
    """``url`` on the signed host, or None when it is not Google's Lens host.

    A mirror set through LENS_ENDPOINT is never signed for: the cookies are
    the whole Google account and go to Google only.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != ANONYMOUS_HOST:
        return None
    return urlunsplit(parts._replace(netloc=SIGNED_HOST))


def email_from_list_accounts(body: str) -> Optional[str]:
    """The first signed-in account's address in a ListAccounts reply.

    The reply is ``["gaia.l.a.r", [["gaia.l.a", 1, "Name", "a@b", ...], ...]]``.
    It is searched rather than indexed, so a shifted field does not break it.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return None

    def first(node: Any) -> Optional[str]:
        if isinstance(node, str):
            return node if "@" in node and " " not in node else None
        if isinstance(node, list):
            for item in node:
                found = first(item)
                if found:
                    return found
        return None

    accounts = data[1] if isinstance(data, list) and len(data) > 1 else data
    return first(accounts)


def resolve_identity(
    cookies: Optional[Union[CookieSource, "GoogleIdentity"]],
    email: Optional[str] = None,
    auth_user: int = 0,
) -> Optional[GoogleIdentity]:
    if cookies is None or isinstance(cookies, GoogleIdentity):
        return cookies
    if isinstance(cookies, str) and not cookies.strip():
        return None
    return GoogleIdentity(
        cookies, email=(email or "").strip() or None, auth_user=auth_user
    )


__all__: Tuple[str, ...] = (
    "ANONYMOUS_HOST",
    "GoogleIdentity",
    "LIST_ACCOUNTS_URL",
    "ORIGIN",
    "REFUSAL_STATUS_CODES",
    "SIGNED_HOST",
    "decode_body",
    "is_cookie_file",
    "email_from_list_accounts",
    "parse_cookies",
    "resolve_identity",
    "sapisid_hash",
    "signed_url",
)
