"""ADIF and Cabrillo export."""

from __future__ import annotations

from datetime import datetime

from partyhams.app.session import build_session
from partyhams.core.models import Mode
from partyhams.export import adif_to_mode, park_adif_name, timestamped_adif_name

FREQ_20M = 14_040_000


def test_timestamped_adif_name():
    when = datetime(2026, 6, 7, 14, 30, 12)
    assert timestamped_adif_name("W7ABC", "arrl-field-day", when) == (
        "W7ABC-arrl-field-day-20260607-143012.adi"
    )
    # Slashes/odd characters in the call are sanitised; empty call falls back.
    assert timestamped_adif_name("VK3/AB1C", "cqww", when).startswith("VK3_AB1C-cqww-")
    assert timestamped_adif_name("", "x", when).startswith("log-x-")


def test_park_adif_name():
    when = datetime(2026, 6, 24, 9, 0, 0)
    # @ supported: CALL@PARK_YYYYMMDD.adif, park keeps its dash.
    assert park_adif_name("W7ABC", "US-1234", when) == "W7ABC@US-1234_20260624.adif"
    # @ unsupported: underscore separator instead.
    assert park_adif_name("W7ABC", "US-1234", when, at_sign=False) == "W7ABC_US-1234_20260624.adif"
    # No park: drop the park segment entirely.
    assert park_adif_name("W7ABC", "", when) == "W7ABC_20260624.adif"
    # Odd characters in the call are sanitised; empty call falls back to "log".
    assert park_adif_name("VK3/AB1C", "VK-0001", when) == "VK3_AB1C@VK-0001_20260624.adif"
    assert park_adif_name("", "", when) == "log_20260624.adif"


async def make_logged_session():
    s = build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        sent_exchange={"class": "1E", "section": "OR"},
        power="low_150w",
        network=None,
    )
    await s.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "2A", "section": "EPA"}
    )
    await s.log_qso(
        call="W2XYZ", freq_hz=FREQ_20M, mode=Mode.USB, exchange={"class": "3A", "section": "STX"}
    )
    return s


async def test_adif_mine_only_filters_to_this_station():
    from dataclasses import replace

    s = await make_logged_session()  # two QSOs logged here (this station)
    mine = s.qsos()[0]
    # A peer's QSO syncs into the log under a different station_id.
    peer = replace(mine, uuid="peer-1", call="DX1ABC", station_id="peerXYZ", lamport=999)
    s.engine.log.apply(peer)

    all_adif = s.export_adif()  # everyone
    assert all_adif.count("<EOR>") == 3
    assert "DX1ABC" in all_adif

    my_adif = s.export_adif(mine_only=True)  # just this station
    assert my_adif.count("<EOR>") == 2
    assert "DX1ABC" not in my_adif
    assert "K1ABC" in my_adif


async def test_adif_structure():
    s = await make_logged_session()
    adif = s.export_adif()
    assert "<EOH>" in adif
    assert adif.count("<EOR>") == 2
    assert "<CALL:5>K1ABC" in adif
    assert "<BAND:3>20M" in adif
    assert "<MODE:3>SSB" in adif  # USB maps to SSB in ADIF
    assert "<SRX_STRING:6>2A EPA" in adif
    assert "<CONTEST_ID:7>ARRL-FD" in adif


async def test_adif_my_pota_ref_multi_park():
    """A POTA log's activator parks export as a comma-separated MY_POTA_REF."""
    s = build_session(
        contest_id="pota",
        my_call="W7ABC",
        sent_exchange={},
        extra={"park": "US-1234,US-5678"},
        network=None,
    )
    await s.log_qso(call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={})
    adif = s.export_adif()
    assert "<MY_POTA_REF:15>US-1234,US-5678" in adif


async def test_adif_my_entity_and_state():
    """The operating site's DX entity + location export as MY_COUNTRY / MY_STATE."""
    s = build_session(
        contest_id="pota",
        my_call="W7ABC",
        sent_exchange={},
        extra={"park": "US-1234", "entity": "United States Of America", "location": "US-WA"},
        network=None,
    )
    await s.log_qso(call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={})
    adif = s.export_adif()
    assert "<MY_COUNTRY:24>United States Of America" in adif
    assert "<MY_STATE:2>WA" in adif  # state derived from the "US-WA" location code


async def test_adif_no_my_pota_ref_without_park():
    """Non-POTA logs (no park) don't emit MY_POTA_REF."""
    s = build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        sent_exchange={"class": "1E", "section": "OR"},
        network=None,
    )
    await s.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    assert "MY_POTA_REF" not in s.export_adif()


async def test_adif_ft8_ft4_mode_and_submode():
    """FT8 is a top-level ADIF MODE; FT4 is a SUBMODE of MFSK."""
    s = build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        sent_exchange={"class": "1E", "section": "OR"},
        network=None,
    )
    await s.log_qso(
        call="K1ABC", freq_hz=7_074_000, mode=Mode.FT8, exchange={"class": "1D", "section": "WY"}
    )
    await s.log_qso(
        call="W2XYZ", freq_hz=7_047_500, mode=Mode.FT4, exchange={"class": "1D", "section": "NM"}
    )
    adif = s.export_adif()
    assert "<MODE:3>FT8" in adif
    assert "<MODE:4>MFSK" in adif
    assert "<SUBMODE:3>FT4" in adif
    # FT8 carries no submode.
    assert "<SUBMODE:3>FT8" not in adif


def test_adif_to_mode_roundtrip():
    assert adif_to_mode("FT8") == Mode.FT8
    assert adif_to_mode("MFSK", "FT4") == Mode.FT4
    assert adif_to_mode("PSK", "PSK31") == Mode.PSK31
    assert adif_to_mode("CW") == Mode.CW
    # A bare parent mode with no submode is ambiguous -> unrecognised.
    assert adif_to_mode("MFSK") is None
    assert adif_to_mode("ZZZ") is None


async def test_cabrillo_structure():
    s = await make_logged_session()
    cab = s.export_cabrillo()
    lines = cab.splitlines()
    assert lines[0] == "START-OF-LOG: 3.0"
    assert "CONTEST: ARRL-FD" in cab
    assert "CALLSIGN: W7ABC" in cab
    assert "CLAIMED-SCORE: 6" in cab  # CW(2)+Phone(1)=3 pts x2 power
    assert sum(1 for ln in lines if ln.startswith("QSO:")) == 2
    assert lines[-1] == "END-OF-LOG:"
    assert "K1ABC" in cab and "W2XYZ" in cab
