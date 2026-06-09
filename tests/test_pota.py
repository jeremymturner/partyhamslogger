"""POTA activity + park-verification API.

The live POTA API is NOT contacted here: ``verify_park`` is exercised purely with
an injected ``fetch`` (the live call is unverified in this environment).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from factories import FREQ, make_qso

from partyhams.contest import get
from partyhams.contest.base import ContestConfig
from partyhams.contest.pota import is_valid_park
from partyhams.contest.pota_api import park_url, verify_park
from partyhams.core.models import QSO, Mode


@pytest.fixture
def pota():
    return get("pota")


def _qso(call, *, freq_hz=FREQ["20m"], mode=Mode.CW, day=27, park=""):
    q = make_qso(call, freq_hz=freq_hz, mode=mode, exchange={"park": park} if park else {})
    q.timestamp = datetime(2026, 6, day, 18, 0, 0, tzinfo=UTC)
    return q


# --------------------------------------------------------------------------- #
# registry + definition
# --------------------------------------------------------------------------- #
def test_registered():
    from partyhams.contest import available

    contest = get("pota")
    assert contest.id == "pota"
    assert contest.name == "Parks on the Air"
    assert ("pota", "Parks on the Air") in available()


def test_park_validation():
    assert is_valid_park("US-1234")
    assert is_valid_park("K-0001")
    assert is_valid_park("us-1234")  # lower-case accepted
    assert is_valid_park("VE-50000")  # 5-digit suffix
    assert not is_valid_park("US1234")  # missing hyphen
    assert not is_valid_park("US-12")  # too few digits
    assert not is_valid_park("TOOLONG-1234")  # >4 prefix chars
    assert not is_valid_park("")


def test_allowed_bands_include_hf_warc_and_vhf(pota):
    bands = pota.allowed_bands()
    assert {"160m", "20m", "10m", "6m", "2m"} <= bands
    assert "30m" in bands and "17m" in bands  # WARC allowed for POTA
    assert "70cm" not in bands


def test_optional_exchange_park(pota):
    fields = pota.exchange_fields()
    assert [f.name for f in fields] == ["park"]
    assert fields[0].required is False
    # parse_exchange tolerates an empty (no-P2P) exchange because park is optional.
    assert pota.parse_exchange("") == {}
    assert pota.parse_exchange("US-5678") == {"park": "US-5678"}


# --------------------------------------------------------------------------- #
# dupes — workable again on different band, mode, or day
# --------------------------------------------------------------------------- #
def test_dupe_same_band_mode_day(pota):
    a = _qso("W1AW", day=27)
    b = _qso("W1AW", day=27)
    assert pota.dupe_key(a) == pota.dupe_key(b)


def test_workable_on_different_band(pota):
    a = _qso("W1AW", freq_hz=FREQ["20m"], day=27)
    b = _qso("W1AW", freq_hz=FREQ["40m"], day=27)
    assert pota.dupe_key(a) != pota.dupe_key(b)


def test_workable_on_different_mode_group(pota):
    a = _qso("W1AW", mode=Mode.CW, day=27)
    b = _qso("W1AW", mode=Mode.USB, day=27)
    assert pota.dupe_key(a) != pota.dupe_key(b)


def test_workable_on_different_day(pota):
    a = _qso("W1AW", day=27)
    b = _qso("W1AW", day=28)
    assert pota.dupe_key(a) != pota.dupe_key(b)


# --------------------------------------------------------------------------- #
# scoring — plain QSO count
# --------------------------------------------------------------------------- #
def test_score_is_qso_count(pota):
    qsos = [
        _qso("W1AW", freq_hz=FREQ["20m"], day=27),
        _qso("W1AW", freq_hz=FREQ["40m"], day=27),  # different band: counts
        _qso("K9XYZ", day=28),
    ]
    summary = pota.score(qsos, ContestConfig(my_call="N0CALL"))
    assert summary.qso_count == 3
    assert summary.total == 3


def test_score_dedupes(pota):
    qsos = [_qso("W1AW", day=27), _qso("W1AW", day=27)]  # same slot: one counts
    summary = pota.score(qsos, ContestConfig(my_call="N0CALL"))
    assert summary.qso_count == 1
    assert summary.total == 1


def test_qso_points_are_one(pota):
    assert pota.qso_points(_qso("W1AW")) == 1


def test_park_to_park_tracked_as_mult(pota):
    p2p = _qso("W1AW", park="US-5678")
    assert ("park", "US-5678") in pota.multipliers(p2p)
    assert pota.multipliers(_qso("W1AW")) == set()


def test_cabrillo_line(pota):
    qso = QSO(
        uuid="u1", station_id="s1", operator="OP", call="w1aw",
        timestamp=datetime(2026, 6, 27, 18, 30, tzinfo=UTC),
        freq_hz=14_040_000, mode=Mode.CW, rst_sent="599", rst_rcvd="599",
        exchange_rcvd={"park": "US-5678"},
    )
    config = ContestConfig(my_call="N0CALL", extra={"park": "US-1234"})
    line = pota.cabrillo_qso_line(qso, config)
    assert line.startswith("QSO:")
    assert "N0CALL" in line and "W1AW" in line
    assert "US-1234" in line and "US-5678" in line


# --------------------------------------------------------------------------- #
# park verification — injected fetch, NO network
# --------------------------------------------------------------------------- #
def test_park_url():
    assert park_url("us-1234") == "https://api.pota.app/park/US-1234"


def test_verify_park_parses_name():
    sample = json.dumps(
        {"reference": "US-1234", "name": "Yellowstone NP", "locationDesc": "US-WY"}
    )

    def fake_fetch(url):
        assert url == "https://api.pota.app/park/US-1234"
        return sample

    info = verify_park("US-1234", fetch=fake_fetch)
    assert info is not None
    assert info["name"] == "Yellowstone NP"
    assert info["location"] == "US-WY"
    assert info["reference"] == "US-1234"


def test_verify_park_offline_returns_none():
    def boom(url):
        raise OSError("no network")

    assert verify_park("US-1234", fetch=boom) is None


def test_verify_park_bad_json_returns_none():
    assert verify_park("US-1234", fetch=lambda url: "not json{") is None


def test_verify_park_missing_name_returns_none():
    assert verify_park("US-1234", fetch=lambda url: json.dumps({"reference": "US-1234"})) is None


def test_verify_park_empty_ref_returns_none():
    # No fetch should even be attempted for an empty ref.
    def fail(url):
        raise AssertionError("fetch should not be called for empty ref")

    assert verify_park("", fetch=fail) is None
