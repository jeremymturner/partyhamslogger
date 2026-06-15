"""Settings dialog for the automatic update check.

Lets the operator turn the GitHub release check on/off (privacy opt-out), choose
how often it runs (1 hour .. 7 days), and trigger a check right now. The interval
spinbox is disabled while the check is off.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from partyhams.app.update import UPDATE_MAX_HOURS, UPDATE_MIN_HOURS, clamp_interval_hours


class UpdateSettingsDialog(QDialog):
    def __init__(
        self,
        enabled: bool,
        interval_hours: int,
        *,
        on_check_now=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update Settings")
        self._on_check_now = on_check_now

        outer = QVBoxLayout(self)
        form = QFormLayout()

        self._enabled = QCheckBox("Automatically check for new releases")
        self._enabled.setChecked(enabled)
        form.addRow(self._enabled)

        self._hours = QSpinBox()
        self._hours.setRange(UPDATE_MIN_HOURS, UPDATE_MAX_HOURS)  # 1 hour .. 7 days
        self._hours.setSuffix(" h")
        self._hours.setValue(clamp_interval_hours(interval_hours))
        self._hours.setToolTip("How often to check (1 hour to 7 days = 168 hours)")
        form.addRow("Check every:", self._hours)

        outer.addLayout(form)

        self._check_now = QPushButton("Check for Updates Now")
        self._check_now.clicked.connect(self._do_check_now)
        outer.addWidget(self._check_now)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._enabled.toggled.connect(self._hours.setEnabled)
        self._hours.setEnabled(self._enabled.isChecked())

    def _do_check_now(self) -> None:
        if self._on_check_now is not None:
            self._on_check_now()

    def settings(self) -> tuple[bool, int]:
        """Return the chosen ``(enabled, interval_hours)``."""
        return self._enabled.isChecked(), self._hours.value()
