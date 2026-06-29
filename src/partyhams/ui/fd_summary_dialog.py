"""Field Day summary-info entry dialog.

Collects the figures the ARRL Field Day web form needs that the log doesn't
already know: number of participants, the club/group name, an optional GOTA
station call, and the itemised bonus points (rules §7). The QSO totals and score
are computed from the log, not entered here.

The bonus catalog is data-driven (:mod:`partyhams.contest.fd_bonus`); this dialog
just renders it. ``settings()`` returns the ``extra`` updates to merge into the
station config (including a recomputed aggregate ``bonus_points`` so older code
paths keep working).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from partyhams.contest.fd_bonus import (
    BONUS_SELECTIONS_KEY,
    FD_BONUS_ITEMS,
    BonusItem,
    bonus_total,
)


class _BonusRow:
    """One bonus item's widgets: an enable checkbox plus, for counted items, a
    quantity spinbox. ``value()`` returns the stored selection (bool or int)."""

    def __init__(self, item: BonusItem, raw: object) -> None:
        self.item = item
        self.check = QCheckBox(f"{item.label}  (+{item.points})")
        if item.note:
            self.check.setToolTip(item.note)
        self.spin: QSpinBox | None = None
        if item.counted:
            self.spin = QSpinBox()
            max_count = (item.max_points // item.points) if item.max_points else 999
            self.spin.setRange(0, max_count)
            self.spin.setPrefix("× ")
            count = _as_int(raw)
            self.spin.setValue(count)
            self.check.setChecked(count > 0)
        else:
            self.check.setChecked(bool(raw))

    def widget(self) -> QWidget:
        if self.spin is None:
            return self.check
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.check)
        layout.addStretch(1)
        layout.addWidget(self.spin)
        return row

    def value(self) -> object:
        if self.spin is not None:
            return self.spin.value() if self.check.isChecked() else 0
        return self.check.isChecked()


def _as_int(raw: object) -> int:
    try:
        return max(0, int(raw))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


class FieldDaySummaryDialog(QDialog):
    def __init__(self, extra: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Field Day Summary Info")
        extra = extra or {}
        selections = extra.get(BONUS_SELECTIONS_KEY)
        selections = selections if isinstance(selections, dict) else {}

        outer = QVBoxLayout(self)
        outer.addWidget(
            QLabel(
                "Enter the details the Field Day web form needs but the log can't\n"
                "compute. QSO totals and score come from the log automatically."
            )
        )

        form = QFormLayout()
        self._participants = QSpinBox()
        self._participants.setRange(0, 9999)
        self._participants.setValue(_as_int(extra.get("participants")))
        form.addRow("Participants:", self._participants)

        self._club = QLineEdit(str(extra.get("club_name", "") or ""))
        self._club.setPlaceholderText("Club or group name (optional)")
        form.addRow("Club / group:", self._club)

        self._gota = QLineEdit(str(extra.get("gota_call", "") or ""))
        self._gota.setPlaceholderText("GOTA station call (optional)")
        form.addRow("GOTA call:", self._gota)
        outer.addLayout(form)

        outer.addWidget(QLabel("Bonus points claimed:"))
        self._rows: list[_BonusRow] = []
        bonus_box = QWidget()
        bonus_layout = QVBoxLayout(bonus_box)
        bonus_layout.setContentsMargins(0, 0, 0, 0)
        for item in FD_BONUS_ITEMS:
            row = _BonusRow(item, selections.get(item.key))
            self._rows.append(row)
            bonus_layout.addWidget(row.widget())
            row.check.toggled.connect(self._update_total)
            if row.spin is not None:
                row.spin.valueChanged.connect(self._update_total)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(bonus_box)
        scroll.setMinimumHeight(240)
        outer.addWidget(scroll)

        self._total = QLabel()
        outer.addWidget(self._total)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._update_total()

    def _current_selections(self) -> dict:
        return {row.item.key: row.value() for row in self._rows}

    def _update_total(self) -> None:
        self._total.setText(f"Total bonus points: {bonus_total(self._current_selections())}")

    def settings(self) -> dict:
        """The ``extra`` updates to merge into the station config."""
        selections = self._current_selections()
        return {
            "participants": self._participants.value(),
            "club_name": self._club.text().strip(),
            "gota_call": self._gota.text().strip().upper(),
            BONUS_SELECTIONS_KEY: selections,
            "bonus_points": bonus_total(selections),
        }
