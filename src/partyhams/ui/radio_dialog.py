"""Radio-selection screen — shown after a log is set up if no radio is configured.

Separate from log creation on purpose: the radio is a per-station hardware choice,
not part of the log/event. "None" is a valid, remembered answer (manual band/mode).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

# Radio kinds that connect directly to the rig over the network (Icom native LAN).
_LAN_KINDS = ("icom705-lan", "icom7610-lan")


class RadioDialog(QDialog):
    def __init__(self, current: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PartyHams Logger — Select Radio")
        self.setMinimumWidth(380)

        self._radio = QComboBox()
        self._radio.addItem("None — manual band/mode", "none")
        self._radio.addItem("Hamlib (rigctld)", "hamlib")
        self._radio.addItem("FlexRadio (native)", "flex")
        self._radio.addItem("Icom IC-705 (CI-V serial)", "icom705")
        self._radio.addItem("Icom IC-7610 (CI-V serial)", "icom7610")
        self._radio.addItem("Icom IC-705 (LAN / Ethernet)", "icom705-lan")
        self._radio.addItem("Icom IC-7610 (LAN / Ethernet)", "icom7610-lan")
        self._conn = QLineEdit()
        self._conn.setEnabled(False)
        self._user = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)

        if current:
            idx = self._radio.findData(current.get("kind", "none"))
            if idx >= 0:
                self._radio.setCurrentIndex(idx)
            self._conn.setText(current.get("conn", ""))
            self._user.setText(current.get("user", ""))
            self._password.setText(current.get("password", ""))

        info = QLabel(
            "Choose how to read frequency/mode from your rig. You can change this "
            "later, and 'None' is fine — you'll just pick band/mode manually."
        )
        info.setWordWrap(True)

        outer = QVBoxLayout(self)
        outer.addWidget(info)
        self._form = QFormLayout()
        self._form.addRow("Radio", self._radio)
        self._form.addRow("Connection", self._conn)
        self._form.addRow("Username", self._user)
        self._form.addRow("Password", self._password)
        outer.addLayout(self._form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        # Connect only after the form exists — restoring `current` above can fire it.
        self._radio.currentIndexChanged.connect(lambda _i: self._on_radio_changed())
        self._on_radio_changed()

    def _on_radio_changed(self) -> None:
        kind = self._radio.currentData()
        is_lan = kind in _LAN_KINDS
        self._conn.setEnabled(kind != "none")
        # Username/password only apply to the native-LAN Icom connections.
        self._form.setRowVisible(self._user, is_lan)
        self._form.setRowVisible(self._password, is_lan)
        if kind == "hamlib":
            self._conn.setPlaceholderText("rigctld host:port (default 127.0.0.1:4532)")
        elif kind == "flex":
            self._conn.setPlaceholderText("radio IP (blank = auto-discover)")
        elif kind in ("icom705", "icom7610"):
            self._conn.setPlaceholderText("serial port (e.g. /dev/cu.usbmodem…)")
        elif is_lan:
            self._conn.setPlaceholderText("radio IP or hostname (Network function must be On)")
        else:
            self._conn.setPlaceholderText("")

    def settings(self) -> dict:
        return {
            "kind": self._radio.currentData(),
            "conn": self._conn.text().strip(),
            "user": self._user.text().strip(),
            "password": self._password.text(),
        }
