"""Application theming.

A palette-driven QSS applied app-wide on the Fusion base style (which makes the
stylesheet render consistently across macOS/Windows/Linux). Six built-in themes —
three dark, three light — are selectable at runtime, and the app defaults to a
dark or light theme to match the OS.

UI modules read the active palette through this module's attributes (e.g.
``style.ACCENT``) rather than copying them at import, so :func:`apply_theme`
re-colors the whole app live.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

ICON_PATH = Path(__file__).parent / "assets" / "icon.svg"

#: Base UI font, applied app-wide and orthogonal to the colour palette. The
#: size feeds the QSS base ``font-size`` (so the whole UI scales); the family
#: is set via ``QApplication.setFont``. ``None`` family means the Qt default.
DEFAULT_FONT_SIZE = 13
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 28
_font_family: str | None = None
_font_size: int = DEFAULT_FONT_SIZE


def clamp_font_size(size: int) -> int:
    """Clamp a requested point size to the supported range (8..28)."""
    return max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(size)))


@dataclass(frozen=True)
class Palette:
    """A complete color scheme. ``dark`` only affects the system-default pick."""

    name: str
    dark: bool
    bg: str
    bg_panel: str
    bg_input: str
    bg_dark: str
    bg_alt: str  # table alternate-row tint
    border: str
    text: str
    text_dim: str
    accent: str
    accent_hi: str
    accent_lo: str  # pressed accent
    on_accent: str  # text drawn on accent fills (buttons, selection)
    amber: str
    peer: str
    dupe: str
    mult: str
    mult_bg: str
    input_focus: str  # input background when focused


# --- Dark themes ---------------------------------------------------------- #
_MIDNIGHT = Palette(
    name="Midnight (cyan)", dark=True,
    bg="#1f2128", bg_panel="#23262e", bg_input="#2a2d36", bg_dark="#14161c",
    bg_alt="#272a33", border="#31343d", text="#e7e9ee", text_dim="#aeb6c4",
    accent="#4aa8d8", accent_hi="#5ab9e9", accent_lo="#3a8fbf", on_accent="#0c1116",
    amber="#e0a83a", peer="#5aa9e6", dupe="#ff6b6b", mult="#5fd38d", mult_bg="#1d3326",
    input_focus="#30343f",
)
_FOREST = Palette(
    name="Forest (green)", dark=True,
    bg="#16201b", bg_panel="#1c2922", bg_input="#22302a", bg_dark="#0f1813",
    bg_alt="#1f2d26", border="#2c3b32", text="#e6efe8", text_dim="#a9bcae",
    accent="#4cc38a", accent_hi="#5fd49b", accent_lo="#3aa472", on_accent="#0a140e",
    amber="#e0a83a", peer="#6fb3e0", dupe="#ff6b6b", mult="#7fd6ff", mult_bg="#10262e",
    input_focus="#283a31",
)
_VIOLET = Palette(
    name="Violet (purple)", dark=True,
    bg="#1e1b2e", bg_panel="#262238", bg_input="#2d2942", bg_dark="#15131f",
    bg_alt="#2a2640", border="#3a3550", text="#ece9f5", text_dim="#b3aecb",
    accent="#a78bfa", accent_hi="#b9a4fb", accent_lo="#8b6ee0", on_accent="#14101f",
    amber="#f0b860", peer="#8b9cf0", dupe="#ff7b7b", mult="#5fd38d", mult_bg="#1f2b3a",
    input_focus="#332e4c",
)

# --- Light themes --------------------------------------------------------- #
_DAYLIGHT = Palette(
    name="Daylight (cyan)", dark=False,
    bg="#f4f6fa", bg_panel="#ffffff", bg_input="#ffffff", bg_dark="#e9edf3",
    bg_alt="#eef2f7", border="#cdd5e0", text="#1b2330", text_dim="#566377",
    accent="#1f7bb6", accent_hi="#2a8fce", accent_lo="#176394", on_accent="#ffffff",
    amber="#b9791a", peer="#2b6fb0", dupe="#c0392b", mult="#1f9d57", mult_bg="#dff3e6",
    input_focus="#eef4fb",
)
_SAND = Palette(
    name="Sand (warm)", dark=False,
    bg="#f7f3ec", bg_panel="#fffdf9", bg_input="#fffdf9", bg_dark="#ece4d6",
    bg_alt="#f1ebe0", border="#d8cdba", text="#2a2620", text_dim="#6b6353",
    accent="#c2722a", accent_hi="#d6843a", accent_lo="#a35f20", on_accent="#ffffff",
    amber="#9a6b12", peer="#3f7fae", dupe="#c0392b", mult="#3d9a5a", mult_bg="#e4f0e2",
    input_focus="#fbf6ee",
)
_LAVENDER = Palette(
    name="Lavender (violet)", dark=False,
    bg="#f6f4fb", bg_panel="#ffffff", bg_input="#ffffff", bg_dark="#ebe7f5",
    bg_alt="#f0ecf8", border="#d3cce5", text="#241f33", text_dim="#5d5677",
    accent="#7c4fd0", accent_hi="#8f63e0", accent_lo="#653cb0", on_accent="#ffffff",
    amber="#b07d1a", peer="#5b6fd0", dupe="#c0392b", mult="#1f9d57", mult_bg="#e6e0f5",
    input_focus="#f3effb",
)

THEMES: dict[str, Palette] = {
    p.name: p for p in (_MIDNIGHT, _FOREST, _VIOLET, _DAYLIGHT, _SAND, _LAVENDER)
}
DEFAULT_DARK = _MIDNIGHT.name
DEFAULT_LIGHT = _DAYLIGHT.name

# Module-level color constants — reassigned by apply_theme(); UI reads them live
# via `style.ACCENT` etc. Initialised to the default dark theme.
BG = BG_PANEL = BG_INPUT = BG_DARK = BORDER = ""
TEXT = TEXT_DIM = ACCENT = ACCENT_HI = AMBER = PEER = DUPE = MULT = MULT_BG = ON_ACCENT = ""
_active: Palette = _MIDNIGHT


def build_qss(p: Palette) -> str:
    """Render the app-wide stylesheet for a palette (using the active font size)."""
    return f"""
