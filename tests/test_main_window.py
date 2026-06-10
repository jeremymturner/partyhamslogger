"""Main window behavior under offscreen Qt: F-key bar visibility + WSJT-X mode."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from partyhams.app.session import build_session  # noqa: E402
from partyhams.core.models import Mode  # noqa: E402
from partyhams.wsjtx.protocol import Status  # noqa: E402


def _window():
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    s = build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        sent_exchange={"class": "1E", "section": "OR"},
        network=None,
        db_path=":memory:",
    )
    w = MainWindow(s)
    w.refresh()
    return w


def _set_mode(w, mode: Mode) -> None:
    w._mode.setCurrentIndex(w._mode.findData(mode))


def test_fkey_bar_only_visible_for_cw_and_ssb():
    w = _window()
    for mode in (Mode.CW, Mode.USB, Mode.LSB):
        _set_mode(w, mode)
        assert not w._fkey_bar.isHidden(), f"F-keys should show in {mode.value}"
    for mode in (Mode.FM, Mode.RTTY, Mode.FT8, Mode.FT4):
        _set_mode(w, mode)
        assert w._fkey_bar.isHidden(), f"F-keys should hide in {mode.value}"


def test_wsjtx_status_sets_entry_mode_and_swaps_panel():
    w = _window()
    # A data-mode status flips to the WSJT-X panel and mirrors FT8 vs FT4.
    w._on_wsjtx_status(Status(id="WSJT", mode="FT4", dial_freq=7_047_500))
    assert w._mode.currentData() == Mode.FT4
    assert not w._wsjtx_panel.isHidden()
    assert w._fkey_bar.isHidden()

    w._on_wsjtx_status(Status(id="WSJT", mode="FT8", dial_freq=14_074_000))
    assert w._mode.currentData() == Mode.FT8
    assert not w._wsjtx_panel.isHidden()
