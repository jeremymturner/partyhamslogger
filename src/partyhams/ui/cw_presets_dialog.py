"""Settings dialog for the CW WPM preset buttons.

Lets the operator turn the whole feature on or off and manage any number of
quick-speed presets (add / change / remove). The list is disabled while the
feature is switched off, so an unchecked box truly hides the presets and the
``+`` button from the CW speed bar.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from partyhams.app.macros import WPM_MAX, WPM_MIN, clamp_wpm, normalize_wpm_presets


class CwPresetsDialog(QDialog):
    def __init__(
        self,
        presets: list[int],
        enabled: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CW WPM Presets")

        outer = QVBoxLayout(self)

        self._enabled = QCheckBox("Show CW WPM preset buttons")
        self._enabled.setChecked(enabled)
        self._enabled.setToolTip(
            "When off, no preset buttons or the + add button appear on the CW speed bar"
        )
        outer.addWidget(self._enabled)

        self._list = QListWidget()
        for wpm in normalize_wpm_presets(presets):
            self._list.addItem(f"{wpm} WPM")
        self._list.itemDoubleClicked.connect(lambda _item: self._edit())
        outer.addWidget(self._list)

        row = QHBoxLayout()
        self._add_btn = QPushButton("Add…")
        self._add_btn.clicked.connect(self._add)
        self._edit_btn = QPushButton("Change…")
        self._edit_btn.clicked.connect(self._edit)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._remove)
        row.addWidget(self._add_btn)
        row.addWidget(self._edit_btn)
        row.addWidget(self._remove_btn)
        row.addStretch(1)
        outer.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._enabled.toggled.connect(self._sync_enabled)
        self._sync_enabled(self._enabled.isChecked())

    def _sync_enabled(self, on: bool) -> None:
        self._list.setEnabled(on)
        self._add_btn.setEnabled(on)
        self._edit_btn.setEnabled(on)
        self._remove_btn.setEnabled(on)

    def _ask_wpm(self, initial: int) -> int | None:
        value, ok = QInputDialog.getInt(
            self, "CW WPM Preset", "Speed (WPM):", initial, WPM_MIN, WPM_MAX
        )
        return clamp_wpm(value) if ok else None

    def _add(self) -> None:
        wpm = self._ask_wpm(20)
        if wpm is not None:
            self._list.addItem(f"{wpm} WPM")

    def _edit(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        wpm = self._ask_wpm(self._values()[row])
        if wpm is not None:
            self._list.item(row).setText(f"{wpm} WPM")

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)

    def _values(self) -> list[int]:
        return [int(self._list.item(i).text().split()[0]) for i in range(self._list.count())]

    def settings(self) -> tuple[list[int], bool]:
        """Return the chosen (presets, enabled), presets clamped and de-duplicated."""
        return normalize_wpm_presets(self._values()), self._enabled.isChecked()
