"""The network side panel: a station roster (top) and a chat box (bottom).

Top: every station we've detected — operator, frequency, mode, QSO counts in the
last 15 / 60 minutes, and their all-time total in this log (our own row first).
Bottom: a chat where a message goes to everyone by default, or to one operator.

Data comes from the :class:`~partyhams.app.session.LogSession`; sending a chat
calls :attr:`on_send_chat` (wired by the main window to post + broadcast).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from partyhams.app.session import LogSession
from partyhams.ui.style import ACCENT, AMBER, MULT, PEER, TEXT_DIM

_COLUMNS = ["Op", "Freq", "Mode", "15m", "60m", "All"]


def _fmt_freq(freq_hz: int) -> str:
    return f"{freq_hz / 1_000_000:.3f}" if freq_hz else "—"


def _short_time(iso_ts: str) -> str:
    try:
        return datetime.fromisoformat(iso_ts).strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


class NetworkPanel(QWidget):
    def __init__(self, session: LogSession) -> None:
        super().__init__()
        self.session = session
        #: Wired by the main window: on_send_chat(to_op, text).
        self.on_send_chat: Callable[[str, str], None] | None = None
        self._known_ops: list[str] = []
        self.setMinimumWidth(292)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- stations ---
        stations = QWidget()
        sv = QVBoxLayout(stations)
        sv.setContentsMargins(6, 6, 6, 2)
        sv.addWidget(self._section_label("Stations"))
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setShowGrid(False)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.horizontalHeader().setStretchLastSection(False)
        # Tight padding so all 7 columns fit (and text isn't truncated) in the panel.
        self._table.setStyleSheet(
            "QHeaderView::section { padding: 4px 2px; }QTableWidget::item { padding: 2px 4px; }"
        )
        for col, width in enumerate((72, 62, 44, 38, 38, 38)):
            self._table.setColumnWidth(col, width)
        sv.addWidget(self._table)
        splitter.addWidget(stations)

        # --- chat ---
        chat = QWidget()
        cv = QVBoxLayout(chat)
        cv.setContentsMargins(6, 2, 6, 6)
        cv.addWidget(self._section_label("Chat"))
        self._chat_view = QTextEdit()
        self._chat_view.setReadOnly(True)
        cv.addWidget(self._chat_view, stretch=1)

        row = QHBoxLayout()
        self._recipient = QComboBox()
        self._recipient.addItem("Everyone", "*")
        self._recipient.setMinimumWidth(110)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Message… (Enter to send)")
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._recipient)
        row.addWidget(self._input, stretch=1)
        cv.addLayout(row)
        splitter.addWidget(chat)

        splitter.setSizes([320, 240])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(splitter)

        self.refresh_roster()

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color: {TEXT_DIM}; font-weight: 600; padding: 2px;")
        return label

    # ------------------------------------------------------------------ #
    # roster
    # ------------------------------------------------------------------ #
    def refresh_roster(self) -> None:
        rows = self.session.roster()
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            rates = r["rates"]
            values = [
                r["operator"] or "?",
                _fmt_freq(r["freq_hz"]),
                r["mode"] or "—",
                str(rates[15]),
                str(rates[60]),
                str(r["total"]),  # total QSOs by this station across the whole log
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col >= 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if r["is_self"]:
                    item.setForeground(QColor(ACCENT))
                elif r["stale"]:
                    item.setForeground(QColor(TEXT_DIM))
                self._table.setItem(i, col, item)

        ops = self.session.operators()
        if ops != self._known_ops:
            self._known_ops = ops
            self._rebuild_recipients(ops)

    def _rebuild_recipients(self, ops: list[str]) -> None:
        current = self._recipient.currentData()
        self._recipient.blockSignals(True)
        self._recipient.clear()
        self._recipient.addItem("Everyone", "*")
        for op in ops:
            self._recipient.addItem(op, op)
        idx = self._recipient.findData(current)
        self._recipient.setCurrentIndex(idx if idx >= 0 else 0)
        self._recipient.blockSignals(False)

    # ------------------------------------------------------------------ #
    # chat
    # ------------------------------------------------------------------ #
    def append_chat(self, entry: dict) -> None:
        to_op = entry["to_op"]
        target = "all" if to_op in ("", "*") else to_op
        when = _short_time(entry["ts"])
        if entry["incoming"]:
            who = entry["from_op"]
            color = PEER
            arrow = "" if target == "all" else " →you"
            header = f"{who}{arrow}"
        else:
            color = MULT if target == "all" else AMBER
            header = f"you→{target}"
        text = entry["text"].replace("<", "&lt;").replace(">", "&gt;")
        self._chat_view.append(
            f"<span style='color:{TEXT_DIM}'>{when}</span> "
            f"<b style='color:{color}'>{header}:</b> {text}"
        )

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text or self.on_send_chat is None:
            return
        self.on_send_chat(self._recipient.currentData(), text)
        self._input.clear()
