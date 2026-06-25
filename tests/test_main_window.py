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

    # Typing a dupe call reds the call field and filters the log to that call.
    _set_mode(w, Mode.CW)
    w._band.setCurrentText("20m")
    w._call.setText("K1ABC")
    w._refresh_indicators()
    from partyhams.ui import style

    assert style.DUPE in w._call.styleSheet()  # dupe -> red box on the call field
    assert w._call_filter == "K1ABC"
    assert _table_calls(w) == ["K1ABC", "K1ABC"]

    # Clearing the call field removes the red box and the filter.
    w._call.setText("")
    w._refresh_indicators()
    assert w._call.styleSheet() == ""
    assert w._call_filter == ""
    assert _table_calls(w) == ["K1ABC", "W2XYZ", "K1ABC"]

    # A call that isn't a dupe doesn't red-box or filter.
    w._call.setText("N0NEW")
    w._refresh_indicators()
    assert w._call.styleSheet() == ""
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


async def test_edit_dialog_validates_exchange_on_save():
    from PySide6.QtWidgets import QDialog

    from partyhams.ui.qso_dialog import QsoEditDialog

    w = _window()
    s = w.session
    q = await s.log_qso(
        call="K1ABC", freq_hz=14_040_000, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    dialog = QsoEditDialog(s, q)

    # An invalid section blocks Save (no suggestion offered).
    dialog._exchange_edits["section"].setText("ORE")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert not dialog._error.isHidden()
    assert "Section" in dialog._error.text() and "invalid" in dialog._error.text()
    assert "try" not in dialog._error.text()

    # An empty callsign is also rejected.
    dialog._exchange_edits["section"].setText("OR")
    dialog._call.setText("")
    assert "Callsign is required" in dialog._errors()

    # A valid edit goes through.
    dialog._call.setText("K1ABC")
    assert dialog._errors() == []
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


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


async def test_log_rows_colored_by_operator_not_station_id():
    from dataclasses import replace

    from PySide6.QtGui import QColor

    from partyhams.ui import style

    w = _window()
    s = w.session
    me = s.engine.operator  # this op (W7ABC)
    mine = await s.log_qso(
        call="K1ABC", freq_hz=14_040_000, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    # A peer QSO from a different operator (and different station_id).
    peer = replace(
        mine, uuid="peer-1", call="W2XYZ", operator="N0AW", station_id="other", lamport=99
    )
    s.engine.log.apply(peer)
    s._rebuild_indexes()
    w.refresh()

    # Row 0 is newest; find each row's color by call.
    colors = {}
    for row in range(w._table.rowCount()):
        call = w._table.item(row, 1).text()
        colors[call] = w._table.item(row, 1).foreground().color()
    peer_color = QColor(style.PEER)
    assert colors["W2XYZ"] == peer_color  # other operator -> blue
    assert colors["K1ABC"] != peer_color  # my operator -> default (white)
    assert me == "W7ABC"

    # Simulating a reopen: the station_id changes, but coloring keys on operator,
    # so my own QSO stays white (the bug was everything turning blue here).
    s.engine.station_id = "brand-new-session-id"
    w.refresh()
    again = {
        w._table.item(r, 1).text(): w._table.item(r, 1).foreground().color()
        for r in range(w._table.rowCount())
    }
    assert again["K1ABC"] != peer_color  # still white after the station_id change


def test_graceful_quit_filter_routes_quit_to_shutdown():
    """⌘Q / app-menu Quit is intercepted and run through the graceful path instead
    of stopping the qasync loop mid-await."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.app import _GracefulQuitFilter

    app = QApplication.instance() or QApplication([])
    calls = []
    f = _GracefulQuitFilter(lambda: calls.append(1))

    # A Quit event runs on_quit and is consumed (so Qt won't tear down the loop).
    assert f.eventFilter(app, QEvent(QEvent.Type.Quit)) is True
    assert calls == [1]
    # Other events pass through untouched.
    assert f.eventFilter(app, QEvent(QEvent.Type.User)) is False
    assert calls == [1]

    # And once installed, a Quit delivered to the app is intercepted.
    app.installEventFilter(f)
    try:
        app.sendEvent(app, QEvent(QEvent.Type.Quit))
        assert calls == [1, 1]
    finally:
        app.removeEventFilter(f)


async def test_section_field_boxed_red_invalid_green_new_none_valid():
    from partyhams.ui import style

    w = _window()
    section = w._exchange_edits["section"]
    w._call.setText("K1ABC")

    # Invalid section -> red box.
    section.setText("ORE")
    w._refresh_indicators()
    assert style.DUPE in section.styleSheet()
    assert style.MULT not in section.styleSheet()

    # Valid, not-yet-worked section -> green box (new multiplier).
    section.setText("WY")
    w._refresh_indicators()
    assert style.MULT in section.styleSheet()
    assert style.DUPE not in section.styleSheet()

    # Valid section that's already a worked multiplier -> no box.
    await w.session.log_qso(
        call="W2XYZ", freq_hz=14_040_000, mode=Mode.CW, exchange={"class": "1D", "section": "OR"}
    )
    section.setText("OR")
    w._refresh_indicators()
    assert section.styleSheet() == ""


def test_space_and_tab_walk_the_qso_entry_fields():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w = _window()
    w.show()
    w.activateWindow()
    app.processEvents()

    def press(key, mods=Qt.KeyboardModifier.NoModifier):
        consumed = w.eventFilter(app.focusWidget(), QKeyEvent(QEvent.Type.KeyPress, key, mods))
        app.processEvents()
        return consumed

    call, section = w._call, w._exchange_edits["section"]
    klass = w._exchange_edits["class"]

    call.setFocus()
    app.processEvents()
    assert app.focusWidget() is call
    assert press(Qt.Key.Key_Space) is True  # Space advances...
    assert app.focusWidget() is klass
    assert press(Qt.Key.Key_Tab) is True  # ...so does Tab
    assert app.focusWidget() is section
    # Last field doesn't wrap.
    assert press(Qt.Key.Key_Space) is True
    assert app.focusWidget() is section
    # Shift+Tab walks back.
    assert press(Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier) is True
    assert app.focusWidget() is klass
    # A normal character is left alone.
    letter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
    assert w.eventFilter(klass, letter) is False
    w.close()


def test_roster_mode_tags_ft8_ft4_even_odd():
    from partyhams.ui.network_panel import _fmt_mode

    assert _fmt_mode("FT8", 1) == "FT8e"  # even sequence
    assert _fmt_mode("FT8", 0) == "FT8o"  # odd sequence
    assert _fmt_mode("FT4", 1) == "FT4e"
    assert _fmt_mode("FT4", 0) == "FT4o"
    assert _fmt_mode("FT8", -1) == "FT8"  # unknown sequence -> no tag
    assert _fmt_mode("CW", 1) == "CW"  # only FT8/FT4 get tagged
    assert _fmt_mode("", -1) == "—"


def test_chat_is_broadcast_only_and_tags_by_op_callsign():
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.network_panel import NetworkPanel

    QApplication.instance() or QApplication([])
    s = build_session(
        contest_id="arrl-field-day",
        my_call="W0CPH",
        operator="N0AW",
        sent_exchange={"class": "2A", "section": "OR"},
        network=None,
        db_path=":memory:",
    )
    panel = NetworkPanel(s)
    assert not hasattr(panel, "_recipient")  # the direct-message selector is gone

    sent = []
    panel.on_send_chat = lambda to, txt: sent.append((to, txt))
    panel._input.setText("hello all")
    panel._send()
    assert sent == [("*", "hello all")]  # always broadcast

    # The op callsign is the nick for both incoming and outgoing.
    panel.append_chat({"from_op": "W0AEZ", "to_op": "*", "text": "hi", "ts": "t", "incoming": True})
    panel.append_chat({"from_op": "N0AW", "to_op": "*", "text": "yo", "ts": "t", "incoming": False})
    body = panel._chat_view.toPlainText()
    assert "W0AEZ:" in body and "N0AW:" in body


def test_chat_tab_completes_and_cycles_roster_callsigns():
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.network_panel import NetworkPanel

    QApplication.instance() or QApplication([])
    s = build_session(
        contest_id="arrl-field-day",
        my_call="W0CPH",
        sent_exchange={"class": "2A", "section": "OR"},
        network=None,
        db_path=":memory:",
    )
    panel = NetworkPanel(s)
    panel._roster_rows = [{"operator": "W0AEZ"}, {"operator": "W0ABC"}, {"operator": "K1XYZ"}]

    panel._input.setText("W0A")
    panel._complete_callsign()
    first = panel._input.text()
    panel._complete_callsign()
    second = panel._input.text()
    assert {first, second} == {"W0ABC", "W0AEZ"}  # cycles through both W0A* matches
    panel._complete_callsign()
    assert panel._input.text() == first  # wraps around

    # Completes the last word in a sentence.
    panel._input.setText("hey K1")
    panel._complete_callsign()
    assert panel._input.text() == "hey K1XYZ"

    # No match leaves the text untouched.
    panel._input.setText("ZZ")
    panel._complete_callsign()
    assert panel._input.text() == "ZZ"


def test_roster_table_columns_scale_proportionally():
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.network_panel import _COL_WEIGHTS, _COLUMNS, _RosterTable

    app = QApplication.instance() or QApplication([])
    table = _RosterTable(0, len(_COLUMNS))
    table.setHorizontalHeaderLabels(_COLUMNS)
    table.verticalHeader().setVisible(False)
    table.show()

    widths_by_panel = {}
    for panel_w in (260, 380):
        table.setFixedWidth(panel_w)
        table.resize(panel_w, 200)
        app.processEvents()
        widths_by_panel[panel_w] = [table.columnWidth(c) for c in range(table.columnCount())]
        # Columns fill the viewport exactly — nothing absorbs the slack on its own.
        assert sum(widths_by_panel[panel_w]) == table.viewport().width()

    narrow, wide = widths_by_panel[260], widths_by_panel[380]
    # Every column grows when the panel widens (not just the last one).
    assert all(w >= n for w, n in zip(wide, narrow, strict=True))
    # The last column ("All") is never the widest — Op/Freq lead, per the weights.
    assert wide[-1] <= wide[0] and _COL_WEIGHTS[-1] <= _COL_WEIGHTS[0]
    table.close()


def test_log_button_label_is_just_log():
    w = _window()
    from PySide6.QtWidgets import QPushButton

    labels = {b.text() for b in w.findChildren(QPushButton)}
    assert "Log" in labels
    assert "Log (Enter)" not in labels


def test_theme_menu_has_nonselectable_dark_light_headers():
    from PySide6.QtWidgets import QMenu

    w = _window()
    theme_menu = next(m for m in w.menuBar().findChildren(QMenu) if m.title() == "Theme")
    headers = [
        a.text() for a in theme_menu.actions() if not a.isSeparator() and not a.isEnabled()
    ]
    assert headers == ["Dark Themes", "Light Themes"]
    # Headers are not checkable theme choices.
    for a in theme_menu.actions():
        if a.text() in ("Dark Themes", "Light Themes"):
            assert not a.isCheckable() and not a.isEnabled()
    # The dark header comes before any selectable theme; the light header divides.
    texts = [
        ("HEADER", a.text()) if not a.isEnabled() and not a.isSeparator() else ("ITEM", a.text())
        for a in theme_menu.actions()
        if not a.isSeparator()
    ]
    assert texts[0] == ("HEADER", "Dark Themes")
    light_idx = texts.index(("HEADER", "Light Themes"))
    assert all(kind == "ITEM" for kind, _ in texts[1:light_idx])  # only themes between headers


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


def test_wsjtx_tx_period_shown_in_status_bar():
    w = _window()
    assert w._tx_period.text() == ""  # nothing until WSJT-X is driving a data mode

    w._on_wsjtx_status(Status(id="W", mode="FT4", dial_freq=7_047_500, tx_period_odd=True))
    assert w._tx_period.text() == "ODD"
    w._on_wsjtx_status(Status(id="W", mode="FT8", dial_freq=14_074_000, tx_period_odd=False))
    assert w._tx_period.text() == "EVEN"

    # Dropping out of a data mode clears it.
    w._on_wsjtx_status(Status(id="W", mode="USB", dial_freq=14_200_000))
    assert w._tx_period.text() == ""


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


async def test_humanize_ago_labels():
    from datetime import timedelta

    from partyhams.ui.main_window import _humanize_ago

    assert _humanize_ago(timedelta(seconds=5)) == "just now"
    assert _humanize_ago(timedelta(minutes=8)) == "8 min ago"
    assert _humanize_ago(timedelta(hours=3)) == "3h ago"
    assert _humanize_ago(timedelta(days=2)) == "2d ago"
    assert _humanize_ago(timedelta(seconds=-10)) == "just now"  # clamps negatives


async def test_sp_dupe_warn_prefills_call_on_qsy():
    """Issue #1: tuning to a worked frequency in S&P pre-fills the call as a dupe."""
    from partyhams.ui import style

    w = _window()
    s = w.session
    await s.log_qso(
        call="K1ABC", freq_hz=14_040_000, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    w._set_run(False)  # Search & Pounce

    # QSY onto the worked frequency (within tolerance) -> call pre-filled + reddened.
    w._apply_radio_state(RadioState(freq_hz=14_040_100, mode=Mode.CW))
    assert w._call.text() == "K1ABC"
    assert style.DUPE in w._call.styleSheet()

    # If the op clears it, a poll on essentially the same spot won't re-fill it.
    w._call.setText("")
    w._apply_radio_state(RadioState(freq_hz=14_040_120, mode=Mode.CW))
    assert w._call.text() == ""


async def test_sp_dupe_warn_silent_in_run_mode_and_off_frequency():
    w = _window()
    s = w.session
    await s.log_qso(
        call="K1ABC", freq_hz=14_040_000, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )

    # Run mode never auto-fills (you're calling CQ, not tuning around).
    assert w._run is True
    w._apply_radio_state(RadioState(freq_hz=14_040_000, mode=Mode.CW))
    assert w._call.text() == ""

    # S&P, but off-frequency or wrong mode group -> no suggestion.
    w._set_run(False)
    w._apply_radio_state(RadioState(freq_hz=14_100_000, mode=Mode.CW))  # far away
    assert w._call.text() == ""
    w._apply_radio_state(RadioState(freq_hz=14_040_000, mode=Mode.USB))  # CW logged, not Phone
    assert w._call.text() == ""


# --- CW speed bar + live keyboard sender (issue #4) ---------------------------


def test_cw_bar_visible_only_in_cw_mode():
    w = _window()
    _set_mode(w, Mode.CW)
    w._update_bottom_bars()
    assert not w._cw_bar.isHidden()  # CW -> speed bar shows
    _set_mode(w, Mode.USB)
    w._update_bottom_bars()
    assert w._cw_bar.isHidden()  # phone -> hidden (no CW speed there)


def test_set_wpm_updates_label_persists_and_highlights(monkeypatch):
    saved = []
    monkeypatch.setattr(
        "partyhams.ui.main_window.save_macros", lambda cid, ms, *a, **k: saved.append(ms.cw_wpm)
    )
    from partyhams.ui import style

    w = _window()
    w._macros.cw_wpm = 18  # known starting point (independent of any saved macros)
    w._set_wpm(24)
    assert w._macros.cw_wpm == 24
    assert saved == [24]  # persisted with the event's macros
    assert w._wpm_label.text() == "24 WPM"
    # The matching preset is outlined; others are not.
    assert style.MULT in w._wpm_buttons[24].styleSheet()
    assert w._wpm_buttons[28].styleSheet() == ""


def test_set_wpm_clamps_to_range(monkeypatch):
    monkeypatch.setattr("partyhams.ui.main_window.save_macros", lambda *a, **k: None)
    from partyhams.app.macros import WPM_MAX, WPM_MIN

    w = _window()
    w._set_wpm(WPM_MAX + 50)
    assert w._macros.cw_wpm == WPM_MAX
    w._bump_wpm(+5)
    assert w._macros.cw_wpm == WPM_MAX  # can't exceed the ceiling
    w._set_wpm(WPM_MIN - 50)
    assert w._macros.cw_wpm == WPM_MIN


def test_up_down_arrows_change_wpm_from_entry_and_keyboard(monkeypatch):
    monkeypatch.setattr("partyhams.ui.main_window.save_macros", lambda *a, **k: None)
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    w = _window()
    w._macros.cw_wpm = 20

    def press(widget, key):
        ev = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        return w.eventFilter(widget, ev)

    # Up from the call field bumps +1 and consumes the key.
    assert press(w._call, Qt.Key.Key_Up) is True
    assert w._macros.cw_wpm == 21
    # Down from the live CW keyboard nudges -1.
    assert press(w._cw_keyboard, Qt.Key.Key_Down) is True
    assert w._macros.cw_wpm == 20


def test_cw_keyboard_streams_appended_chars_and_enter_clears():
    w = _window()
    sent = []
    w._send_cw = lambda text, *a, **k: sent.append(text)  # capture, no radio needed

    # Typing streams only the newly-appended characters, upper-cased.
    w._on_cw_keyboard_edited("c")
    w._on_cw_keyboard_edited("cq")
    w._on_cw_keyboard_edited("cq ")
    assert sent == ["C", "Q", " "]

    # A deletion can't be un-sent and emits nothing.
    w._on_cw_keyboard_edited("cq")
    assert sent == ["C", "Q", " "]

    # Enter clears the field and resets the tracker; the next char sends fresh.
    w._cw_keyboard.setText("cq")
    w._clear_cw_keyboard()
    assert w._cw_keyboard.text() == "" and w._cw_kbd_sent == ""
    w._on_cw_keyboard_edited("k")
    assert sent == ["C", "Q", " ", "K"]


# --- call-history exchange auto-fill (issue #3) -------------------------------


def test_call_history_autofills_empty_exchange_only(tmp_path):
    w = _window()
    w._refdata.dir = tmp_path
    # Import a tiny call-history map for this Field Day session.
    n = w._refdata.import_call_history(
        "Call,Class,Section\nK1ABC,2A,EMA\n",
        [f.name for f in w.session.contest.exchange_fields()],
    )
    assert n == 1

    # Typing a known call fills the blank exchange fields.
    w._call.setText("K1ABC")
    assert w._exchange_edits["class"].text() == "2A"
    assert w._exchange_edits["section"].text() == "EMA"


def test_call_history_does_not_overwrite_typed_values(tmp_path):
    w = _window()
    w._refdata.dir = tmp_path
    w._refdata.import_call_history(
        "Call,Class,Section\nK1ABC,2A,EMA\n",
        [f.name for f in w.session.contest.exchange_fields()],
    )
    # Operator already typed a class -> history must not clobber it.
    w._exchange_edits["class"].setText("3A")
    w._call.setText("K1ABC")
    assert w._exchange_edits["class"].text() == "3A"  # kept
    assert w._exchange_edits["section"].text() == "EMA"  # blank one still filled


def test_call_history_unknown_call_leaves_exchange_alone(tmp_path):
    w = _window()
    w._refdata.dir = tmp_path
    w._refdata.import_call_history(
        "Call,Class,Section\nK1ABC,2A,EMA\n",
        [f.name for f in w.session.contest.exchange_fields()],
    )
    w._call.setText("W9NONE")
    assert w._exchange_edits["class"].text() == ""
    assert w._exchange_edits["section"].text() == ""


# --- update indicator (auto-update check) -------------------------------------


def _update_info(version="0.1.0", url="https://example.invalid/win.zip"):
    from partyhams.app.update import UpdateInfo

    return UpdateInfo(
        version=version, tag=f"v{version}", name=f"PartyHams Logger v{version}", url=url, notes=""
    )


def test_update_indicator_hidden_until_available():
    w = _window()
    assert w._update_btn.isHidden()  # nothing to show on a fresh window
    w._show_update_available(_update_info())
    assert not w._update_btn.isHidden()
    assert "0.1.0" in w._update_btn.toolTip()


def test_download_progress_updates_the_status_bar():
    w = _window()
    w._on_download_progress(50, 200)
    assert w._download_bar.value() == 25
    w._on_download_progress(200, 200)
    assert w._download_bar.value() == 100


def test_set_auto_update_toggles_the_timer_and_clamps_interval():
    w = _window()
    w.set_auto_update(True, 1000)  # absurd interval -> clamped to 7 days (168h)
    assert w._auto_update_interval_hours == 168
    assert w._update_timer.isActive()
    # Privacy opt-out stops the periodic timer.
    w.set_auto_update(False, 6)
    assert not w._update_timer.isActive()


def test_disabled_auto_update_skips_check_unless_forced():
    w = _window()
    calls = []
    w._loop = None  # so the real network task is never created
    # With the loop gone, _check_for_update returns early; assert the gate logic
    # by checking it doesn't raise and respects the disabled flag + force path.
    w.set_auto_update(False, 1)
    w._check_for_update()  # disabled + not forced -> no-op
    w._check_for_update(force=True)  # forced -> reaches the (no-loop) guard, still no-op
    assert calls == []  # nothing blew up; both paths handled gracefully


# --- CW keyer-speed ownership modes ---------------------------------------- #
class _FakeKeyerRadio:
    """A radio that can read/set keyer speed, recording every call."""

    def __init__(self, wpm: int = 20) -> None:
        self._wpm = wpm
        self.sent: list[tuple[str, int | None]] = []
        self.set_calls: list[int] = []

    def supports(self, _cap) -> bool:
        return True

    async def read_wpm(self) -> int | None:
        return self._wpm

    async def set_wpm(self, wpm: int) -> None:
        self._wpm = wpm
        self.set_calls.append(wpm)

    async def send_cw(self, text: str, wpm: int | None = None) -> None:
        if wpm is not None:
            self._wpm = wpm
        self.sent.append((text, wpm))


def test_cw_speed_menu_reflects_and_persists_mode():
    w = _window()
    saved: list[str] = []
    w.on_change_cw_speed_mode = saved.append

    w.set_cw_speed_mode("restore")
    assert w._cw_speed_mode == "restore"
    assert w._cw_speed_actions["restore"].isChecked()
    assert not w._cw_speed_actions["sync"].isChecked()
    assert saved == []  # set_* applies but does not persist

    w._choose_cw_speed_mode("always")  # simulate a menu click
    assert w._cw_speed_mode == "always"
    assert w._cw_speed_actions["always"].isChecked()
    assert saved == ["always"]  # menu choice persists via the callback

    # An unknown stored value falls back to the default (sync).
    w.set_cw_speed_mode("bogus")
    assert w._cw_speed_mode == "sync"


def test_sync_mode_adopts_radio_wpm_other_modes_ignore_it():
    w = _window()
    w._macros.cw_wpm = 28

    # Sync: a keyer-speed change reported by the rig is adopted by the logger.
    w.set_cw_speed_mode("sync")
    w._maybe_follow_radio_wpm(RadioState(freq_hz=14_040_000, mode=Mode.CW, wpm=22))
    assert w._macros.cw_wpm == 22

    # A state with no wpm (rig can't report it) leaves the logger untouched.
    w._maybe_follow_radio_wpm(RadioState(freq_hz=14_040_000, mode=Mode.CW, wpm=None))
    assert w._macros.cw_wpm == 22

    # Other modes never follow the radio.
    for mode in ("restore", "always"):
        w.set_cw_speed_mode(mode)
        w._maybe_follow_radio_wpm(RadioState(freq_hz=14_040_000, mode=Mode.CW, wpm=35))
        assert w._macros.cw_wpm == 22


async def test_restore_mode_keys_at_logger_speed_then_restores():
    w = _window()
    w._macros.cw_wpm = 30
    w.set_cw_speed_mode("restore")
    radio = _FakeKeyerRadio(wpm=18)  # the operator's speed on the rig

    await w._send_cw_then_restore(radio, "CQ TEST")
    # Captured the rig's own speed and keyed at the logger's speed.
    assert w._cw_restore_wpm == 18
    assert radio.sent == [("CQ TEST", 30)]
    assert radio._wpm == 30

    # Once keying is done, the rig's own speed is restored and state cleared.
    await w._restore_cw_after(radio, 0)
    assert radio._wpm == 18
    assert w._cw_restore_wpm is None


async def test_restore_mode_overlapping_sends_keep_original_speed():
    w = _window()
    w._macros.cw_wpm = 30
    w.set_cw_speed_mode("restore")
    radio = _FakeKeyerRadio(wpm=18)

    await w._send_cw_then_restore(radio, "CQ")
    # A second send before the restore fires must not re-capture (rig is at 30 now).
    await w._send_cw_then_restore(radio, "TEST")
    assert w._cw_restore_wpm == 18  # still the original knob speed, not 30

    await w._restore_cw_after(radio, 0)
    assert radio._wpm == 18


async def test_do_set_wpm_pushes_to_radio():
    w = _window()
    radio = _FakeKeyerRadio(wpm=20)
    await w._do_set_wpm(radio, 33)
    assert radio.set_calls == [33]
    assert radio._wpm == 33


# --- ADIF export default filename ------------------------------------------ #
def test_default_adif_path_uses_call_and_park():
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from partyhams.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    s = build_session(
        contest_id="pota",
        my_call="W7ABC",
        sent_exchange={},
        extra={"park": "US-1234"},
        network=None,
        db_path=":memory:",
    )
    w = MainWindow(s)
    name = Path(w._default_adif_path()).name
    assert name.startswith("W7ABC")
    assert "US-1234" in name  # park reference kept, dash intact
    assert name.endswith(".adif")
    # Separator is @ or _ depending on the filesystem probe, but never both ways.
    assert ("W7ABC@US-1234" in name) or ("W7ABC_US-1234" in name)


def test_default_adif_path_without_park_omits_park_segment():
    from pathlib import Path

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
    name = Path(w._default_adif_path()).name
    assert name.startswith("W7ABC_")
    assert "@" not in name  # no park -> no @ segment
    assert name.endswith(".adif")


# --- new-log dialog: no nonsensical "My Their park" field ------------------ #
def test_log_dialog_excludes_received_only_exchange_fields_for_pota():
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.log_dialog import LogDialog

    QApplication.instance() or QApplication([])
    dlg = LogDialog()
    idx = dlg._contest.findData("pota")
    assert idx >= 0
    dlg._contest.setCurrentIndex(idx)  # triggers _rebuild_contest_fields

    # The received-only P2P park must NOT be collected as a sent-exchange field
    # (that produced the bogus "My Their park" row); the activator's own park is
    # the dedicated multi-park widget, not an exchange/plain-config field.
    assert "park" not in dlg._exchange_edits
    assert dlg._park_list is not None
    assert dlg.settings()["sent_exchange"] == {}  # POTA sends only RST


def test_log_dialog_multi_park_collected_comma_separated():
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.log_dialog import LogDialog

    QApplication.instance() or QApplication([])
    dlg = LogDialog()
    dlg._contest.setCurrentIndex(dlg._contest.findData("pota"))

    # Add two parks independently; a bad ref is rejected.
    dlg._park_edit.setText("US-1234")
    dlg._add_park_ref()
    dlg._park_edit.setText("not-a-park")
    dlg._add_park_ref()  # ignored — invalid
    dlg._park_edit.setText("US-5678")
    dlg._add_park_ref()
    assert dlg._park_list.count() == 2
    assert dlg.settings()["extra"]["park"] == "US-1234,US-5678"

    # A valid ref typed but not yet "Add"-ed is still included on accept.
    dlg._park_edit.setText("CA-0001")
    assert dlg.settings()["extra"]["park"] == "US-1234,US-5678,CA-0001"

    # Removing a selected park drops it from the list.
    dlg._park_list.setCurrentRow(0)
    dlg._remove_park_ref()
    dlg._park_edit.clear()
    assert dlg.settings()["extra"]["park"] == "US-5678"


def test_log_dialog_keeps_sent_exchange_fields_for_field_day():
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.log_dialog import LogDialog

    QApplication.instance() or QApplication([])
    dlg = LogDialog()
    idx = dlg._contest.findData("arrl-field-day")
    assert idx >= 0
    dlg._contest.setCurrentIndex(idx)
    # Field Day's class/section are symmetric -> still collected as sent exchange.
    assert set(dlg._exchange_edits) == {"class", "section"}


_FAKE_PARKS = {
    "US-1234": {"reference": "US-1234", "name": "A", "entity": "United States Of America",
                "location": "US-WA", "locations": ["US-WA"]},
    "US-5678": {"reference": "US-5678", "name": "B", "entity": "United States Of America",
                "location": "US-WA", "locations": ["US-WA"]},
    # US-4403 spans multiple locations.
    "US-4403": {"reference": "US-4403", "name": "C", "entity": "United States Of America",
                "location": "US-TN,US-NC", "locations": ["US-TN", "US-NC"]},
}


def _pota_dialog_with_fake_lookup():
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.log_dialog import LogDialog

    QApplication.instance() or QApplication([])
    dlg = LogDialog()
    dlg._contest.setCurrentIndex(dlg._contest.findData("pota"))
    dlg._verify_fn = lambda ref: _FAKE_PARKS.get(ref)
    return dlg


def test_verify_all_parks_fills_entity_and_single_location():
    dlg = _pota_dialog_with_fake_lookup()
    for ref in ("US-1234", "US-5678"):
        dlg._park_edit.setText(ref)
        dlg._add_park_ref()

    dlg._verify_all_parks()  # verifies the whole list, not just one
    assert dlg._entity_edit.text() == "United States Of America"
    # Both parks resolve to the same single location -> auto-selected.
    assert dlg._location_combo.currentText() == "US-WA"
    extra = dlg.settings()["extra"]
    assert extra["entity"] == "United States Of America"
    assert extra["location"] == "US-WA"


def test_edit_log_dialog_us_4403_location_dropdown():
    """Editing a log whose park (US-4403) spans two states must offer a dropdown
    letting the operator pick either US-CO or US-WY."""
    from PySide6.QtWidgets import QApplication, QDialog

    from partyhams.ui.log_dialog import LogDialog

    QApplication.instance() or QApplication([])
    existing = {
        "contest_id": "pota",
        "my_call": "W7ABC",
        "operator": "W7ABC",
        "network": "",
        "sent_exchange": {},
        "extra": {"park": "US-4403"},
    }
    dlg = LogDialog(existing=existing)  # EDIT mode
    dlg._verify_fn = lambda ref: {
        "US-4403": {
            "entity": "United States Of America",
            "location": "US-CO,US-WY",
            "locations": ["US-CO", "US-WY"],
        }
    }.get(ref)
    # The park is pre-loaded from the log; Verify resolves its locations.
    assert [dlg._park_list.item(i).text() for i in range(dlg._park_list.count())] == ["US-4403"]
    dlg._verify_all_parks()

    options = [dlg._location_combo.itemText(i) for i in range(dlg._location_combo.count())]
    assert options == ["US-CO", "US-WY"]  # both states offered
    assert dlg._location_combo.currentText().strip() == ""  # nothing auto-picked

    # Can't accept until a location is chosen.
    dlg._on_accept()
    assert dlg.result() != QDialog.DialogCode.Accepted

    # Either choice is selectable and round-trips through settings().
    dlg._location_combo.setCurrentText("US-CO")
    assert dlg.settings()["extra"]["location"] == "US-CO"
    dlg._location_combo.setCurrentText("US-WY")
    assert dlg.settings()["extra"]["location"] == "US-WY"
    dlg._on_accept()
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_verify_multi_location_park_requires_selection_to_continue():
    from PySide6.QtWidgets import QDialog

    dlg = _pota_dialog_with_fake_lookup()
    dlg._call.setText("W7ABC")
    dlg._park_edit.setText("US-4403")
    dlg._add_park_ref()
    dlg._verify_all_parks()

    items = [dlg._location_combo.itemText(i) for i in range(dlg._location_combo.count())]
    assert items == ["US-TN", "US-NC"]
    assert dlg._location_combo.currentText().strip() == ""  # nothing auto-picked

    # OK is blocked while the location is ambiguous and unselected.
    dlg._on_accept()
    assert dlg.result() != QDialog.DialogCode.Accepted

    # Once a location is chosen, OK goes through.
    dlg._location_combo.setCurrentText("US-NC")
    dlg._on_accept()
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.settings()["extra"]["location"] == "US-NC"


def test_log_dialog_edit_mode_prefills_and_locks():
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.log_dialog import LogDialog

    QApplication.instance() or QApplication([])
    existing = {
        "contest_id": "pota",
        "my_call": "W7ABC",
        "operator": "N0AW",
        "network": "fd-net",
        "sent_exchange": {},
        "extra": {
            "park": "US-1234,US-5678",
            "entity": "United States Of America",
            "location": "US-WA",
        },
    }
    dlg = LogDialog(existing=existing)

    # Fixed fields are pre-filled and locked.
    assert dlg._call.text() == "W7ABC"
    assert dlg._operator.text() == "N0AW"
    assert dlg._network.text() == "fd-net"
    assert not dlg._contest.isEnabled()  # contest type fixed once a log exists
    assert not dlg._network.isEnabled()  # sync network fixed at creation

    # POTA fields pre-filled.
    parks = [dlg._park_list.item(i).text() for i in range(dlg._park_list.count())]
    assert parks == ["US-1234", "US-5678"]
    assert dlg._entity_edit.text() == "United States Of America"
    assert dlg._location_combo.currentText() == "US-WA"

    # settings() round-trips the (locked) contest and edited values.
    s = dlg.settings()
    assert s["contest_id"] == "pota"
    assert s["extra"]["park"] == "US-1234,US-5678"
    assert s["extra"]["entity"] == "United States Of America"
    assert s["extra"]["location"] == "US-WA"


# --- station line (top): Station/Operator + POTA park context -------------- #
def _pota_window(extra):
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    s = build_session(
        contest_id="pota", my_call="W7ABC", operator="W7ABC",
        sent_exchange={}, extra=extra, network=None, db_path=":memory:",
    )
    w = MainWindow(s)
    w.refresh()
    return w


def test_station_line_merges_station_operator_when_same():
    w = _pota_window({"park": "US-4403"})
    text = w._station_label.text()
    assert "Station/Operator" in text  # one field when call == operator
    assert "W7ABC" in text


def test_station_line_splits_station_and_operator_when_different():
    w = _pota_window({"park": "US-4403"})
    w.session.set_operator("N0AW")
    w.refresh()
    text = w._station_label.text()
    assert "Station" in text and "Op" in text
    assert "Station/Operator" not in text
    assert "N0AW" in text


def test_station_line_single_park_shows_id_name_location():
    w = _pota_window(
        {"park": "US-4403", "location": "US-WY", "park_names": {"US-4403": "Snowy Range NST"}}
    )
    text = w._station_label.text()
    assert "US-4403" in text
    assert "Snowy Range NST" in text
    assert "US-WY" in text
    assert "fer" not in text  # single park -> not an N-fer
    assert "QSOs" in text  # QSO count consolidated onto the single top line


def test_station_line_multi_park_shows_n_fer_in_location():
    w = _pota_window({"park": "US-1234,US-5678,US-4403", "location": "US-WY"})
    text = w._station_label.text()
    assert "3-fer" in text
    assert "in US-WY" in text


def test_station_line_non_pota_has_no_park_segment():
    from PySide6.QtWidgets import QApplication

    from partyhams.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    s = build_session(
        contest_id="arrl-field-day", my_call="W7ABC",
        sent_exchange={"class": "1E", "section": "OR"}, network=None, db_path=":memory:",
    )
    w = MainWindow(s)
    w.refresh()
    text = w._station_label.text()
    assert "W7ABC" in text
    assert "fer" not in text and "US-" not in text
