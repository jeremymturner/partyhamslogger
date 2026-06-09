"""Application theme.

A single dark stylesheet (QSS) applied app-wide. Dark by default — it's what
most contest ops want for a 24-hour Field Day — with a cyan primary accent and
amber for score highlights. Using the Fusion base style makes the QSS render
consistently across macOS/Windows/Linux.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

ICON_PATH = Path(__file__).parent / "assets" / "icon.svg"

# Palette
BG = "#1f2128"
BG_PANEL = "#23262e"
BG_INPUT = "#2a2d36"
BG_DARK = "#14161c"
BORDER = "#31343d"
TEXT = "#e7e9ee"
TEXT_DIM = "#aeb6c4"
ACCENT = "#4aa8d8"  # cyan — primary
ACCENT_HI = "#5ab9e9"
AMBER = "#e0a83a"  # score highlight
PEER = "#5aa9e6"  # QSOs from a networked peer
DUPE = "#ff6b6b"
MULT = "#5fd38d"  # new-multiplier highlight (green)
MULT_BG = "#1d3326"  # field tint behind a new multiplier

APP_QSS = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-size: 13px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QMainWindow, QDialog {{ background-color: {BG}; }}
QLabel {{ color: {TEXT_DIM}; background: transparent; }}

/* ESM mode indicator — an amber pill shown while Enter-sends-messages is on. */
QLabel#esmBadge {{
    background-color: {AMBER};
    color: #1f1606;
    border-radius: 5px;
    padding: 4px 10px;
    font-weight: 700;
}}

QLabel#scoreBar {{
    background-color: {BG_DARK};
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
    padding: 9px 14px;
    font-size: 15px;
}}

QLineEdit, QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 7px;
    min-height: 22px;
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
    background-color: #30343f;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}

QPushButton {{
    background-color: {ACCENT};
    color: #0c1116;
    border: none;
    border-radius: 5px;
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton:hover {{ background-color: {ACCENT_HI}; }}
QPushButton:pressed {{ background-color: #3a8fbf; }}
QPushButton:default {{ background-color: {ACCENT}; }}

/* Function-key macro bar — two lines (Fn + macro label), so it needs
   more vertical room and a legible disabled state for empty slots. */
QPushButton#fkey {{
    background-color: {ACCENT};
    color: #0c1116;
    border: none;
    border-radius: 5px;
    padding: 4px 6px;
    font-weight: 700;
    font-size: 12px;
}}
QPushButton#fkey:hover {{ background-color: {ACCENT_HI}; }}
QPushButton#fkey:pressed {{ background-color: #3a8fbf; }}
QPushButton#fkey:disabled {{
    background-color: #2f5d72;  /* dimmed cyan — clearly inactive, label still legible */
    color: #acc2cf;
}}

QTableWidget {{
    background-color: {BG_PANEL};
    alternate-background-color: #272a33;
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 5px;
}}
QHeaderView::section {{
    background-color: #2c2f38;
    color: {TEXT_DIM};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid {BORDER};
    font-weight: 600;
}}
QTableWidget::item {{ padding: 3px 6px; }}
QTableWidget::item:selected {{ background-color: {ACCENT}; color: #ffffff; }}

QStatusBar {{ background-color: {BG_DARK}; color: {TEXT_DIM}; }}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: {BG_PANEL}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #3a3e4a; border-radius: 6px; min-height: 26px;
}}
QScrollBar::handle:vertical:hover {{ background: #4a4f5e; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the PartyHams dark theme to the whole application."""
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)


def app_icon() -> QIcon:
    """The application icon (the cyan/amber RF broadcast mark)."""
    return QIcon(str(ICON_PATH))
