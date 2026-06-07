"""Log-creation screen: pick the activity type and set up the station.

The activity (contest) is a dropdown populated from the contest registry, so new
contests appear here automatically. The exchange and any extra config fields
(e.g. Field Day power) are generated from the selected contest — no radio here;
that's a separate screen.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from partyhams.contest import available
from partyhams.contest import get as get_contest
from partyhams.ui.widgets import make_upper


class LogDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PartyHams Logger — New Log")
        self.setMinimumWidth(380)

        self._contest = QComboBox()
        for contest_id, name in available():
            self._contest.addItem(name, contest_id)
        self._call = QLineEdit()
        self._call.setPlaceholderText("e.g. W7ABC")
        self._operator = QLineEdit()
        self._operator.setPlaceholderText("this operator (defaults to station call)")
        self._network = QLineEdit()
        self._network.setPlaceholderText("blank = solo / offline")
        make_upper(self._call, self._operator)

        outer = QVBoxLayout(self)
        top = QFormLayout()
        top.addRow("Activity", self._contest)
        top.addRow("Station call", self._call)
        top.addRow("Operator", self._operator)
        top.addRow("Network name", self._network)
        outer.addLayout(top)

        # Contest-specific fields (exchange + config) live in their own form so we
        # can rebuild just this section when the activity changes.
        self._dyn_widget = QWidget()
        self._dyn = QFormLayout(self._dyn_widget)
        self._dyn.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._dyn_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._exchange_edits: dict[str, QLineEdit] = {}
        self._config_widgets: dict[str, QWidget] = {}
        self._contest.currentIndexChanged.connect(lambda _i: self._rebuild_contest_fields())
        self._rebuild_contest_fields()

    def _rebuild_contest_fields(self) -> None:
        while self._dyn.rowCount():
            self._dyn.removeRow(0)
        self._exchange_edits = {}
        self._config_widgets = {}

        contest = get_contest(self._contest.currentData())
        for fld in contest.exchange_fields():
            edit = QLineEdit()
            make_upper(edit)
            self._exchange_edits[fld.name] = edit
            self._dyn.addRow(f"My {fld.label}", edit)
        for cfg in contest.config_fields():
            if cfg.choices:
                combo = QComboBox()
                for label, value in cfg.choices:
                    combo.addItem(label, value)
                idx = combo.findData(cfg.default)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                self._config_widgets[cfg.name] = combo
                self._dyn.addRow(cfg.label, combo)
            else:
                edit = QLineEdit(cfg.default)
                self._config_widgets[cfg.name] = edit
                self._dyn.addRow(cfg.label, edit)

    def _on_accept(self) -> None:
        if not self._call.text().strip():
            self._call.setFocus()
            return
        self.accept()

    def settings(self) -> dict:
        call = self._call.text().strip().upper()
        extra: dict[str, object] = {}
        for name, widget in self._config_widgets.items():
            if isinstance(widget, QComboBox):
                extra[name] = widget.currentData()
            elif isinstance(widget, QLineEdit):
                extra[name] = widget.text().strip()
        return {
            "contest_id": self._contest.currentData(),
            "my_call": call,
            "operator": self._operator.text().strip().upper() or call,
            "network": self._network.text().strip(),
            "sent_exchange": {n: e.text().strip().upper() for n, e in self._exchange_edits.items()},
            "extra": extra,
        }
