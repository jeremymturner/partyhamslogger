"""App state persistence and log-file open/save round-trip."""

from __future__ import annotations

from pathlib import Path

from partyhams.app.session import build_session, open_session
from partyhams.app.state import (
    MAX_RECENT_LOGS,
    AppState,
    load_state,
    new_log_path,
    push_recent,
    save_state,
)
from partyhams.core.models import Mode


def test_state_round_trip(tmp_path):
    path = tmp_path / "state.json"
    assert load_state(path) == AppState()  # missing file -> defaults

    state = AppState(current_log="/logs/fd.sqlite", radio={"kind": "flex", "conn": ""})
    save_state(state, path)
    loaded = load_state(path)
    assert loaded.current_log == "/logs/fd.sqlite"
    assert loaded.radio == {"kind": "flex", "conn": ""}


def test_theme_round_trip(tmp_path):
    path = tmp_path / "state.json"
    assert load_state(path).theme is None  # default: follow the OS
    save_state(AppState(theme="Sand (warm)"), path)
    assert load_state(path).theme == "Sand (warm)"


def test_cw_speed_mode_round_trip(tmp_path):
    path = tmp_path / "state.json"
    assert load_state(path).cw_speed_mode == "sync"  # default
    save_state(AppState(cw_speed_mode="restore"), path)
    assert load_state(path).cw_speed_mode == "restore"


def test_cw_presets_round_trip(tmp_path):
    path = tmp_path / "state.json"
    defaults = load_state(path)
    assert defaults.cw_wpm_presets == [24, 20]  # seeded defaults
    assert defaults.cw_presets_enabled is True
    save_state(AppState(cw_wpm_presets=[35, 18, 13], cw_presets_enabled=False), path)
    loaded = load_state(path)
    assert loaded.cw_wpm_presets == [35, 18, 13]
    assert loaded.cw_presets_enabled is False


def test_recent_logs_round_trip(tmp_path):
    path = tmp_path / "state.json"
    state = AppState()
    push_recent(state, "/logs/a.sqlite")
    push_recent(state, "/logs/b.sqlite")
    save_state(state, path)
    assert load_state(path).recent_logs == ["/logs/b.sqlite", "/logs/a.sqlite"]


def test_push_recent_dedups_and_caps():
    state = AppState()
    for i in range(MAX_RECENT_LOGS + 3):
        push_recent(state, f"/logs/{i}.sqlite")
    # Most-recent first, capped at the limit.
    assert len(state.recent_logs) == MAX_RECENT_LOGS
    assert state.recent_logs[0] == f"/logs/{MAX_RECENT_LOGS + 2}.sqlite"
    # Re-pushing an existing path moves it to the front without duplicating.
    push_recent(state, "/logs/5.sqlite")
    assert state.recent_logs[0] == "/logs/5.sqlite"
    assert state.recent_logs.count("/logs/5.sqlite") == 1


def test_load_state_tolerates_garbage(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json {{{")
    assert load_state(path) == AppState()


def test_new_log_path(tmp_path):
    from datetime import date

    when = date(2026, 6, 27)
    p = new_log_path("arrl-field-day", "W7/ABC", logs_dir=tmp_path, when=when)
    assert p.endswith("arrl-field-day-W7_ABC-20260627.sqlite")


def test_new_log_path_is_unique_per_creation(tmp_path):
    from datetime import date

    when = date(2026, 6, 27)
    p1 = new_log_path("arrl-field-day", "W7ABC", logs_dir=tmp_path, when=when)
    Path(p1).write_text("")  # the first log now exists on disk
    p2 = new_log_path("arrl-field-day", "W7ABC", logs_dir=tmp_path, when=when)
    assert p1 != p2  # same contest/call/day -> a distinct path, not an overwrite
    assert p2.endswith("arrl-field-day-W7ABC-20260627-2.sqlite")


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
