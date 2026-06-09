"""QRZ.com XML-API client: login + lookup parsing with an injected fetch.

The live QRZ service (paid XML subscription) is NOT contacted here — every test
uses sample XML via an injected ``fetch``, so URL construction, namespaced XML
parsing, session caching, and the error/expiry paths are all exercised offline.
"""

from __future__ import annotations

from partyhams.app.state import AppState, load_state, save_state
from partyhams.qrz import (
    QrzClient,
    format_record,
    login_url,
    lookup_url,
    parse_login,
    parse_lookup,
)

# QRZ responses are namespaced; the sample XML mirrors the real service.
_NS = 'xmlns="http://xmldata.qrz.com"'

_LOGIN_OK = f"""<?xml version="1.0" ?>
<QRZDatabase version="1.34" {_NS}>
  <Session>
    <Key>abc123sessionkey</Key>
    <Count>123</Count>
    <SubExp>Wed Dec 31 2026</SubExp>
  </Session>
</QRZDatabase>"""

_LOGIN_BAD = f"""<?xml version="1.0" ?>
<QRZDatabase version="1.34" {_NS}>
  <Session>
    <Error>Username/password incorrect</Error>
  </Session>
</QRZDatabase>"""

_LOOKUP_OK = f"""<?xml version="1.0" ?>
<QRZDatabase version="1.34" {_NS}>
  <Callsign>
    <call>W1AW</call>
    <fname>Hiram Percy</fname>
    <name>Maxim</name>
    <addr2>Newington</addr2>
    <state>CT</state>
    <grid>FN31pr</grid>
    <country>United States</country>
  </Callsign>
  <Session>
    <Key>abc123sessionkey</Key>
  </Session>
</QRZDatabase>"""

_LOOKUP_EXPIRED = f"""<?xml version="1.0" ?>
<QRZDatabase version="1.34" {_NS}>
  <Session>
    <Error>Session Timeout</Error>
  </Session>
</QRZDatabase>"""

_LOOKUP_NOTFOUND = f"""<?xml version="1.0" ?>
<QRZDatabase version="1.34" {_NS}>
  <Session>
    <Error>Not found: ZZ9ZZZ</Error>
  </Session>
</QRZDatabase>"""


# --------------------------------------------------------------------------- #
# URL construction
# --------------------------------------------------------------------------- #
def test_login_url():
    url = login_url("w1aw", "secret pw")
    assert url.startswith("https://xmldata.qrz.com/xml/current/?")
    assert "username=w1aw" in url
    assert "password=secret%20pw" in url  # url-encoded
    assert "agent=partyhams" in url
    assert ";" in url  # QRZ uses semicolon-separated params


def test_lookup_url():
    url = lookup_url("KEY1", "w1aw")
    assert "s=KEY1" in url
    assert "callsign=W1AW" in url  # upper-cased


# --------------------------------------------------------------------------- #
# parse_login
# --------------------------------------------------------------------------- #
def test_parse_login_returns_key():
    assert parse_login(_LOGIN_OK) == "abc123sessionkey"


def test_parse_login_error_returns_none():
    assert parse_login(_LOGIN_BAD) is None


def test_parse_login_bad_xml_returns_none():
    assert parse_login("not xml <<<") is None


# --------------------------------------------------------------------------- #
# parse_lookup (namespaced)
# --------------------------------------------------------------------------- #
def test_parse_lookup_normalizes_record():
    record, expired = parse_lookup(_LOOKUP_OK)
    assert expired is False
    assert record == {
        "call": "W1AW",
        "first": "Hiram Percy",
        "name": "Maxim",
        "city": "Newington",
        "state": "CT",
        "grid": "FN31pr",
        "country": "United States",
    }


def test_parse_lookup_expired_flags_session():
    record, expired = parse_lookup(_LOOKUP_EXPIRED)
    assert record is None
    assert expired is True


def test_parse_lookup_not_found_is_not_expiry():
    record, expired = parse_lookup(_LOOKUP_NOTFOUND)
    assert record is None
    assert expired is False


def test_parse_lookup_bad_xml_returns_none():
    record, expired = parse_lookup("garbage")
    assert record is None and expired is False


