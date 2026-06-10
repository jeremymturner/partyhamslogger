"""LogSession controller: logging, dupes, validation, score, persistence."""

from __future__ import annotations

from partyhams.app.session import build_session, list_logs
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
    # Case-insensitive on the callsign.
    assert s.is_dupe("k1abc", FREQ_20M, Mode.CW) is True
    # Empty callsign is never a dupe.
    assert s.is_dupe("", FREQ_20M, Mode.CW) is False


async def test_dupe_phone_modes_share_a_group():
    """All phone modes (USB/LSB/FM/AM) collapse to one Field Day slot."""
    s = make_session()
    await s.log_qso(
        call="W1AW", freq_hz=FREQ_20M, mode=Mode.USB, exchange={"class": "2A", "section": "EPA"}
    )
    assert s.is_dupe("W1AW", FREQ_20M, Mode.LSB) is True  # both Phone
    assert s.is_dupe("W1AW", FREQ_20M, Mode.FM) is True
    assert s.is_dupe("W1AW", FREQ_20M, Mode.CW) is False  # CW is its own group


async def test_dupe_digital_modes_share_a_group():
    """FT8 and RTTY both count as Digital — a station worked on one dupes the other."""
    s = make_session()
    await s.log_qso(
        call="N0CALL", freq_hz=FREQ_20M, mode=Mode.FT8, exchange={"class": "1D", "section": "CO"}
    )
    assert s.is_dupe("N0CALL", FREQ_20M, Mode.RTTY) is True  # both Digital
    assert s.is_dupe("N0CALL", FREQ_20M, Mode.PSK31) is True
    assert s.is_dupe("N0CALL", FREQ_20M, Mode.USB) is False  # Phone is distinct
    assert s.is_dupe("N0CALL", FREQ_40M, Mode.FT8) is False  # different band


async def test_update_qso_edits_in_place_and_reindexes():
    s = make_session()
    q = await s.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "2A", "section": "EPA"}
    )
    assert s.is_dupe("K1ABC", FREQ_20M, Mode.CW)

    amended = s.update_qso(
        q, call="K1XYZ", freq_hz=FREQ_40M, mode=Mode.USB, exchange={"class": "1D", "section": "WY"}
    )
    assert amended.uuid == q.uuid  # same record, edited
    assert amended.lamport > q.lamport  # wins last-writer-wins
    assert [(x.call, x.band_label, x.mode.value) for x in s.qsos()] == [("K1XYZ", "40m", "USB")]
    # Dupe index follows the edit: old slot freed, new slot taken.
    assert not s.is_dupe("K1ABC", FREQ_20M, Mode.CW)
    assert s.is_dupe("K1XYZ", FREQ_40M, Mode.USB)


async def test_delete_qso_tombstones_and_persists():
    s = make_session()
    q = await s.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "2A", "section": "EPA"}
    )
    tombstone = s.delete_qso(q)
    assert tombstone.deleted and tombstone.uuid == q.uuid
    assert s.qsos() == []  # gone from the live log
    assert not s.is_dupe("K1ABC", FREQ_20M, Mode.CW)  # and from the dupe index
    # The tombstone is persisted (so the delete survives a reopen / syncs to peers).
    assert any(x.deleted for x in s.store.all(include_deleted=True))


async def test_wipe_log_clears_qsos_memory_and_disk(tmp_path):
    from partyhams.app.session import open_session

    db = tmp_path / "log.sqlite"
    s = build_session(
        contest_id="arrl-field-day",
        my_call="W0CPH",
        sent_exchange={"class": "2A", "section": "OR"},
        network=None,
        db_path=db,
    )
    await s.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    await s.log_qso(
        call="W2XYZ", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1D", "section": "NM"}
    )
    assert len(s.qsos()) == 2 and s.is_dupe("K1ABC", FREQ_20M, Mode.CW)

    s.wipe_log()
    assert s.qsos() == []  # gone from memory
    assert not s.is_dupe("K1ABC", FREQ_20M, Mode.CW)  # and the dupe index
    # No tombstones left behind (a hard wipe, not a CRDT delete).
    assert s.store.all(include_deleted=True) == []
    # Contest setup is preserved.
    assert s.config.my_call == "W0CPH"

    # Persisted: a reopen shows an empty log.
    s.store.close()
    assert open_session(db).qsos() == []


async def test_set_operator_stamps_new_qsos_and_persists(tmp_path):
    db = tmp_path / "log.sqlite"
    from partyhams.app.session import build_session, open_session

    s = build_session(
        contest_id="arrl-field-day",
        my_call="W0CPH",
        operator="N0AW",
        sent_exchange={"class": "1E", "section": "OR"},
        network=None,
        db_path=db,
    )
    q1 = await s.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    assert q1.operator == "N0AW"

    s.set_operator("w1xyz")  # lower-cased -> normalized
    assert s.operator == "W1XYZ"
    q2 = await s.log_qso(
        call="W2ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1D", "section": "NM"}
    )
    assert q2.operator == "W1XYZ"  # new QSOs follow the current operator
    assert q1.station_callsign == "W0CPH"  # station call unchanged

    # Persisted to the log's meta, so a reopen restores the latest operator.
    s.store.close()
    assert open_session(db).operator == "W1XYZ"


async def test_set_operator_ignores_blank_and_noop():
    s = make_session()
    before = s.operator
    s.set_operator("")  # blank -> ignored
    s.set_operator(before)  # same -> no-op
    assert s.operator == before


async def test_dupe_label_message():
    s = make_session()
    assert s.dupe_label("K1ABC", FREQ_20M, Mode.CW) == ""
    await s.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "2A", "section": "EPA"}
    )
    assert s.dupe_label("K1ABC", FREQ_20M, Mode.CW) == "DUPE"
    # Same call works again on a different band / mode group (per the dupe rule).
    await s.log_qso(
        call="K1ABC", freq_hz=FREQ_40M, mode=Mode.FT8, exchange={"class": "2A", "section": "EPA"}
    )
    assert s.dupe_label("K1ABC", FREQ_40M, Mode.RTTY) == "DUPE"  # 40m DIGITAL slot taken
    # Not a dupe -> empty.
    assert s.dupe_label("K1ABC", FREQ_20M, Mode.USB) == ""


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


async def test_list_logs_summarizes_each_file(tmp_path):
    s1 = build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        sent_exchange={"class": "1E", "section": "OR"},
        network=None,
        db_path=tmp_path / "fd.sqlite",
    )
    await s1.log_qso(
        call="K1A", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1A", "section": "OR"}
    )
    build_session(
        contest_id="arrl-field-day",
        my_call="N0AW",
        sent_exchange={"class": "2A", "section": "EPA"},
        network=None,
        db_path=tmp_path / "other.sqlite",
    )

    logs = list_logs(tmp_path)
    by_call = {entry["call"]: entry for entry in logs}
    assert set(by_call) == {"W7ABC", "N0AW"}
    assert by_call["W7ABC"]["qsos"] == 1
    assert by_call["N0AW"]["qsos"] == 0
    assert "Field Day" in by_call["W7ABC"]["contest"]
    assert by_call["W7ABC"]["path"].endswith("fd.sqlite")


async def test_list_logs_missing_dir_is_empty(tmp_path):
    assert list_logs(tmp_path / "nope") == []


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
