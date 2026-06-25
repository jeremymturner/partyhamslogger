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

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
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
#: Relative column widths — the roster scales these proportionally to the dock
#: width (rather than dumping all slack into the last column).
_COL_WEIGHTS = (72, 62, 44, 44, 44, 44)


class _RosterTable(QTableWidget):
    """Stations roster whose columns grow and shrink proportionally with the dock,
    so no single column (e.g. "All") balloons to absorb the slack."""

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        avail = self.viewport().width()
        if avail <= 0 or self.columnCount() != len(_COL_WEIGHTS):
            return
        total = sum(_COL_WEIGHTS)
        used = 0
        for col in range(self.columnCount() - 1):
            w = round(_COL_WEIGHTS[col] / total * avail)
            self.setColumnWidth(col, w)
            used += w
        self.setColumnWidth(self.columnCount() - 1, max(0, avail - used))  # exact fill


def _fmt_freq(freq_hz: int) -> str:
    return f"{freq_hz / 1_000_000:.3f}" if freq_hz else "—"


def _fmt_mode(mode: str, ft_tx_even: int) -> str:
    """Mode for the roster, tagging the FT8/FT4 Tx sequence: ``FT8e`` (even) /
    ``FT8o`` (odd). ``ft_tx_even`` is 1 even, 0 odd, -1 unknown."""
    m = (mode or "").upper()
    if m in ("FT8", "FT4") and ft_tx_even in (0, 1):
        return f"{m}{'e' if ft_tx_even == 1 else 'o'}"
    return mode or "—"


#: Marker shown on a peer's Op cell once we haven't heard a presence beat from
#: it in over two minutes (see ``session.SILENT_AFTER_S``).
SILENT_ICON = "⚠"


def _fmt_silence(secs: float | None) -> str:
    """Humanize seconds-since-last-heard for the silent-peer tooltip."""
    if secs is None:
        return "no presence received yet"
    total = int(secs)
    if total < 60:
        return f"{total}s ago"
    mins, rem = divmod(total, 60)
    if mins < 60:
        return f"{mins}m {rem}s ago"
    hrs, mins = divmod(mins, 60)
    return f"{hrs}h {mins}m ago"


