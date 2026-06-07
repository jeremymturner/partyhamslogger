"""App state persistence and log-file open/save round-trip."""

from __future__ import annotations

from partyhams.app.session import build_session, open_session
from partyhams.app.state import AppState, load_state, new_log_path, save_state
from partyhams.core.models import Mode


def test_state_round_trip(tmp_path):
    path = tmp_path / "state.json"
    assert load_state(path) == AppState()  # missing file -> defaults

    state = AppState(current_log="/logs/fd.sqlite", radio={"kind": "flex", "conn": ""})
    save_state(state, path)
    loaded = load_state(path)
    assert loaded.current_log == "/logs/fd.sqlite"
    assert loaded.radio == {"kind": "flex", "conn": ""}


def test_load_state_tolerates_garbage(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json {{{")
    assert load_state(path) == AppState()


def test_new_log_path(tmp_path):
    p = new_log_path("arrl-field-day", "W7/ABC", logs_dir=tmp_path)
    assert p.endswith("arrl-field-day-W7_ABC.sqlite")


def test_log_file_is_self_describing(tmp_path):
    db = tmp_path / "fd.sqlite"
    s1 = build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        operator="N0AW",
        sent_exchange={"class": "2A", "section": "OR"},
        network="fd-2026",
        extra={"power": "qrp_5w_alt"},
        db_path=db,
    )
    # record_qso is synchronous and doesn't touch the network transport.
    s1.record_qso(
        call="K1ABC", freq_hz=14_040_000, mode=Mode.CW, exchange={"class": "1A", "section": "EPA"}
    )

    # Reopen purely from the file — contest, config, and QSOs all restored.
    s2 = open_session(db)
    assert s2.contest.id == "arrl-field-day"
    assert s2.config.my_call == "W7ABC"
    assert s2.engine.operator == "N0AW"
    assert s2.config.sent_exchange == {"class": "2A", "section": "OR"}
    assert s2.config.extra["power"] == "qrp_5w_alt"
    assert s2.store.get_meta("network") == "fd-2026"
    assert {q.call for q in s2.qsos()} == {"K1ABC"}
    # The QRP power multiplier survives the round-trip (one CW QSO = 2 pts x5).
    assert s2.score().total == 10


def test_open_session_rejects_non_log(tmp_path):
    import pytest

    from partyhams.db.store import SqliteLog

    db = tmp_path / "empty.sqlite"
    SqliteLog(db).close()  # a valid sqlite file but no meta
    with pytest.raises(ValueError):
        open_session(db)


def test_field_day_config_fields():
    from partyhams.contest import get

    fields = get("arrl-field-day").config_fields()
    assert [f.name for f in fields] == ["power"]
    assert fields[0].choices is not None
    assert ("Low — ≤150 W (×2)", "low_150w") in fields[0].choices
