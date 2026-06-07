"""The main logging window: score bar, keyboard-first entry row, and live log.

Binds to a :class:`~partyhams.app.session.LogSession`. The entry row is built
*from the contest's exchange schema*, so this same window serves any contest —
Field Day today, CQ WW tomorrow — with no UI changes.

Keyboard flow (N1MM-style): type the call, Enter advances to the next empty
field, Enter on the last field logs the QSO, clears, and refocuses the call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from partyhams.app.radio import RadioPoller
from partyhams.app.session import LogSession
from partyhams.core.models import Band, Mode, band_by_label, band_for_freq
from partyhams.radio.base import RadioState
from partyhams.ui.style import ACCENT, AMBER, DUPE, MULT, MULT_BG, PEER, TEXT, TEXT_DIM
from partyhams.ui.widgets import make_upper

# Modes offered in the entry row.
_ENTRY_MODES = [Mode.CW, Mode.USB, Mode.LSB, Mode.FM, Mode.RTTY, Mode.FT8]


class MainWindow(QMainWindow):
    def __init__(
        self,
        session: LogSession,
        on_close: Callable[[], None] | None = None,
        radio_poller: RadioPoller | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self._on_close = on_close
        #: Set by the app to a no-arg callback that re-runs the radio screen.
        self.on_change_radio: Callable[[], None] | None = None
        self._radio_dialog = None  # app keeps the open radio dialog alive here
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = None  # no loop (e.g. tests) -> log locally, skip broadcast

        # CAT state (managed via set_poller). When a poller is present, band/mode/
        # frequency follow the rig and the manual combos become read-only mirrors.
        self._poller: RadioPoller | None = None
        self._cat = False
        self._radio_freq: int | None = None
        self._radio_mode: Mode | None = None
        self._radio_connected = False

        self.setWindowTitle(f"PartyHams Logger — {session.config.my_call} — {session.contest.name}")
        self.resize(1060, 580)

        # Log columns adapt to the contest (Field Day has no RST exchange).
        self._columns = ["UTC", "Call", "Band", "Mode"]
        if session.contest.exchanges_rst:
            self._columns += ["RST S", "RST R"]
        self._columns += ["Exchange", "Op"]

        self._build_menu()
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(self._build_score_bar())
        layout.addWidget(self._build_entry_row())
        layout.addWidget(self._build_log_table(), stretch=1)
        layout.addLayout(self._build_buttons())
        self.setCentralWidget(root)

        session.add_listener(self.refresh)
        # Permanent radio indicator on the right of the status bar.
        self._radio_status_label = QLabel()
        self.statusBar().addPermanentWidget(self._radio_status_label)

        self.set_poller(radio_poller)
        self._call.setFocus()
        self.refresh()

    def _build_menu(self) -> None:
        radio_menu = self.menuBar().addMenu("Radio")
        action = radio_menu.addAction("Select Radio…")
        action.triggered.connect(self._radio_menu_clicked)

    def _radio_menu_clicked(self) -> None:
        if self.on_change_radio is not None:
            self.on_change_radio()

    def set_poller(self, poller: RadioPoller | None) -> None:
        """Attach (or detach) a radio poller and rewire CAT state live."""
        self._poller = poller
        self._cat = poller is not None
        self._radio_freq = None
        self._radio_mode = None
        self._radio_connected = poller.connected if poller is not None else False
        self._band.setEnabled(not self._cat)
        self._mode.setEnabled(not self._cat)
        if poller is not None:
            poller.on_state = self._on_radio_state
            poller.on_status = self._on_radio_status
            if poller.state is not None:
                self._apply_radio_state(poller.state)
        self._refresh_indicators()
        self._update_radio_label()

    def _update_radio_label(self) -> None:
        if self._poller is None:
            self._radio_status_label.setText("📻 No radio (manual)")
            self._radio_status_label.setStyleSheet(f"color: {TEXT_DIM};")
            return
        desc = self._poller.radio.description()
        if self._radio_connected:
            self._radio_status_label.setText(f"📻 {desc}")
            self._radio_status_label.setStyleSheet(f"color: {MULT};")
        else:
            self._radio_status_label.setText(f"📻 {desc} · disconnected")
            self._radio_status_label.setStyleSheet(f"color: {AMBER};")

    def closeEvent(self, event: QCloseEvent) -> None:
        # Hand control back to the app loop for graceful async shutdown.
        if self._on_close is not None:
            self._on_close()
        event.accept()

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    def _build_score_bar(self) -> QLabel:
        self._score_label = QLabel()
        self._score_label.setObjectName("scoreBar")  # themed in ui/style.py
        self._score_label.setTextFormat(Qt.TextFormat.RichText)
        return self._score_label

    def _build_entry_row(self) -> QWidget:
        row = QWidget()
        hbox = QHBoxLayout(row)

        self._call = QLineEdit()
        self._call.setPlaceholderText("Call")
        self._call.setMinimumWidth(110)
        self._call.setMaximumWidth(160)
        make_upper(self._call)
        self._call.textChanged.connect(lambda *_: self._refresh_indicators())
        self._call.returnPressed.connect(self._advance_or_log)
        hbox.addWidget(QLabel("Call"))
        hbox.addWidget(self._call)

        # Exchange fields, generated from the contest definition.
        self._exchange_edits: dict[str, QLineEdit] = {}
        for field in self.session.contest.exchange_fields():
            edit = QLineEdit()
            edit.setMinimumWidth(72)
            edit.setMaximumWidth(100)
            edit.setPlaceholderText(field.label)
            make_upper(edit)
            edit.returnPressed.connect(self._advance_or_log)
            edit.textChanged.connect(lambda *_: self._refresh_indicators())
            self._exchange_edits[field.name] = edit
            hbox.addWidget(QLabel(field.label))
            hbox.addWidget(edit)

        # Band + mode (no CAT yet — chosen manually; auto-fill comes next).
        self._band = QComboBox()
        for band in self._sorted_bands():
            self._band.addItem(band.label, band)
        default_band = self._band.findText("20m")  # busiest FD band
        if default_band >= 0:
            self._band.setCurrentIndex(default_band)
        self._band.currentIndexChanged.connect(lambda *_: self._refresh_indicators())
        hbox.addWidget(QLabel("Band"))
        hbox.addWidget(self._band)

        self._mode = QComboBox()
        for mode in _ENTRY_MODES:
            self._mode.addItem(mode.value, mode)
        self._mode.currentIndexChanged.connect(lambda *_: self._refresh_indicators())
        hbox.addWidget(QLabel("Mode"))
        hbox.addWidget(self._mode)

        # Frequency readout (live from CAT when a radio is connected). Fixed width
        # so its content changing doesn't shift the row.
        self._freq = QLabel()
        self._freq.setFixedWidth(140)
        self._freq.setStyleSheet(f"color: {ACCENT}; font-weight: 600;")
        hbox.addWidget(self._freq)

        # Status indicators: new-multiplier (green) and dupe (red). Both reserve a
        # fixed width so showing/hiding a badge never squishes the entry fields.
        self._mult = QLabel()
        self._mult.setFixedWidth(110)
        self._mult.setStyleSheet(f"font-weight: bold; color: {MULT};")
        hbox.addWidget(self._mult)
        self._dupe = QLabel()
        self._dupe.setFixedWidth(75)
        self._dupe.setStyleSheet(f"font-weight: bold; color: {DUPE};")
        hbox.addWidget(self._dupe)

        log_btn = QPushButton("Log (Enter)")
        log_btn.clicked.connect(self._try_log)
        hbox.addWidget(log_btn)

        hbox.addStretch(1)
        return row

    def _build_log_table(self) -> QTableWidget:
        self._table = QTableWidget(0, len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        return self._table

    def _build_buttons(self) -> QHBoxLayout:
        hbox = QHBoxLayout()
        adif_btn = QPushButton("Export ADIF…")
        adif_btn.clicked.connect(self._export_adif)
        cab_btn = QPushButton("Export Cabrillo…")
        cab_btn.clicked.connect(self._export_cabrillo)
        hbox.addStretch(1)
        hbox.addWidget(adif_btn)
        hbox.addWidget(cab_btn)
        return hbox

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _sorted_bands(self) -> list[Band]:
        bands = [band_by_label(lbl) for lbl in self.session.allowed_bands()]
        bands = [b for b in bands if b is not None]
        bands.sort(key=lambda b: b.low_hz)
        return bands

    def _current_band(self) -> Band:
        return self._band.currentData()

    def _current_freq(self) -> int:
        if self._cat and self._radio_freq is not None:
            return self._radio_freq
        band = self._current_band()
        return (band.low_hz + band.high_hz) // 2

    def _current_mode(self) -> Mode:
        if self._cat and self._radio_mode is not None:
            return self._radio_mode
        return self._mode.currentData()

    # ------------------------------------------------------------------ #
    # CAT (radio) integration
    # ------------------------------------------------------------------ #
    def _on_radio_state(self, state: RadioState) -> None:
        self._apply_radio_state(state)

    def _on_radio_status(self, connected: bool, error: str | None) -> None:
        self._radio_connected = connected
        if not connected:
            self.statusBar().showMessage(
                f"Radio disconnected{f' ({error})' if error else ''}", 3000
            )
        self._update_freq_readout()
        self._update_radio_label()

    def _apply_radio_state(self, state: RadioState) -> None:
        self._radio_freq = state.freq_hz
        self._radio_mode = state.mode
        # Mirror onto the (disabled) combos for a familiar display.
        band = band_for_freq(state.freq_hz)
        if band is not None:
            idx = self._band.findText(band.label)
            if idx >= 0:
                self._band.setCurrentIndex(idx)
        mode_idx = self._mode.findData(state.mode)
        if mode_idx >= 0:
            self._mode.setCurrentIndex(mode_idx)
        self._refresh_indicators()  # updates dupe/mult badges + the freq readout
        self._update_radio_label()  # model/nickname may have just arrived

    def _update_freq_readout(self) -> None:
        freq = self._current_freq()
        mhz, khz, hz = freq // 1_000_000, (freq // 1000) % 1000, (freq % 1000) // 10
        band = band_for_freq(freq)
        text = f"{mhz}.{khz:03d}.{hz:02d}  {band.label if band else '?'}"
        if self._cat:
            if self._radio_connected:
                self._freq.setText(f"📻 {text}")
                self._freq.setStyleSheet(f"color: {ACCENT}; font-weight: 600;")
            else:
                self._freq.setText("📻 no radio")
                self._freq.setStyleSheet(f"color: {AMBER}; font-weight: 600;")
        else:
            self._freq.setText(text)
            self._freq.setStyleSheet(f"color: {TEXT_DIM};")

    # ------------------------------------------------------------------ #
    # entry behavior
    # ------------------------------------------------------------------ #
    def _refresh_indicators(self) -> None:
        """Update the dupe + new-multiplier badges and tint mult exchange fields."""
        call = self._call.text().strip().upper()
        freq, mode = self._current_freq(), self._current_mode()
        is_dupe = bool(call) and self.session.is_dupe(call, freq, mode)
        self._dupe.setText("● DUPE" if is_dupe else "")

        exchange = {name: e.text().strip().upper() for name, e in self._exchange_edits.items()}
        new = self.session.new_mults(call, freq, mode, exchange) if call and not is_dupe else set()
        new_types = {mtype for mtype, _ in new}
        self._mult.setText("★ NEW " + "/".join(sorted(t.upper() for t in new_types)) if new else "")
        # Tint the exchange field(s) that carry a new multiplier.
        for field in self.session.contest.exchange_fields():
            edit = self._exchange_edits[field.name]
            if field.name in new_types and edit.text().strip():
                edit.setStyleSheet(f"border: 1px solid {MULT}; background-color: {MULT_BG};")
            else:
                edit.setStyleSheet("")

        self._update_freq_readout()

    def _advance_or_log(self) -> None:
        if not self._call.text().strip():
            self._call.setFocus()
            return
        for field in self.session.contest.exchange_fields():
            edit = self._exchange_edits[field.name]
            if field.required and not edit.text().strip():
                edit.setFocus()
                return
        self._try_log()

    def _try_log(self) -> None:
        call = self._call.text().strip().upper()
        if not call:
            self._flash(self._call)
            self._call.setFocus()
            self.statusBar().showMessage("Enter a callsign to log", 3000)
            return
        parsed = {name: e.text().strip().upper() for name, e in self._exchange_edits.items()}
        errors = self.session.validate_exchange(parsed)
        if errors:
            # Make the failure obvious: flash the first bad field and focus it.
            self._highlight_invalid(parsed)
            self.statusBar().showMessage("Not logged — " + " • ".join(errors), 5000)
            return

        # Record locally and synchronously so the log updates instantly, then
        # broadcast to peers as a best-effort side effect (offline = no-op).
        qso = self.session.record_qso(
            call=call, freq_hz=self._current_freq(), mode=self._current_mode(), exchange=parsed
        )
        self._broadcast(qso)

        self._call.clear()
        for edit in self._exchange_edits.values():
            edit.clear()
        self._call.setFocus()
        self.statusBar().showMessage(f"Logged {call}", 2500)

    def _broadcast(self, qso) -> None:
        """Fire-and-forget network broadcast; the QSO is already logged locally."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return  # no running loop (offline/tests) -> local log is enough
        try:
            loop.create_task(self.session.broadcast(qso))
        except Exception as exc:  # noqa: BLE001 - never block logging on the network
            self.statusBar().showMessage(f"Logged (broadcast deferred: {exc})", 3000)

    def _highlight_invalid(self, parsed: dict[str, str]) -> None:
        focused = False
        for field in self.session.contest.exchange_fields():
            value = parsed.get(field.name, "")
            ok = bool(value) and (field.validator is None or field.validator(value))
            if (field.required and not value) or not ok:
                edit = self._exchange_edits[field.name]
                self._flash(edit)
                if not focused:
                    edit.setFocus()
                    focused = True

    def _flash(self, widget: QLineEdit) -> None:
        """Briefly outline a field in red to signal a problem."""
        widget.setStyleSheet(f"border: 1px solid {DUPE}; background-color: #3a2326;")
        QTimer.singleShot(900, lambda: widget.setStyleSheet(""))

    # ------------------------------------------------------------------ #
    # refresh (fired by the session on any log change)
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        self._update_score_bar()
        self._refresh_indicators()
        self._reload_table()

    def _update_score_bar(self) -> None:
        s = self.session.score()
        mult = s.breakdown.get("power_multiplier", 1)
        peers = len(self.session.peers)
        peer_txt = f" &nbsp;|&nbsp; Peers <b style='color:{PEER}'>{peers}</b>" if peers else ""
        call = self.session.config.my_call
        operator = self.session.engine.operator
        name = self.session.contest.name
        mult_label = self.session.contest.mult_label
        op_txt = (
            f" <span style='color:{TEXT_DIM}'>op</span> {operator}"
            if operator and operator != call
            else ""
        )
        self._score_label.setText(
            f"<span style='color:{TEXT_DIM}'>Station</span> "
            f"<b style='color:{ACCENT}'>{call}</b>{op_txt} &nbsp;·&nbsp; {name} &nbsp;|&nbsp; "
            f"QSOs <b style='color:{TEXT}'>{s.qso_count}</b> &nbsp; "
            f"Pts <b style='color:{TEXT}'>{s.qso_points}</b> &nbsp; "
            f"{mult_label} <b style='color:{MULT}'>{s.mult_count}</b> &nbsp; "
            f"Pwr <b style='color:{AMBER}'>×{mult}</b> &nbsp; "
            f"Score <b style='color:{AMBER}'>{s.total}</b>{peer_txt}"
        )

    def _reload_table(self) -> None:
        qsos = list(reversed(self.session.recent(200)))  # newest first
        self._table.setRowCount(len(qsos))
        local_station = self.session.engine.station_id
        for row, q in enumerate(qsos):
            exchange = " ".join(
                q.exchange_rcvd.get(f.name, "") for f in self.session.contest.exchange_fields()
            )
            values = [q.timestamp.strftime("%H:%M:%S"), q.call, q.band_label, q.mode.value]
            if self.session.contest.exchanges_rst:
                values += [q.rst_sent, q.rst_rcvd]
            values += [exchange.strip(), q.operator]
            is_peer = q.station_id != local_station  # logged at another station
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if is_peer:
                    item.setForeground(QColor(PEER))
                self._table.setItem(row, col, item)

    # ------------------------------------------------------------------ #
    # export
    # ------------------------------------------------------------------ #
    def _export_adif(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export ADIF", "partyhams.adi", "ADIF (*.adi)")
        if path:
            Path(path).write_text(self.session.export_adif())
            self.statusBar().showMessage(f"Exported ADIF to {path}", 4000)

    def _export_cabrillo(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Cabrillo", "partyhams.cbr", "Cabrillo (*.cbr *.log)"
        )
        if path:
            Path(path).write_text(self.session.export_cabrillo())
            self.statusBar().showMessage(f"Exported Cabrillo to {path}", 4000)
