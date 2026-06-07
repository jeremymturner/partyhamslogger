"""ADIF and Cabrillo export."""

from __future__ import annotations

from partyhams.app.session import build_session
from partyhams.core.models import Mode

FREQ_20M = 14_040_000


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
