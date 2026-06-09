"""Keyboard-shortcut catalog + the "Keyboard Shortcuts" help dialog.

Single source of truth: the same key specs are assigned to menu actions (so each
shortcut shows next to its menu item) and rendered in the help dialog, so the two
can never drift. Specs use the portable "Ctrl+..." form; Qt maps Ctrl→⌘ on macOS
and ``fmt_keys`` renders them in the platform-native notation.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from partyhams.ui import style

# Menu/command shortcuts. These constants are imported by the main window and
# assigned to the matching QActions.
NEW_LOG = "Ctrl+N"
OPEN_LOG = "Ctrl+O"
EXPORT_ADIF = "Ctrl+E"
EXPORT_CABRILLO = "Ctrl+Shift+E"
SELECT_RADIO = "Ctrl+R"
EDIT_MACROS = "Ctrl+M"
TOGGLE_ESM = "Ctrl+Shift+M"
SECTIONS = "Ctrl+Shift+S"
TOGGLE_NETWORK = "Ctrl+Shift+N"
SHORTCUTS = "Ctrl+/"

# (keyspec, description) for the help dialog's "Commands" group — order matters.
COMMANDS: list[tuple[str, str]] = [
    (NEW_LOG, "New log"),
    (OPEN_LOG, "Open log…"),
    (EXPORT_ADIF, "Export ADIF…"),
    (EXPORT_CABRILLO, "Export Cabrillo…"),
    (SELECT_RADIO, "Select radio…"),
    (EDIT_MACROS, "Edit macros…"),
    (TOGGLE_ESM, "Toggle ESM (Enter sends messages)"),
    (SECTIONS, "Sections worked window"),
    (TOGGLE_NETWORK, "Toggle network panel"),
    (SHORTCUTS, "Keyboard shortcuts (this window)"),
]

# Operating keys are behaviors (not menu actions); shown literally.
OPERATING: list[tuple[str, str]] = [
    ("F1 – F12", "Send the F-key macro for the current Run / S&P bank"),
    ("Enter", "Log the QSO / advance to the next field (ESM: send the next message)"),
    ("Esc", "Emergency stop transmitting"),
]


def fmt_keys(keyspec: str) -> str:
    """Render a key spec in the platform-native notation (⌘N on macOS, Ctrl+N else)."""
    native = QKeySequence(keyspec).toString(QKeySequence.SequenceFormat.NativeText)
    return native or keyspec


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PartyHams Logger — Keyboard Shortcuts")
        self.setMinimumWidth(440)

        outer = QVBoxLayout(self)
        for title, rows, literal in (("Commands", COMMANDS, False), ("Operating", OPERATING, True)):
            header = QLabel(f"<b>{title}</b>")
            header.setStyleSheet(f"color: {style.TEXT_DIM}; margin-top: 6px;")
            outer.addWidget(header)
            grid = QGridLayout()
            grid.setColumnMinimumWidth(0, 110)
            grid.setColumnStretch(1, 1)
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(4)
            for row, (keys, desc) in enumerate(rows):
                chip = QLabel(keys if literal else fmt_keys(keys))
                chip.setStyleSheet(
                    f"QLabel {{ background: {style.BORDER}; color: {style.TEXT};"
                    f" border-radius: 4px; padding: 1px 7px; }}"
                )
                grid.addWidget(chip, row, 0)
                grid.addWidget(QLabel(desc), row, 1)
            outer.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        outer.addWidget(buttons)
