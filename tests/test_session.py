"""LogSession controller: logging, dupes, validation, score, persistence."""

from __future__ import annotations

from partyhams.app.session import build_session
from partyhams.core.models import Mode

FREQ_20M = 14_040_000
FREQ_40M = 7_030_000


def make_session(db_path=":memory:", power="low_150w", network=None):
    return build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        sent_exchange={"class": "1E", "section": "OR"},
        power=power,
        network=network,
        db_path=db_path,
    )


async def test_log_and_persist():
    s = make_session()
    await s.log_qso(
        call="k1abc", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "2A", "section": "EPA"}
    )
    qsos = s.qsos()
    assert len(qsos) == 1
    assert qsos[0].call == "K1ABC"  # upper-cased
    assert qsos[0].operator == "W7ABC"
    # Persisted to the store, too.
    assert len(s.store.all()) == 1


async def test_dupe_detection_per_band_and_mode():
    s = make_session()
    assert s.is_dupe("K1ABC", FREQ_20M, Mode.CW) is False
    await s.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "2A", "section": "EPA"}
    )
    assert s.is_dupe("K1ABC", FREQ_20M, Mode.CW) is True  # same slot
    assert s.is_dupe("K1ABC", FREQ_20M, Mode.USB) is False  # different mode group
    assert s.is_dupe("K1ABC", FREQ_40M, Mode.CW) is False  # different band


async def test_validate_exchange():
    s = make_session()
    assert s.validate_exchange({"class": "3A", "section": "OR"}) == []
    assert s.validate_exchange({"class": "3A"}) == ["Section is required"]
    bad = s.validate_exchange({"class": "ZZ", "section": "OR"})
    assert any("Class" in e for e in bad)
    bad2 = s.validate_exchange({"class": "3A", "section": "ZZ"})
    assert any("Section" in e for e in bad2)


async def test_score_uses_power_multiplier():
    s = make_session(power="low_150w")  # x2
    await s.log_qso(
        call="K1A", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1A", "section": "OR"}
    )
    # One CW QSO = 2 points, x2 power = 4.
    assert s.score().total == 4


async def test_new_mult_detection():
    s = make_session()
    # A section not yet worked is a new mult; an empty section is not.
    assert s.new_mults("K1A", FREQ_20M, Mode.CW, {"class": "2A", "section": "EPA"}) == {
        ("section", "EPA")
    }
    assert s.new_mults("K1A", FREQ_20M, Mode.CW, {"class": "2A", "section": ""}) == set()
    # After logging EPA, it's no longer new (even on a different band).
    await s.log_qso(
        call="K1A", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "2A", "section": "EPA"}
    )
    assert s.new_mults("K9Z", FREQ_40M, Mode.USB, {"class": "1D", "section": "EPA"}) == set()
    assert s.new_mults("K9Z", FREQ_40M, Mode.USB, {"class": "1D", "section": "OR"}) == {
        ("section", "OR")
    }


async def test_field_day_logs_no_rst():
    s = make_session()
    await s.log_qso(
        call="K1A", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1A", "section": "OR"}
    )
    qso = s.qsos()[0]
    assert qso.rst_sent == "" and qso.rst_rcvd == ""


async def test_section_status_tracks_band_mode_slots():
    s = make_session()
    await s.log_qso(
        call="K1A", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "2A", "section": "EPA"}
    )
    await s.log_qso(
        call="K2B", freq_hz=FREQ_40M, mode=Mode.USB, exchange={"class": "1A", "section": "EPA"}
    )
    await s.log_qso(
        call="K3C", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1A", "section": "OR"}
    )
    status = s.section_status()
    assert status["EPA"] == {("20m", "CW"), ("40m", "PHONE")}
    assert status["OR"] == {("20m", "CW")}
    assert "STX" not in status  # not worked


async def test_partial_matches():
    s = make_session()
    for call in ("K1ABC", "K1AXY", "W2ZZZ"):
        await s.log_qso(
            call=call, freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1A", "section": "OR"}
        )
    assert s.partial_matches("K1A") == ["K1ABC", "K1AXY"]
    assert s.partial_matches("") == []


async def test_listener_fires_on_log():
    s = make_session()
    hits = []
    s.add_listener(lambda: hits.append(len(s.qsos())))
    await s.log_qso(
        call="K1A", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1A", "section": "OR"}
    )
    assert hits == [1]


async def test_reload_from_disk(tmp_path):
    db = tmp_path / "log.sqlite"
    s1 = make_session(db_path=db)
    await s1.log_qso(
        call="K1A", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1A", "section": "OR"}
    )
    await s1.log_qso(
        call="K2B", freq_hz=FREQ_40M, mode=Mode.USB, exchange={"class": "1A", "section": "EPA"}
    )

    # A fresh session on the same DB file recovers the full log.
    s2 = make_session(db_path=db)
    assert {q.call for q in s2.qsos()} == {"K1A", "K2B"}
    # And the dupe set is rebuilt from disk.
    assert s2.is_dupe("K1A", FREQ_20M, Mode.CW) is True
