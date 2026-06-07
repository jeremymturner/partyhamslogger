"""Qt application bootstrap and a placeholder main window.

This is intentionally thin — the real entry window (keyboard-first QSO logging),
band map, log, and score windows come in Phase 1. For now it proves the app
launches cross-platform and surfaces what the headless core already knows
(registered contests and radio backends).
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

from partyhams import __version__
from partyhams.contest import available as available_contests
from partyhams.radio import available as available_backends


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"PartyHams Logger {__version__}")
        self.resize(640, 360)

        contests = ", ".join(name for _, name in available_contests()) or "none"
        backends = ", ".join(name for _, name in available_backends()) or "none"

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(_centered("<h1>PartyHams Logger</h1>"))
        layout.addWidget(_centered("Multi-station amateur radio contest logger"))
        layout.addWidget(_centered(f"<b>Contests:</b> {contests}"))
        layout.addWidget(_centered(f"<b>Radio backends:</b> {backends}"))
        layout.addWidget(_centered("<i>Phase 1 entry window coming soon — 73</i>"))
        self.setCentralWidget(central)


def _centered(text: str) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def run() -> int:
    """Launch the Qt application. Returns the process exit code."""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
