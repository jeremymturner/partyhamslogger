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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from partyhams.contest import available
from partyhams.contest import get as get_contest
from partyhams.contest.pota import is_valid_park
from partyhams.contest.pota_api import verify_park
from partyhams.ui.widgets import make_upper


class LogDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self._park_status: QLabel | None = None
        self._contest.currentIndexChanged.connect(lambda _i: self._rebuild_contest_fields())
        self._rebuild_contest_fields()

    def _rebuild_contest_fields(self) -> None:
        while self._dyn.rowCount():
            self._dyn.removeRow(0)
        self._exchange_edits = {}
        self._config_widgets = {}
        self._park_status = None

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
            elif contest.id == "pota" and cfg.name == "park":
                self._add_park_field(cfg)
            else:
                edit = QLineEdit(cfg.default)
                self._config_widgets[cfg.name] = edit
                self._dyn.addRow(cfg.label, edit)

    def _add_park_field(self, cfg) -> None:
        """A park-reference text field with an inline 'Verify park' button."""
        edit = QLineEdit(cfg.default)
        make_upper(edit)
        self._config_widgets[cfg.name] = edit
        verify = QPushButton("Verify park")
        verify.clicked.connect(self._verify_park)
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.addWidget(edit, 1)
        hbox.addWidget(verify)
        self._dyn.addRow(cfg.label, row)
        self._park_status = QLabel("")
        self._park_status.setWordWrap(True)
        self._dyn.addRow("", self._park_status)

    def _verify_park(self) -> None:
        """Resolve the park ref via the POTA API; soft-warn (never block) on failure."""
        if self._park_status is None:
            return
        widget = self._config_widgets.get("park")
        ref = widget.text().strip().upper() if isinstance(widget, QLineEdit) else ""
        if not is_valid_park(ref):
            self._park_status.setText("Enter a park like US-1234 to verify.")
            return
        self._park_status.setText("Verifying…")
        info = verify_park(ref)
        if info:
            loc = f" — {info['location']}" if info.get("location") else ""
            self._park_status.setText(f"{info['reference']}: {info['name']}{loc}")
        else:
            self._park_status.setText(
                f"Could not verify {ref} (offline or unknown). You can still log."
            )

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
