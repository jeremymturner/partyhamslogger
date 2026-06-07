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

from PySide6.QtCore import Qt
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

from partyhams.app.session import LogSession
from partyhams.core.models import Band, Mode, band_by_label
from partyhams.ui.style import ACCENT, AMBER, DUPE, MULT, MULT_BG, PEER, TEXT

# Modes offered in the entry row.
_ENTRY_MODES = [Mode.CW, Mode.USB, Mode.LSB, Mode.FM, Mode.RTTY, Mode.FT8]


class MainWindow(QMainWindow):
    def __init__(self, session: LogSession, on_close: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.session = session
        self._on_close = on_close
        self.setWindowTitle(f"PartyHams Logger — {session.config.my_call} — {session.contest.name}")
        self.resize(900, 560)

        # Log columns adapt to the contest (Field Day has no RST exchange).
        self._columns = ["UTC", "Call", "Band", "Mode"]
        if session.contest.exchanges_rst:
            self._columns += ["RST S", "RST R"]
        self._columns += ["Exchange", "Op"]

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(self._build_score_bar())
        layout.addWidget(self._build_entry_row())
        layout.addWidget(self._build_log_table(), stretch=1)
        layout.addLayout(self._build_buttons())
        self.setCentralWidget(root)

        session.add_listener(self.refresh)
        self._call.setFocus()
        self.refresh()

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
        self._call.setMaximumWidth(140)
        self._call.textChanged.connect(lambda *_: self._refresh_indicators())
        self._call.returnPressed.connect(self._advance_or_log)
        hbox.addWidget(QLabel("Call"))
        hbox.addWidget(self._call)

        # Exchange fields, generated from the contest definition.
        self._exchange_edits: dict[str, QLineEdit] = {}
        for field in self.session.contest.exchange_fields():
            edit = QLineEdit()
            edit.setMaximumWidth(90)
            edit.setPlaceholderText(field.label)
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

        # Status indicators: new-multiplier (green) and dupe (red).
        self._mult = QLabel()
        self._mult.setStyleSheet(f"font-weight: bold; color: {MULT};")
        hbox.addWidget(self._mult)
        self._dupe = QLabel()
        self._dupe.setMinimumWidth(60)
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
        band = self._current_band()
        return (band.low_hz + band.high_hz) // 2

    def _current_mode(self) -> Mode:
        return self._mode.currentData()

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
            self._call.setFocus()
            return
        parsed = {name: e.text().strip().upper() for name, e in self._exchange_edits.items()}
        errors = self.session.validate_exchange(parsed)
        if errors:
            self.statusBar().showMessage("  •  ".join(errors), 4000)
            return
        asyncio.ensure_future(self._do_log(call, parsed))

    async def _do_log(self, call: str, exchange: dict[str, str]) -> None:
        await self.session.log_qso(
            call=call,
            freq_hz=self._current_freq(),
            mode=self._current_mode(),
            exchange=exchange,
        )
        self._call.clear()
        for edit in self._exchange_edits.values():
            edit.clear()
        self._call.setFocus()
        self.statusBar().showMessage(f"Logged {call}", 2500)

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
        name = self.session.contest.name
        mult_label = self.session.contest.mult_label
        self._score_label.setText(
            f"<b style='color:{ACCENT}'>{call}</b> &nbsp;·&nbsp; {name} &nbsp;|&nbsp; "
            f"QSOs <b style='color:{TEXT}'>{s.qso_count}</b> &nbsp; "
            f"Pts <b style='color:{TEXT}'>{s.qso_points}</b> &nbsp; "
            f"{mult_label} <b style='color:{MULT}'>{s.mult_count}</b> &nbsp; "
            f"Pwr <b style='color:{AMBER}'>×{mult}</b> &nbsp; "
            f"Score <b style='color:{AMBER}'>{s.total}</b>{peer_txt}"
        )

    def _reload_table(self) -> None:
        qsos = list(reversed(self.session.recent(200)))  # newest first
        self._table.setRowCount(len(qsos))
        for row, q in enumerate(qsos):
            exchange = " ".join(
                q.exchange_rcvd.get(f.name, "") for f in self.session.contest.exchange_fields()
            )
            values = [q.timestamp.strftime("%H:%M:%S"), q.call, q.band_label, q.mode.value]
            if self.session.contest.exchanges_rst:
                values += [q.rst_sent, q.rst_rcvd]
            values += [exchange.strip(), q.operator]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if q.operator != self.session.config.my_call:
                    item.setForeground(QColor(PEER))  # QSOs from a peer station
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
