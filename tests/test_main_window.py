"""Main window behavior under offscreen Qt: F-key bar visibility + WSJT-X mode."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace  # noqa: E402

from partyhams.app.radio import RadioState  # noqa: E402
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


def _table_calls(w) -> list[str]:
    return [w._table.item(r, 1).text() for r in range(w._table.rowCount())]


async def test_dupe_filters_log_to_that_call_and_clears():
    w = _window()
    s = w.session
    await s.log_qso(
        call="K1ABC", freq_hz=14_040_000, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    await s.log_qso(
        call="W2XYZ", freq_hz=14_040_000, mode=Mode.CW, exchange={"class": "1D", "section": "NM"}
    )
    await s.log_qso(
        call="K1ABC", freq_hz=7_040_000, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    w.refresh()
    assert _table_calls(w) == ["K1ABC", "W2XYZ", "K1ABC"]

    # Typing a dupe call filters the log to every QSO with that call.
    _set_mode(w, Mode.CW)
    w._band.setCurrentText("20m")
    w._call.setText("K1ABC")
    w._refresh_indicators()
    assert w._status_badge.text() == "DUPE"
    assert w._call_filter == "K1ABC"
    assert _table_calls(w) == ["K1ABC", "K1ABC"]

    # Clearing the call field removes the filter.
    w._call.setText("")
    w._refresh_indicators()
    assert w._call_filter == ""
    assert _table_calls(w) == ["K1ABC", "W2XYZ", "K1ABC"]

    # A call that isn't a dupe doesn't filter.
    w._call.setText("N0NEW")
    w._refresh_indicators()
    assert w._call_filter == ""
    assert _table_calls(w) == ["K1ABC", "W2XYZ", "K1ABC"]


async def test_edit_qso_dialog_prefills_and_preserves_freq():
    from partyhams.ui.qso_dialog import QsoEditDialog

    w = _window()
    s = w.session
    q = await s.log_qso(
        call="K1ABC", freq_hz=14_040_000, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    w.refresh()
    assert [x.call for x in w._row_qsos] == ["K1ABC"]

    dialog = QsoEditDialog(s, q)
    assert dialog._call.text() == "K1ABC"
    assert dialog._band.currentData() == "20m"
    assert dialog._mode.currentData() == Mode.CW
    assert dialog._exchange_edits["section"].text() == "WY"

    # Edit call + section, leave band/mode -> exact frequency is preserved.
    dialog._call.setText("K1XYZ")
    dialog._exchange_edits["section"].setText("NM")
    values = dialog.values()
    assert values["freq_hz"] == 14_040_000
    amended = s.update_qso(q, **values)
    assert amended.call == "K1XYZ"
    assert amended.exchange_rcvd["section"] == "NM"
    assert [x.call for x in s.qsos()] == ["K1XYZ"]


async def test_delete_qso_via_row():
    w = _window()
    s = w.session
    q = await s.log_qso(
        call="K1ABC", freq_hz=14_040_000, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    w.refresh()
    assert w._qso_at(0).uuid == q.uuid
    # _delete_qso shows a confirm dialog; exercise the underlying session call here.
    s.delete_qso(w._qso_at(0))
    assert s.qsos() == []


def test_fkey_bar_only_visible_for_cw_and_ssb():
    w = _window()
    for mode in (Mode.CW, Mode.USB, Mode.LSB):
        _set_mode(w, mode)
        assert not w._fkey_bar.isHidden(), f"F-keys should show in {mode.value}"
    for mode in (Mode.FM, Mode.RTTY, Mode.FT8, Mode.FT4):
        _set_mode(w, mode)
        assert w._fkey_bar.isHidden(), f"F-keys should hide in {mode.value}"


def _fake_poller(freq_hz: int, mode: Mode, *, connected: bool = True):
    radio = SimpleNamespace(description=lambda: "Test Rig")
    return SimpleNamespace(
        connected=connected,
        state=RadioState(freq_hz=freq_hz, mode=mode),
        on_state=None,
        on_status=None,
        radio=radio,
    )


def test_band_mode_boxes_hidden_under_cat_and_shown_manually():
    w = _window()
    # Manual (no radio): both pickers visible; status bar shows freq + band only.
    assert not w._band.isHidden() and not w._mode.isHidden()
    assert "CW" not in w._freq.text()  # mode lives in the visible box, not the bar

    # With a CAT radio the rig supplies band/mode: pickers hide, status bar gains mode.
    w.set_poller(_fake_poller(14_175_000, Mode.CW))
    assert w._band.isHidden() and w._mode.isHidden()
    assert w._band_label.isHidden() and w._mode_label.isHidden()
    text = w._freq.text()
    assert "20m" in text and text.rstrip().endswith("CW")  # frequency band mode

    # Detaching the radio brings the manual pickers back.
    w.set_poller(None)
    assert not w._band.isHidden() and not w._mode.isHidden()


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


def test_wsjtx_submode_overrides_rig_data_mode():
    # A CAT rig only knows "data/USB" (read back as FT8); WSJT-X knows FT8 vs FT4.
    # While WSJT-X is active its sub-mode must win — even when the rig keeps
    # re-reporting its coarse FT8 data mode.
    w = _window()
    w.set_poller(_fake_poller(7_074_000, Mode.FT8))  # rig in a data mode
    assert w._current_mode() == Mode.FT8

    w._on_wsjtx_status(Status(id="WSJT", mode="FT4", dial_freq=7_047_500))
    assert w._current_mode() == Mode.FT4
    assert w._freq.text().rstrip().endswith("FT4")

    # A later rig poll still says FT8 — it must not clobber the WSJT-X sub-mode.
    w._apply_radio_state(RadioState(freq_hz=7_047_500, mode=Mode.FT8))
    assert w._current_mode() == Mode.FT4

    # When WSJT-X drops out of a data mode, fall back to the rig's mode.
    w._on_wsjtx_status(Status(id="WSJT", mode="USB", dial_freq=14_200_000))
    assert w._wsjtx_mode is None
    assert w._current_mode() == Mode.FT8  # back to the rig's data mode
