"""QRZ.com XML-API client for looking up callsign station information.

QRZ's lookup service is session-based. First you log in:

    GET https://xmldata.qrz.com/xml/current/?username=USER;password=PASS;agent=...

which returns XML carrying either a ``<Key>`` session key or an ``<Error>``.
Then each lookup reuses that key:

    GET https://xmldata.qrz.com/xml/current/?s=KEY;callsign=W1AW

returning a ``<Callsign>`` element with ``fname``, ``name``, ``addr2`` (city),
``state``, ``grid``, ``country``, etc. Session keys expire, so :class:`QrzClient`
caches the key and transparently re-logs-in once when a lookup reports an invalid
session.

The XML is namespaced (``xmlns="http://xmldata.qrz.com"``); we strip the
namespace when matching tags so callers don't have to care about it.

The HTTP fetch is injectable (the ``fetch`` parameter) so login/lookup parsing
and the error paths are unit-testable without touching the network. ``login`` and
``lookup`` never raise on a network/parse failure — they return ``None``.

NOTE: the *live* QRZ service needs a paid XML subscription plus credentials and
is unverified in this build/test environment; only URL construction, XML parsing,
and error handling are exercised by the unit tests (via an injected ``fetch``).
"""

from __future__ import annotations

import socket
import ssl
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from urllib.error import URLError
from urllib.request import urlopen

# A fetch takes a URL and returns the raw response body as text.
Fetch = Callable[[str], str]

BASE_URL = "https://xmldata.qrz.com/xml/current/"
AGENT = "partyhams"
_TIMEOUT_S = 6.0


def _default_fetch(url: str) -> str:
    """Fetch ``url`` over HTTPS using only the standard library (no new deps)."""
    with urlopen(url, timeout=_TIMEOUT_S) as resp:  # noqa: S310 - fixed https QRZ host
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset)


def _transport_error_detail(err: BaseException) -> str:
    """Classify a fetch failure into a short, actionable reason for the status bar.

    ``urlopen`` wraps the underlying cause in ``URLError.reason``, so we inspect
    both the raised error and that reason. A failed TLS handshake (commonly an
    untrusted CA bundle in a packaged/freshly-installed app) is the usual cause
    of a "login fails despite correct credentials" report, so it gets its own
    message instead of being lumped under the generic "network".
    """
    candidates = [err, getattr(err, "reason", None)]
    if any(isinstance(c, ssl.SSLCertVerificationError) for c in candidates):
        return "TLS certificate not trusted"
    if any(isinstance(c, ssl.SSLError) for c in candidates):
        return "TLS error"
    if any(isinstance(c, (TimeoutError, socket.timeout)) for c in candidates):
        return "timed out"
    return "network"


def login_url(username: str, password: str) -> str:
    """Build the QRZ session-login URL. QRZ uses ``;``-separated parameters."""
    parts = {"username": username, "password": password, "agent": AGENT}
    return BASE_URL + "?" + ";".join(f"{k}={urllib.parse.quote(v)}" for k, v in parts.items())


def lookup_url(key: str, call: str) -> str:
    """Build the QRZ callsign-lookup URL for an active session ``key``."""
    parts = {"s": key, "callsign": call.strip().upper()}
    return BASE_URL + "?" + ";".join(f"{k}={urllib.parse.quote(v)}" for k, v in parts.items())


def _localname(tag: str) -> str:
    """Strip an ``{namespace}`` prefix from an ElementTree tag name."""
    return tag.rsplit("}", 1)[-1]


def _find(parent: ET.Element, name: str) -> ET.Element | None:
    """Find a direct child by local (namespace-stripped) tag name."""
    for child in parent:
        if _localname(child.tag) == name:
            return child
    return None


def _section(root: ET.Element, name: str) -> ET.Element | None:
    """Return the ``<Session>`` or ``<Callsign>`` sub-element (namespace-agnostic)."""
    if _localname(root.tag) == name:
        return root
    return _find(root, name)


def _text(parent: ET.Element | None, name: str) -> str:
    """Text of the named child, stripped; ``""`` if absent or empty."""
    if parent is None:
        return ""
    child = _find(parent, name)
    return (child.text or "").strip() if child is not None else ""


def parse_login(xml_text: str) -> str | None:
    """Parse a login response, returning the session key or ``None`` on error."""
    try:
        root = ET.fromstring(xml_text)  # noqa: S314 - trusted QRZ XML, no entities used
    except ET.ParseError:
        return None
    session = _section(root, "Session")
    if session is None:
        return None
    if _text(session, "Error"):
        return None
    return _text(session, "Key") or None