# --------------------------------------------------------------------------- #
# QrzClient.login
# --------------------------------------------------------------------------- #
def test_client_login_caches_key():
    client = QrzClient("w1aw", "pw")
    key = client.login(fetch=lambda url: _LOGIN_OK)
    assert key == "abc123sessionkey"
    assert client.key == "abc123sessionkey"
    assert client.last_error is None


def test_client_login_bad_creds_returns_none():
    client = QrzClient("w1aw", "wrong")
    assert client.login(fetch=lambda url: _LOGIN_BAD) is None
    assert client.key is None
    assert client.last_error is not None


def test_client_login_without_credentials():
    client = QrzClient()
    assert client.login(fetch=lambda url: _LOGIN_OK) is None
    assert "credentials" in client.last_error.lower()


def test_client_login_network_error_returns_none():
    client = QrzClient("w1aw", "pw")

    def boom(url):
        raise OSError("no network")

    assert client.login(fetch=boom) is None
    assert client.key is None


# --------------------------------------------------------------------------- #
# QrzClient.lookup
# --------------------------------------------------------------------------- #
def test_client_lookup_logs_in_then_looks_up():
    client = QrzClient("w1aw", "pw")
    calls: list[str] = []

    def fetch(url):
        calls.append(url)
        return _LOGIN_OK if "username=" in url else _LOOKUP_OK

    record = client.lookup("w1aw", fetch=fetch)
    assert record is not None
    assert record["name"] == "Maxim"
    assert record["state"] == "CT"
    assert len(calls) == 2  # login, then lookup


def test_client_lookup_reuses_cached_key():
    client = QrzClient("w1aw", "pw")
    client.key = "cached"
    urls: list[str] = []

    def fetch(url):
        urls.append(url)
        return _LOOKUP_OK

    assert client.lookup("w1aw", fetch=fetch) is not None
    assert len(urls) == 1  # no login needed
    assert "s=cached" in urls[0]


def test_client_lookup_relogins_on_expiry():
    client = QrzClient("w1aw", "pw")
    client.key = "stale"
    seq = iter([_LOOKUP_EXPIRED, _LOGIN_OK, _LOOKUP_OK])

    def fetch(url):
        return next(seq)

    record = client.lookup("w1aw", fetch=fetch)
    assert record is not None
    assert record["call"] == "W1AW"
    assert client.key == "abc123sessionkey"  # refreshed


def test_client_lookup_not_found_returns_none():
    client = QrzClient("w1aw", "pw")
    client.key = "cached"
    assert client.lookup("ZZ9ZZZ", fetch=lambda url: _LOOKUP_NOTFOUND) is None
    assert "no data" in client.last_error.lower()


def test_client_lookup_empty_call_returns_none():
    client = QrzClient("w1aw", "pw")

    def fail(url):
        raise AssertionError("should not fetch for empty call")

    assert client.lookup("   ", fetch=fail) is None


def test_client_lookup_bad_login_aborts():
    client = QrzClient("w1aw", "wrong")
    assert client.lookup("w1aw", fetch=lambda url: _LOGIN_BAD) is None


# --------------------------------------------------------------------------- #
# format_record
# --------------------------------------------------------------------------- #
def test_format_record_summary():
    record = {
        "call": "W1AW",
        "first": "Hiram",
        "name": "Maxim",
        "city": "Newington",
        "state": "CT",
        "grid": "FN31pr",
    }
    text = format_record(record)
    assert text.startswith("W1AW — ")
    assert "Hiram Maxim" in text
    assert "Newington CT" in text


def test_format_record_minimal():
    assert format_record({"call": "K1ABC"}) == "K1ABC"


# --------------------------------------------------------------------------- #
# AppState round-trip of QRZ credentials
# --------------------------------------------------------------------------- #
def test_state_qrz_round_trip(tmp_path):
    path = tmp_path / "state.json"
    assert load_state(path).qrz_username == ""  # default
    assert load_state(path).qrz_password == ""
    save_state(AppState(qrz_username="W1AW", qrz_password="hunter2"), path)
    loaded = load_state(path)
    assert loaded.qrz_username == "W1AW"
    assert loaded.qrz_password == "hunter2"
