"""ADIF auto-export decision logic and interval clamping (no QTimer / Qt loop)."""

from __future__ import annotations

from partyhams.app.state import AppState, load_state, save_state
from partyhams.ui.main_window import (
    AUTOEXPORT_MAX,
    AUTOEXPORT_MIN,
    clamp_export_minutes,
    should_autoexport,
)


def test_clamp_within_range_is_unchanged():
    assert clamp_export_minutes(5) == 5
    assert clamp_export_minutes(30) == 30
    assert clamp_export_minutes(60) == 60


def test_clamp_pins_to_bounds():
    assert clamp_export_minutes(0) == AUTOEXPORT_MIN == 5
    assert clamp_export_minutes(4) == 5
    assert clamp_export_minutes(120) == AUTOEXPORT_MAX == 60
    assert clamp_export_minutes(-10) == 5


def test_disabled_never_exports():
    assert should_autoexport(False, True, 10, 0) is False
    assert should_autoexport(False, False, 10, 0) is False


def test_only_if_new_skips_when_count_unchanged():
    # Same count as the last export => nothing new => skip.
    assert should_autoexport(True, True, 5, 5) is False
    # Defensive: a lower count (e.g. deletions) also counts as "no new".
    assert should_autoexport(True, True, 4, 5) is False


def test_only_if_new_exports_when_count_increased():
    assert should_autoexport(True, True, 6, 5) is True
    assert should_autoexport(True, True, 1, 0) is True


def test_only_if_new_false_always_exports_when_enabled():
    assert should_autoexport(True, False, 5, 5) is True
    assert should_autoexport(True, False, 0, 0) is True


def test_autoexport_round_trip(tmp_path):
    path = tmp_path / "state.json"
    default = load_state(path)
    assert default.autoexport_enabled is True
    assert default.autoexport_minutes == 5
    assert default.autoexport_only_if_new is True

    save_state(
        AppState(
            autoexport_enabled=False,
            autoexport_minutes=45,
            autoexport_only_if_new=False,
        ),
        path,
    )
    loaded = load_state(path)
    assert loaded.autoexport_enabled is False
    assert loaded.autoexport_minutes == 45
    assert loaded.autoexport_only_if_new is False
