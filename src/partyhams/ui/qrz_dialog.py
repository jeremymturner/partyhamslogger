"""Settings dialog for QRZ.com XML-API credentials.

QRZ callsign lookups need a (paid) XML-subscription account. This small dialog
gathers the username and password; they're persisted via AppState and used to
pull station info (name/QTH/state/grid) as you enter a callsign. Leaving the
fields blank disables the lookup.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class QrzDialog(QDialog):
    def __init__(
        self, username: str = "", password: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("QRZ.com Login")
        self.setMinimumWidth(360)

        info = QLabel(
            "Enter your QRZ.com username and password to look up station info "
            "(name, QTH, state, grid) as you type a callsign. A QRZ XML "
            "subscription is required. Leave blank to disable lookups."
        )
        info.setWordWrap(True)

        self._user = QLineEdit(username)
        self._password = QLineEdit(password)
        self._password.setEchoMode(QLineEdit.EchoMode.Password)

        outer = QVBoxLayout(self)
        outer.addWidget(info)
        form = QFormLayout()
        form.addRow("Username", self._user)
        form.addRow("Password", self._password)
        outer.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def settings(self) -> tuple[str, str]:
        """Return the entered (username, password)."""
        return self._user.text().strip(), self._password.text()
