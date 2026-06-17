"""Settings dialog for QRZ.com XML-API credentials.

QRZ callsign lookups need a (paid) XML-subscription account. This small dialog
gathers the username and password; they're persisted via AppState and used to
pull station info (name/QTH/state/grid) as you enter a callsign. Leaving the
fields blank disables the lookup.

A **Test Login** button runs a live login plus a W1AW lookup and reports the
outcome verbosely in the dialog, so the operator can tell *why* a login failed
(invalid credentials vs. TLS / timeout / site unavailable) without hunting in
the status bar. The network call itself is driven by the owner (MainWindow) via
the :attr:`on_test` callback so it stays off the UI thread.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from partyhams.ui import style


class QrzDialog(QDialog):
    def __init__(
        self, username: str = "", password: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("QRZ.com Login")
        self.setMinimumWidth(380)

        #: Set by the owner: on_test(username, password) runs a background
        #: login + W1AW lookup and calls show_test_result() with the outcome.
        self.on_test: Callable[[str, str], None] | None = None

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

        self._test_btn = QPushButton("Test Login")
        self._test_btn.setToolTip("Log in and look up W1AW to verify these credentials.")
        self._test_btn.clicked.connect(self._on_test_clicked)
        outer.addWidget(self._test_btn)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setVisible(False)
        outer.addWidget(self._result)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def settings(self) -> tuple[str, str]:
        """Return the entered (username, password)."""
        return self._user.text().strip(), self._password.text()

    # ------------------------------------------------------------------ #
    # Test Login
    # ------------------------------------------------------------------ #
    def _on_test_clicked(self) -> None:
        username = self._user.text().strip()
        password = self._password.text()
        if not username or not password:
            self._show("Enter both a QRZ username and password to test.", style.DUPE)
            return
        if self.on_test is None:
            return
        self._test_btn.setEnabled(False)
        self._test_btn.setText("Testing…")
        self._show(f"Testing QRZ login as {username} (looking up W1AW)…", style.TEXT_DIM)
        self.on_test(username, password)

    def show_test_result(self, ok: bool, message: str) -> None:
        """Display the outcome of a background test (called by the owner)."""
        self._test_btn.setEnabled(True)
        self._test_btn.setText("Test Login")
        self._show(message, style.MULT if ok else style.DUPE)

    def _show(self, message: str, color: str) -> None:
        self._result.setStyleSheet(f"color: {color};")
        self._result.setText(message)
        self._result.setVisible(True)
