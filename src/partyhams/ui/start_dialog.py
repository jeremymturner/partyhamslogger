"""First-run dialog: collect the few things needed to start logging.

Deliberately tiny — call, class, section, power, and an optional network name.
Blank network means solo/offline. (The N1MM setup experience this replaces is a
maze of dialogs; keeping this to one screen is the whole point.)
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
)

# (label, power-category key) — keys match PowerCategory in contest.fieldday.
_POWER_OPTIONS = [
    ("Low — ≤150 W (×2)", "low_150w"),
    ("QRP — ≤5 W, alt power (×5)", "qrp_5w_alt"),
    ("High — >150 W (×1)", "high"),
]


class StartDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PartyHams Logger — Start Field Day")
        self.setMinimumWidth(360)

        self._call = QLineEdit()
        self._call.setPlaceholderText("e.g. W7ABC")
        self._class = QLineEdit("1E")
        self._section = QLineEdit()
        self._section.setPlaceholderText("e.g. OR")
        self._power = QComboBox()
        for label, _ in _POWER_OPTIONS:
            self._power.addItem(label)
        self._network = QLineEdit()
        self._network.setPlaceholderText("blank = solo / offline")
        self._operator = QLineEdit()
        self._operator.setPlaceholderText("this operator (defaults to station call)")

        form = QFormLayout(self)
        form.addRow("Station call", self._call)
        form.addRow("Class", self._class)
        form.addRow("Section", self._section)
        form.addRow("Power", self._power)
        form.addRow("Operator", self._operator)
        form.addRow("Network name", self._network)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_accept(self) -> None:
        if not self._call.text().strip():
            self._call.setFocus()
            return
        self.accept()

    def settings(self) -> dict:
        call = self._call.text().strip().upper()
        return {
            "my_call": call,
            "operator": (self._operator.text().strip().upper() or call),
            "fd_class": self._class.text().strip().upper(),
            "section": self._section.text().strip().upper(),
            "power": _POWER_OPTIONS[self._power.currentIndex()][1],
            "network": self._network.text().strip(),
        }
