"""The WSJT-X info panel shown in place of the F-key bar in data modes.

When WSJT-X drives a digital mode, the function-key macro bar is meaningless
(WSJT-X handles transmit), so the main window hides it and shows this panel
instead: current WSJT-X mode/frequency, transmit state, the odd/even Tx period,
what we're sending, and a rolling list of recent decodes.

Pure display — the main window pushes data in via :meth:`set_status` /
:meth:`add_decode`; this widget holds no app/session references.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from partyhams.ui import style

MAX_DECODES = 12  # rolling decode lines kept in the list


def _format_freq(hz: int) -> str:
    if hz <= 0:
        return "—"
    return f"{hz / 1_000_000:.6f} MHz"


class WsjtxPanel(QWidget):
    """Compact WSJT-X status + recent-decodes view."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("wsjtxPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 2, 4, 2)
        root.setSpacing(2)

        header = QHBoxLayout()
        self._title = QLabel("WSJT-X")
        self._title.setStyleSheet(f"font-weight: 700; color: {style.ACCENT};")
        header.addWidget(self._title)
        self._mode = QLabel()
        header.addWidget(self._mode)
        header.addStretch(1)
        self._tx_state = QLabel()
        header.addWidget(self._tx_state)
        self._period = QLabel()
        header.addWidget(self._period)
        root.addLayout(header)

        self._sending = QLabel()
        self._sending.setStyleSheet(f"color: {style.AMBER};")
        root.addWidget(self._sending)

        self._decodes = QListWidget()
        self._decodes.setMaximumHeight(90)
        self._decodes.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        root.addWidget(self._decodes)

    def set_status(
        self,
        *,
        mode: str,
        dial_freq: int,
        tx_enabled: bool,
        transmitting: bool,
        tx_period_odd: bool | None,
        sending: str,
    ) -> None:
        """Update the header/state lines from a WSJT-X Status message."""
        self._mode.setText(f"{mode or '?'} · {_format_freq(dial_freq)}")
        if transmitting:
            self._tx_state.setText("TRANSMITTING")
            self._tx_state.setStyleSheet(f"color: {style.DUPE}; font-weight: 700;")
        elif tx_enabled:
            self._tx_state.setText("Tx enabled")
            self._tx_state.setStyleSheet(f"color: {style.MULT};")
        else:
            self._tx_state.setText("Tx off")
            self._tx_state.setStyleSheet(f"color: {style.TEXT_DIM};")
        if tx_period_odd is None:
            self._period.setText("")
        else:
            self._period.setText(f"Tx {'ODD' if tx_period_odd else 'EVEN'}")
            self._period.setStyleSheet(f"color: {style.TEXT_DIM};")
        self._sending.setText(f"Sending: {sending}" if sending else "")

    def add_decode(self, text: str) -> None:
        """Append a decode line, trimming to the most recent ``MAX_DECODES``."""
        self._decodes.addItem(text)
        while self._decodes.count() > MAX_DECODES:
            self._decodes.takeItem(0)
        self._decodes.scrollToBottom()

    def clear_decodes(self) -> None:
        self._decodes.clear()
