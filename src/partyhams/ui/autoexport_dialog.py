"""Settings dialog for the periodic ADIF auto-export.

Lets the operator enable/disable the timed backup, pick its interval (5..60
minutes), and choose whether to skip exports when no new QSOs have been logged
since the last one. The interval spinbox is disabled while auto-export is off.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from partyhams.ui.main_window import AUTOEXPORT_MAX, AUTOEXPORT_MIN, clamp_export_minutes


class AutoExportDialog(QDialog):
    def __init__(
        self,
        enabled: bool,
        minutes: int,
        only_if_new: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Auto-export Settings")

        outer = QVBoxLayout(self)
        form = QFormLayout()

        self._enabled = QCheckBox("Enable periodic ADIF auto-export")
        self._enabled.setChecked(enabled)
        form.addRow(self._enabled)

        self._minutes = QSpinBox()
        self._minutes.setRange(AUTOEXPORT_MIN, AUTOEXPORT_MAX)
        self._minutes.setSuffix(" min")
        self._minutes.setValue(clamp_export_minutes(minutes))
        form.addRow("Interval:", self._minutes)

        self._only_if_new = QCheckBox("Only when there are new QSOs")
        self._only_if_new.setChecked(only_if_new)
        form.addRow(self._only_if_new)

        outer.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._enabled.toggled.connect(self._sync_enabled)
        self._sync_enabled(self._enabled.isChecked())

    def _sync_enabled(self, on: bool) -> None:
        self._minutes.setEnabled(on)
        self._only_if_new.setEnabled(on)

    def settings(self) -> tuple[bool, int, bool]:
        """Return the chosen (enabled, minutes, only_if_new)."""
        return (
            self._enabled.isChecked(),
            self._minutes.value(),
            self._only_if_new.isChecked(),
        )