QWidget {{
    background-color: {p.bg};
    color: {p.text};
    font-size: {_font_size}px;
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QMainWindow, QDialog {{ background-color: {p.bg}; }}
QLabel {{ color: {p.text_dim}; background: transparent; }}

QLabel#esmBadge {{
    background-color: {p.amber};
    color: {p.bg_dark};
    border-radius: 5px;
    padding: 4px 10px;
    font-weight: 700;
}}

QLabel#scoreBar {{
    background-color: {p.bg_dark};
    color: {p.text};
    border-bottom: 2px solid {p.accent};
    padding: 9px 14px;
    font-size: 15px;
}}

QLineEdit, QComboBox {{
    background-color: {p.bg_input};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 5px;
    padding: 5px 7px;
    min-height: 22px;
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid {p.accent};
    background-color: {p.input_focus};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {p.bg_input};
    color: {p.text};
    border: 1px solid {p.border};
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}

QPushButton {{
    background-color: {p.accent};
    color: {p.on_accent};
    border: none;
    border-radius: 5px;
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton:hover {{ background-color: {p.accent_hi}; }}
QPushButton:pressed {{ background-color: {p.accent_lo}; }}
QPushButton:default {{ background-color: {p.accent}; }}

QPushButton#fkey {{
    background-color: {p.accent};
    color: {p.on_accent};
    border: none;
    border-radius: 5px;
    padding: 4px 6px;
    font-weight: 700;
    font-size: 12px;
}}
QPushButton#fkey:hover {{ background-color: {p.accent_hi}; }}
QPushButton#fkey:pressed {{ background-color: {p.accent_lo}; }}
QPushButton#fkey:disabled {{
    background-color: {p.bg_input};
    color: {p.text_dim};
    border: 1px solid {p.border};
}}

QTableWidget {{
    background-color: {p.bg_panel};
    alternate-background-color: {p.bg_alt};
    gridline-color: {p.border};
    border: 1px solid {p.border};
    border-radius: 5px;
}}
QHeaderView::section {{
    background-color: {p.bg_alt};
    color: {p.text_dim};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid {p.border};
    font-weight: 600;
}}
QTableWidget::item {{ padding: 3px 6px; }}
QTableWidget::item:selected {{ background-color: {p.accent}; color: {p.on_accent}; }}

