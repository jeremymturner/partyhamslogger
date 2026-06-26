"""The WSJT-X info panel shown in place of the F-key bar in data modes.

When WSJT-X drives a digital mode, the function-key macro bar is meaningless
(WSJT-X handles transmit), so the main window hides it and shows this panel
instead: current WSJT-X mode/frequency, transmit state, the odd/even Tx period,
what we're sending, and — instead of a raw decode dump — a row of **buttons for
the stations currently calling us**. Each button shows the caller (plus their
ARRL section on Field Day); park activators (heard on "CQ POTA") are tinted
green. Clicking one asks the main window to answer that station.

Pure display — the main window pushes data in via :meth:`set_status` /
:meth:`set_callers` and wires :attr:`on_call`; this widget holds no app refs.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from partyhams.ui import style

_CALLER_BTN_W = 120  # fixed caller-button width (all buttons match)
_CALLER_ROW_H = 44  # fallback row height before a real button is measured
_CALLER_HSPACING = 4  # gap between buttons in a row
_CALLER_VSPACING = 7  # gap between the two rows (a touch more breathing room)
_CALLER_FALLBACK_COLS = 8  # used before the panel has a real width


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

        #: Set by the main window: on_call(callsign) — answer the clicked caller.
        self.on_call: Callable[[str], None] | None = None

        # Scrollable area of fixed-width caller buttons. They wrap to fill the
        # width; the area is sized for two rows and scrolls vertically beyond that.
        self._callers_host = QWidget()
        self._callers_grid = QGridLayout(self._callers_host)
        self._callers_grid.setContentsMargins(0, 2, 0, 2)
        self._callers_grid.setHorizontalSpacing(_CALLER_HSPACING)
        self._callers_grid.setVerticalSpacing(_CALLER_VSPACING)
        self._trailing_col = 0  # column holding the right-side stretch
        self._callers_scroll = QScrollArea()
        self._callers_scroll.setWidgetResizable(True)
        self._callers_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._callers_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Two rows tall (refined to the real button height in set_callers).
        self._callers_scroll.setMaximumHeight(2 * _CALLER_ROW_H + _CALLER_VSPACING + 4)
        self._callers_scroll.setWidget(self._callers_host)
        root.addWidget(self._callers_scroll)

        self._no_callers = QLabel("Waiting for callers…")
        self._no_callers.setStyleSheet(f"color: {style.TEXT_DIM};")
        self._callers_grid.addWidget(self._no_callers, 0, 0)

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

    def set_callers(self, callers: list[tuple[str, str, bool]]) -> None:
        """Rebuild the caller buttons. Each entry is ``(call, section, pota)``:
        ``section`` is shown under the call when present (Field Day); ``pota`` tints
        the button green (a park activator). Clicking a button fires ``on_call``."""
        # Clear existing buttons (and the placeholder). setParent(None) detaches
        # them from the display immediately; deleteLater frees them later.
        while self._callers_grid.count():
            item = self._callers_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._callers_grid.setColumnStretch(self._trailing_col, 0)  # reset old stretch
        if not callers:
            self._no_callers = QLabel("Waiting for callers…")
            self._no_callers.setStyleSheet(f"color: {style.TEXT_DIM};")
            self._callers_grid.addWidget(self._no_callers, 0, 0)
            return
        cols = self._caller_columns()
        row_h = _CALLER_ROW_H
        for i, (call, section, pota) in enumerate(callers):
            btn = QPushButton(f"{call}\n{section}" if section else call)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedWidth(_CALLER_BTN_W)  # uniform width; natural (themed) height
            btn.setToolTip(f"Answer {call}" + (f" — {section}" if section else ""))
            if pota:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {style.MULT}; "
                    f"color: {style.ON_ACCENT}; font-weight: 600; }}"
                )
            btn.clicked.connect(lambda _checked=False, c=call: self._call_clicked(c))
            self._callers_grid.addWidget(btn, i // cols, i % cols)
            row_h = max(row_h, btn.sizeHint().height())
        # Absorb leftover width on the right so buttons stay left-packed (not stretched).
        self._trailing_col = cols
        self._callers_grid.setColumnStretch(cols, 1)
        # Size to exactly two rows of the real button height; scroll beyond that.
        self._callers_scroll.setMaximumHeight(2 * row_h + _CALLER_VSPACING + 6)

    def _caller_columns(self) -> int:
        """How many fixed-width buttons fit across the current panel width."""
        avail = self._callers_scroll.viewport().width() - 4  # small safety margin
        if avail <= 0:
            return _CALLER_FALLBACK_COLS
        return max(1, avail // (_CALLER_BTN_W + _CALLER_HSPACING))

    def _call_clicked(self, call: str) -> None:
        if self.on_call is not None:
            self.on_call(call)

    def clear_callers(self) -> None:
        self.set_callers([])
