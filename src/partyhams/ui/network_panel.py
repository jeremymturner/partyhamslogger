"""The network side panel: a station roster (top) and a chat box (bottom).

Top: every station we've detected — operator, frequency, mode, QSO counts in the
last 15 / 60 minutes, and their all-time total in this log (our own row first).
Click a station to drill into a per-station stats view (hour-by-hour histogram
and a by-mode breakdown, with a Back button). Bottom: a chat where a message
goes to everyone by default, or to one operator.

Data comes from the :class:`~partyhams.app.session.LogSession`; sending a chat
calls :attr:`on_send_chat` (wired by the main window to post + broadcast).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from partyhams.app.session import LogSession
from partyhams.ui import style

_COLUMNS = ["Op", "Freq", "Mode", "15m", "60m", "All"]


def _fmt_freq(freq_hz: int) -> str:
    return f"{freq_hz / 1_000_000:.3f}" if freq_hz else "—"


class _BarChart(QWidget):
    """A tiny self-painted vertical bar chart (no extra chart dependency)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels: list[str] = []
        self._values: list[int] = []
        self.setMinimumHeight(110)

    def set_data(self, labels: list[str], values: list[int]) -> None:
        self._labels = labels
        self._values = values
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        w, h = self.width(), self.height()
        pad_top, pad_bottom = 14, 16
        if not self._values or max(self._values) == 0:
            painter.setPen(QColor(style.TEXT_DIM))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No QSOs yet")
            painter.end()
            return
        n = len(self._values)
        maxv = max(self._values)
        gap = 2
        bar_w = max(1.0, (w - (n + 1) * gap) / n)
        accent, dim = QColor(style.ACCENT), QColor(style.TEXT_DIM)
        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)
        plot_h = h - pad_top - pad_bottom
        for i, (label, val) in enumerate(zip(self._labels, self._values, strict=False)):
            x = gap + i * (bar_w + gap)
            bar_h = plot_h * (val / maxv)
            y = h - pad_bottom - bar_h
            painter.fillRect(QRect(int(x), int(y), int(bar_w), int(bar_h)), accent)
            painter.setPen(dim)
            if val:
                painter.drawText(
                    QRect(int(x) - 3, int(y) - pad_top, int(bar_w) + 6, pad_top),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                    str(val),
                )
            if label:
                painter.drawText(
                    QRect(int(x) - 3, h - pad_bottom, int(bar_w) + 6, pad_bottom),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    label,
                )
        painter.end()


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
        #: Wired by the main window: ask every peer for their full log.
        self.on_request_sync: Callable[[], None] | None = None
        self._known_ops: list[str] = []
        self.setMinimumWidth(200)  # generous lower bound; drag the dock edge to resize

        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- stations ---
        stations = QWidget()
        sv = QVBoxLayout(stations)
        sv.setContentsMargins(6, 6, 6, 2)
        header = QHBoxLayout()
        self._station_label = self._section_label("Stations")
        header.addWidget(self._station_label, stretch=1)
        self._sync_btn = QPushButton("Sync all logs")
        self._sync_btn.setToolTip("Ask every station to send their full log so you have a copy")
        self._sync_btn.clicked.connect(self._request_sync)
        header.addWidget(self._sync_btn)
        sv.addLayout(header)
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setShowGrid(False)
        # Columns are user-resizable: drag a column border to widen/narrow it, and
        # drag the dock's edge for more room (the last column takes up the slack).
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(24)
        self._table.setStyleSheet(
            "QHeaderView::section { padding: 4px 2px; }QTableWidget::item { padding: 2px 4px; }"
        )
        for col, width in enumerate((72, 62, 44, 38, 38, 38)):
            self._table.setColumnWidth(col, width)
        # Click a row to drill into that station's stats.
        self._table.cellClicked.connect(self._on_row_clicked)
        self._table.setCursor(Qt.CursorShape.PointingHandCursor)

        # Stack: page 0 = roster table, page 1 = the per-station stats view.
        self._stack = QStackedWidget()
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._build_stats_view())
        sv.addWidget(self._stack)
        self._roster_rows: list[dict] = []
        self._stats_station_id: str | None = None
        splitter.addWidget(stations)

        # --- chat ---
        chat = QWidget()
        cv = QVBoxLayout(chat)
        cv.setContentsMargins(6, 2, 6, 6)
        self._chat_label = self._section_label("Chat")
        cv.addWidget(self._chat_label)
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
        label.setStyleSheet(f"color: {style.TEXT_DIM}; font-weight: 600; padding: 2px;")
        return label

    def restyle(self) -> None:
        """Re-apply palette colors after a live theme change."""
        for label in (self._station_label, self._chat_label):
            label.setStyleSheet(f"color: {style.TEXT_DIM}; font-weight: 600; padding: 2px;")
        self._hour_chart.update()
        self._mode_chart.update()
        self.refresh_roster()  # re-colors the self/stale row foregrounds

    # ------------------------------------------------------------------ #
    # per-station stats (drill-down)
    # ------------------------------------------------------------------ #
    def _build_stats_view(self) -> QWidget:
        view = QWidget()
        v = QVBoxLayout(view)
        v.setContentsMargins(0, 0, 0, 0)
        back = QPushButton("← Back to stations")
        back.clicked.connect(self._show_roster)
        v.addWidget(back)
        self._stats_title = QLabel()
        self._stats_title.setStyleSheet(f"color: {style.ACCENT}; font-weight: 700;")
        v.addWidget(self._stats_title)
        self._stats_summary = QLabel()
        self._stats_summary.setWordWrap(True)
        v.addWidget(self._stats_summary)
        v.addWidget(self._section_label("QSOs per hour (UTC)"))
        self._hour_chart = _BarChart()
        v.addWidget(self._hour_chart)
        v.addWidget(self._section_label("QSOs by mode"))
        self._mode_chart = _BarChart()
        v.addWidget(self._mode_chart)
        v.addStretch(1)
        return view

    def _on_row_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._roster_rows):
            self._stats_station_id = self._roster_rows[row]["station_id"]
            self._render_stats()
            self._stack.setCurrentIndex(1)

    def _show_roster(self) -> None:
        self._stats_station_id = None
        self._stack.setCurrentIndex(0)

    def _render_stats(self) -> None:
        sid = self._stats_station_id
        if sid is None:
            return
        row = next((r for r in self._roster_rows if r["station_id"] == sid), None)
        who = (row["operator"] or row["call"] or "Station") if row else "Station"
        stats = self.session.station_stats(sid)
        self._stats_title.setText(who)
        if stats["total"] and stats["first"] and stats["last"]:
            span = f"{stats['first'].strftime('%H:%M')}–{stats['last'].strftime('%H:%M')} UTC"
            self._stats_summary.setText(f"{stats['total']} QSOs  ·  {span}")
        else:
            self._stats_summary.setText("No QSOs logged yet")
        # Hour histogram: label every third hour to avoid clutter.
        hour_labels = [str(h) if h % 3 == 0 else "" for h in range(24)]
        self._hour_chart.set_data(hour_labels, stats["by_hour"])
        modes = sorted(stats["by_mode"].items(), key=lambda kv: kv[1], reverse=True)
        self._mode_chart.set_data([m for m, _ in modes], [c for _, c in modes])

    # ------------------------------------------------------------------ #
    # roster
    # ------------------------------------------------------------------ #
    def refresh_roster(self) -> None:
        rows = self.session.roster()
        self._roster_rows = rows
        if self._stats_station_id is not None:
            self._render_stats()  # keep the open drill-down live
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            rates = r["rates"]
            clock_off = r.get("clock_off")
            op = r["operator"] or "?"
            values = [
                f"⏰ {op}" if clock_off else op,  # clock-drift marker on the Op cell
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
                    item.setForeground(QColor(style.ACCENT))
                elif r["stale"]:
                    item.setForeground(QColor(style.TEXT_DIM))
                if col == 0 and clock_off:
                    offset = r.get("clock_offset") or 0.0
                    item.setForeground(QColor(style.AMBER))
                    item.setToolTip(
                        f"Clock off by {offset:+.1f}s — check time sync "
                        "(offset includes network latency)"
                    )
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
            color = style.PEER
            arrow = "" if target == "all" else " →you"
            header = f"{who}{arrow}"
        else:
            color = style.MULT if target == "all" else style.AMBER
            header = f"you→{target}"
        text = entry["text"].replace("<", "&lt;").replace(">", "&gt;")
        self._chat_view.append(
            f"<span style='color:{style.TEXT_DIM}'>{when}</span> "
            f"<b style='color:{color}'>{header}:</b> {text}"
        )

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text or self.on_send_chat is None:
            return
        self.on_send_chat(self._recipient.currentData(), text)
        self._input.clear()

    def _request_sync(self) -> None:
        if self.on_request_sync is not None:
            self.on_request_sync()