def parse_lookup(xml_text: str) -> tuple[dict | None, bool]:
    """Parse a lookup response into ``(record_or_None, session_expired)``.

    ``session_expired`` is ``True`` when QRZ reports an invalid/expired session,
    signalling the caller to re-login and retry once.
    """
    try:
        root = ET.fromstring(xml_text)  # noqa: S314 - trusted QRZ XML, no entities used
    except ET.ParseError:
        return None, False
    session = _section(root, "Session")
    error = _text(session, "Error") if session is not None else ""
    if error:
        # QRZ phrases expiry as "Session Timeout" / "Invalid session key".
        expired = "session" in error.lower() and (
            "timeout" in error.lower() or "invalid" in error.lower()
        )
        return None, expired
    call = _section(root, "Callsign")
    if call is None:
        return None, False
    record = {
        "call": _text(call, "call").upper(),
        "first": _text(call, "fname"),
        "name": _text(call, "name"),
        "city": _text(call, "addr2"),
        "state": _text(call, "state"),
        "grid": _text(call, "grid"),
        "country": _text(call, "country"),
    }
    if not record["call"]:
        return None, False
    return record, False


class QrzClient:
    """Session-caching QRZ.com lookup client.

    Construct with credentials; the session key is fetched lazily on the first
    lookup and refreshed automatically if it expires. All network calls degrade
    to ``None`` rather than raising, so a lookup never disrupts logging.
    """

    def __init__(self, username: str = "", password: str = "") -> None:
        self.username = username
        self.password = password
        self.key: str | None = None
        #: Short human-readable reason for the last failure (for the status bar).
        self.last_error: str | None = None

    def login(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        fetch: Fetch | None = None,
    ) -> str | None:
        """Log in and cache a session key, returning it (or ``None`` on failure)."""
        if username is not None:
            self.username = username
        if password is not None:
            self.password = password
        if not self.username or not self.password:
            self.last_error = "QRZ credentials not set"
            return None
        fetch = fetch or _default_fetch
        try:
            body = fetch(login_url(self.username, self.password))
        except (URLError, OSError) as err:
            self.last_error = f"QRZ login failed ({_transport_error_detail(err)})"
            return None
        except Exception:  # noqa: BLE001 - any injected/transport error degrades
            self.last_error = "QRZ login failed"
            return None
        key = parse_login(body)
        if key is None:
            self.last_error = "QRZ login rejected (check username/password)"
            self.key = None
            return None
        self.last_error = None
        self.key = key
        return key

    def lookup(self, call: str, *, fetch: Fetch | None = None) -> dict | None:
        """Look up ``call``, returning a normalized record or ``None``.

        Logs in on demand and retries once if the cached session has expired.
        """
        call = call.strip().upper()
        if not call:
            self.last_error = "No callsign to look up"
            return None
        fetch = fetch or _default_fetch
        if self.key is None and self.login(fetch=fetch) is None:
            return None
        record = self._do_lookup(call, fetch)
        if record is not None or self.key is not None:
            return record
        # Session expired: re-login once and retry.
        if self.login(fetch=fetch) is None:
            return None
        return self._do_lookup(call, fetch)

    def _do_lookup(self, call: str, fetch: Fetch) -> dict | None:
        """One lookup attempt; clears ``self.key`` if the session expired."""
        assert self.key is not None
        try:
            body = fetch(lookup_url(self.key, call))
        except (URLError, OSError) as err:
            self.last_error = f"QRZ lookup failed ({_transport_error_detail(err)})"
            return None
        except Exception:  # noqa: BLE001 - any injected/transport error degrades
            self.last_error = "QRZ lookup failed"
            return None
        record, expired = parse_lookup(body)
        if record is not None:
            self.last_error = None
            return record
        if expired:
            self.key = None  # force a re-login on the caller's retry
        else:
            self.last_error = f"QRZ: no data for {call}"
        return None


def format_record(record: dict) -> str:
    """One-line summary for the status bar: ``W1AW — Hiram Maxim, Newington CT``."""
    name = " ".join(p for p in (record.get("first"), record.get("name")) if p)
    locale = f"{record.get('city', '')} {record.get('state', '')}".strip()
    grid = record.get("grid", "")
    tail = ", ".join(p for p in (name, locale, grid) if p)
    call = record.get("call", "")
    return f"{call} — {tail}" if tail else call