def _radio_line(row: dict | None) -> str:
    """One-line summary of a station's power / SWR / FT8-FT4 Tx sequence.

    Power and SWR show ``—`` when unknown (0 = unknown on the wire). The Tx
    sequence (ODD/EVEN) is only shown for FT8/FT4 and only when known.
    """
    if row is None:
        return ""
    power = row.get("power_w", 0.0) or 0.0
    swr = row.get("swr", 0.0) or 0.0
    power_text = f"{power:.0f} W" if power > 0 else "—"
    swr_text = f"{swr:.1f}:1" if swr > 0 else "—"
    parts = [f"Power: {power_text}", f"SWR: {swr_text}"]
    if (row.get("mode") or "").strip().upper() in ("FT8", "FT4"):
        even = int(row.get("ft_tx_even", -1))
        tx_text = "EVEN" if even == 1 else "ODD" if even == 0 else "—"
        parts.append(f"Tx: {tx_text}")
    return "    ".join(parts)


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
        # Tab-completion state for the chat input (roster callsigns).
        self._cc_matches: list[str] = []
        self._cc_index = 0
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
        self._table = _RosterTable(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setShowGrid(False)
        # Columns scale proportionally with the dock width (see _RosterTable); none
        # absorbs the slack on its own. Fixed mode so that scaling isn't overridden.
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setMinimumSectionSize(24)
        self._table.setStyleSheet(
            "QHeaderView::section { padding: 4px 2px; }QTableWidget::item { padding: 2px 4px; }"
        )
        # Click a row to drill into that station's stats.
        self._table.cellClicked.connect(self._on_row_clicked)
        self._table.setCursor(Qt.CursorShape.PointingHandCursor)

        # Stack: page 0 = roster table, page 1 = the per-station stats view. The
        # stats view is scrollable so its tall content doesn't force a big minimum
        # height on the roster pane — that lets the chat be dragged up to ~75%.
        self._stack = QStackedWidget()
        self._stack.addWidget(self._table)
        stats_scroll = QScrollArea()
        stats_scroll.setWidgetResizable(True)
        stats_scroll.setFrameShape(QFrame.Shape.NoFrame)
        stats_scroll.setWidget(self._build_stats_view())
        self._stack.addWidget(stats_scroll)
        sv.addWidget(self._stack)
        self._roster_rows: list[dict] = []
        self._stats_station_id: str | None = None
        stations.setMinimumHeight(110)  # roster floor; below this it collapses (chat 100%)
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

        # Chat is broadcast-only: everyone talks to everyone, tagged by op call.
        self._input = QLineEdit()
        self._input.setPlaceholderText("Message everyone… (Enter to send, Tab completes calls)")
        self._input.returnPressed.connect(self._send)
        self._input.installEventFilter(self)  # Tab -> callsign completion
        cv.addWidget(self._input)
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
        # Power / SWR / (for FT8/FT4) Tx sequence — filled in by _render_stats.
        self._stats_radio = QLabel()
        self._stats_radio.setWordWrap(True)
        v.addWidget(self._stats_radio)
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
        self._stats_radio.setText(_radio_line(row))
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
            silent = r.get("silent")
            gone = r.get("gone")
            op = r["operator"] or "?"
            # Op cell marker: silent (no presence >2m) takes precedence over the
            # clock-drift marker, since a vanished station's drift is moot.
            if silent:
                op_cell = f"{SILENT_ICON} {op}"
            elif clock_off:
                op_cell = f"⏰ {op}"
            else:
                op_cell = op
            values = [
                op_cell,
                _fmt_freq(r["freq_hz"]),
                _fmt_mode(r["mode"], r["ft_tx_even"]),
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
                if col == 0 and gone:
                    # Struck through after five minutes of silence — almost
                    # certainly dropped off the network.
                    font = item.font()
                    font.setStrikeOut(True)
                    item.setFont(font)
                    item.setForeground(QColor(style.AMBER))
                    item.setToolTip(
                        f"No update from this station in over 5 minutes "
                        f"(last heard {_fmt_silence(r.get('silent_secs'))}) — "
                        "it has almost certainly gone offline."
                    )
                elif col == 0 and silent:
                    item.setForeground(QColor(style.AMBER))
                    item.setToolTip(
                        f"No update from this station in over 2 minutes "
                        f"(last heard {_fmt_silence(r.get('silent_secs'))}) — "
                        "it may have gone offline."
                    )
                elif col == 0 and clock_off:
                    offset = r.get("clock_offset") or 0.0
                    item.setForeground(QColor(style.AMBER))
                    item.setToolTip(
                        f"Clock off by {offset:+.1f}s — check time sync "
                        "(offset includes network latency)"
                    )
                self._table.setItem(i, col, item)

    # ------------------------------------------------------------------ #
    # chat
    # ------------------------------------------------------------------ #
    def append_chat(self, entry: dict) -> None:
        when = _short_time(entry["ts"])
        who = entry["from_op"]  # the op callsign is the nick
        color = style.PEER if entry["incoming"] else style.MULT
        text = entry["text"].replace("<", "&lt;").replace(">", "&gt;")
        self._chat_view.append(
            f"<span style='color:{style.TEXT_DIM}'>{when}</span> "
            f"<b style='color:{color}'>{who}:</b> {text}"
        )

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text or self.on_send_chat is None:
            return
        self.on_send_chat("*", text)  # broadcast to everyone
        self._input.clear()

    # ------------------------------------------------------------------ #
    # chat callsign completion (Tab)
    # ------------------------------------------------------------------ #
    def eventFilter(self, obj: object, event: QEvent) -> bool:
        if (
            obj is self._input
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Tab
        ):
            self._complete_callsign()
            return True  # consume Tab (don't move focus / insert a tab)
        return super().eventFilter(obj, event)

    def _roster_calls(self) -> list[str]:
        """Distinct op callsigns currently on the roster (for chat completion)."""
        calls: list[str] = []
        for r in self._roster_rows:
            op = (r.get("operator") or "").strip().upper()
            if op and op not in calls:
                calls.append(op)
        return sorted(calls)

    def _complete_callsign(self) -> None:
        """Tab-complete the last word in the chat box against roster callsigns;
        repeated Tab cycles through all matches for that prefix."""
        text = self._input.text()
        frag = text.rpartition(" ")[2]  # the word being typed
        head = text[: len(text) - len(frag)]
        # Continue the current cycle if the box still shows the last completion.
        if self._cc_matches and frag == self._cc_matches[self._cc_index]:
            self._cc_index = (self._cc_index + 1) % len(self._cc_matches)
        else:
            self._cc_matches = [c for c in self._roster_calls() if c.startswith(frag.upper())]
            self._cc_index = 0
            if not self._cc_matches:
                return
        self._input.setText(head + self._cc_matches[self._cc_index])
        self._input.setCursorPosition(len(self._input.text()))

    def _request_sync(self) -> None:
        if self.on_request_sync is not None:
            self.on_request_sync()