QStatusBar {{
    background-color: {p.bg_dark};
    color: {p.text_dim};
    min-height: 28px;
    padding: 2px 10px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ padding: 2px 4px; }}

QScrollBar:vertical {{ background: {p.bg_panel}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {p.border}; border-radius: 6px; min-height: 26px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.accent_lo}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def theme_names() -> list[tuple[str, bool]]:
    """All themes as ``(name, is_dark)``, dark first."""
    return [(p.name, p.dark) for p in THEMES.values()]


def active_name() -> str:
    return _active.name


def active_font() -> tuple[str | None, int]:
    """The active base font as ``(family, size)`` (family None => Qt default)."""
    return _font_family, _font_size


def _apply_app_font(app: QApplication) -> None:
    """Push the active family onto the QApplication font (size lives in QSS)."""
    font = app.font()
    if _font_family:
        font.setFamily(_font_family)
    app.setFont(font)


def apply_font(app: QApplication, family: str | None, size: int) -> tuple[str | None, int]:
    """Set the app-wide base font, re-rendering the stylesheet. Size clamped 8..28."""
    global _font_family, _font_size
    _font_family = family or None
    _font_size = clamp_font_size(size)
    _apply_app_font(app)
    app.setStyleSheet(build_qss(_active))
    return _font_family, _font_size


def system_is_dark(app: QApplication) -> bool:
    """Best-effort OS dark-mode detection."""
    try:
        from PySide6.QtCore import Qt

        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except (AttributeError, ImportError):
        pass
    # Fallback: infer from the default window color's lightness.
    from PySide6.QtGui import QPalette

    return QPalette().color(QPalette.ColorRole.Window).lightness() < 128


def default_theme_name(app: QApplication) -> str:
    return DEFAULT_DARK if system_is_dark(app) else DEFAULT_LIGHT


def apply_theme(app: QApplication, name: str | None = None) -> str:
    """Apply a theme by name (or the system-matching default). Returns its name."""
    global _active, BG, BG_PANEL, BG_INPUT, BG_DARK, BORDER, ON_ACCENT
    global TEXT, TEXT_DIM, ACCENT, ACCENT_HI, AMBER, PEER, DUPE, MULT, MULT_BG
    palette = THEMES.get(name or "") or THEMES[default_theme_name(app)]
    _active = palette
    BG, BG_PANEL, BG_INPUT, BG_DARK, BORDER = (
        palette.bg, palette.bg_panel, palette.bg_input, palette.bg_dark, palette.border
    )
    TEXT, TEXT_DIM = palette.text, palette.text_dim
    ACCENT, ACCENT_HI, AMBER = palette.accent, palette.accent_hi, palette.amber
    PEER, DUPE, MULT, MULT_BG = palette.peer, palette.dupe, palette.mult, palette.mult_bg
    ON_ACCENT = palette.on_accent
    app.setStyle("Fusion")
    _apply_app_font(app)  # keep the user's font across theme switches
    app.setStyleSheet(build_qss(palette))
    return palette.name


def app_icon() -> QIcon:
    """The application icon (the cyan/amber RF broadcast mark)."""
    return QIcon(str(ICON_PATH))


# Initialise the module constants to the default dark theme at import so any
# early readers (before apply_theme runs) get sensible values.
_MIDNIGHT_INIT = _MIDNIGHT
BG, BG_PANEL, BG_INPUT, BG_DARK, BORDER = (
    _MIDNIGHT.bg, _MIDNIGHT.bg_panel, _MIDNIGHT.bg_input, _MIDNIGHT.bg_dark, _MIDNIGHT.border
)
TEXT, TEXT_DIM = _MIDNIGHT.text, _MIDNIGHT.text_dim
ACCENT, ACCENT_HI, AMBER = _MIDNIGHT.accent, _MIDNIGHT.accent_hi, _MIDNIGHT.amber
PEER, DUPE, MULT, MULT_BG = _MIDNIGHT.peer, _MIDNIGHT.dupe, _MIDNIGHT.mult, _MIDNIGHT.mult_bg
ON_ACCENT = _MIDNIGHT.on_accent
