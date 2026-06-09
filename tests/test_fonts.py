"""Font settings: size clamping, QSS size wiring, and state round-trip."""

from __future__ import annotations

from partyhams.app.state import AppState, load_state, save_state
from partyhams.ui import style


def test_clamp_font_size():
    assert style.clamp_font_size(13) == 13
    assert style.clamp_font_size(4) == style.MIN_FONT_SIZE == 8
    assert style.clamp_font_size(99) == style.MAX_FONT_SIZE == 28
    assert style.clamp_font_size(8) == 8
    assert style.clamp_font_size(28) == 28


def test_build_qss_reflects_font_size(monkeypatch):
    # build_qss renders the module-level _font_size into the base QWidget rule.
    monkeypatch.setattr(style, "_font_size", 20)
    assert "font-size: 20px;" in style.build_qss(style._MIDNIGHT)
    monkeypatch.setattr(style, "_font_size", 11)
    assert "font-size: 11px;" in style.build_qss(style._MIDNIGHT)


def test_font_round_trip(tmp_path):
    path = tmp_path / "state.json"
    # Defaults: Qt default family, size 13.
    assert load_state(path).font_family is None
    assert load_state(path).font_size == 13

    save_state(AppState(font_family="Menlo", font_size=18), path)
    loaded = load_state(path)
    assert loaded.font_family == "Menlo"
    assert loaded.font_size == 18
