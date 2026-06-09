"""Auto-CQ decision logic and interval clamping (no QTimer / Qt loop)."""

from __future__ import annotations

from partyhams.app.state import AppState, load_state, save_state
from partyhams.ui.main_window import (
    AUTOCQ_MAX,
    AUTOCQ_MIN,
    clamp_autocq_interval,
    should_autocq,
)


def test_clamp_within_range_is_unchanged():
    assert clamp_autocq_interval(5) == 5
    assert clamp_autocq_interval(10) == 10
    assert clamp_autocq_interval(30) == 30


def test_clamp_pins_to_bounds():
    assert clamp_autocq_interval(0) == AUTOCQ_MIN == 5
    assert clamp_autocq_interval(3) == 5
    assert clamp_autocq_interval(45) == AUTOCQ_MAX == 30
    assert clamp_autocq_interval(-100) == 5


def test_should_autocq_only_in_run_mode():
    assert should_autocq(run=True, enabled=True, call_text="") is True
    assert should_autocq(run=False, enabled=True, call_text="") is False


def test_should_autocq_requires_enabled():
    assert should_autocq(run=True, enabled=False, call_text="") is False


def test_should_autocq_stops_when_callsign_entered():
    assert should_autocq(run=True, enabled=True, call_text="W7A") is False
    # Whitespace-only entry is treated as empty (still CQ-ing).
    assert should_autocq(run=True, enabled=True, call_text="   ") is True


def test_autocq_interval_round_trip(tmp_path):
    path = tmp_path / "state.json"
    assert load_state(path).autocq_interval == 10  # default
    save_state(AppState(autocq_interval=20), path)
    assert load_state(path).autocq_interval == 20
