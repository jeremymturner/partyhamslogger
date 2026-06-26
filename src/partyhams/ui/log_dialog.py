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
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from partyhams.contest import available
from partyhams.contest import get as get_contest
from partyhams.contest.calendar import nearest_contest_id
from partyhams.contest.pota import is_valid_park
from partyhams.contest.pota_api import verify_park
from partyhams.core.models import utcnow
from partyhams.ui.widgets import make_upper


def _split_parks(value: str) -> list[str]:
    """Split a comma-separated park list into normalized, de-duplicated refs."""
    out: list[str] = []
    for part in (value or "").split(","):
        ref = part.strip().upper()
        if ref and ref not in out:
            out.append(ref)
    return out


class LogDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, existing: dict | None = None) -> None:
        super().__init__(parent)
        # ``existing`` switches the dialog to edit-an-open-log mode: it pre-fills
        # every field and locks the contest type + network (both fixed at creation).
        self._editing = existing is not None
        # POTA park lookup; overridable in tests to avoid the network.
        self._verify_fn = verify_park
        self.setWindowTitle(
            "PartyHams Logger — Edit Log" if self._editing else "PartyHams Logger — New Log"
        )
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
        top.addRow("Activity name", self._network)
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

        if self._editing:
            self._load_existing(existing)
        else:
            self._select_default_contest()
            self._rebuild_contest_fields()

    def _load_existing(self, existing: dict) -> None:
        """Pre-fill the dialog from an open log and lock the fixed fields."""
        idx = self._contest.findData(existing.get("contest_id"))
        if idx >= 0:
            self._contest.setCurrentIndex(idx)
        self._contest.setEnabled(False)  # contest type is fixed once a log exists
        self._contest.setToolTip("The activity is set when the log is created")
        self._call.setText(existing.get("my_call", ""))
        self._operator.setText(existing.get("operator", ""))
        self._network.setText(existing.get("network", ""))
        self._network.setEnabled(False)  # the sync activity name is fixed at creation
        self._network.setToolTip("The activity name is set when the log is created")
        self._rebuild_contest_fields()
        self._prefill_contest_fields(existing)

    def _prefill_contest_fields(self, existing: dict) -> None:
        """Fill the dynamic exchange + config widgets from an open log's config."""
        sent = existing.get("sent_exchange") or {}
        for name, edit in self._exchange_edits.items():
            edit.setText(str(sent.get(name, "")))
        extra = existing.get("extra") or {}
        for name, widget in self._config_widgets.items():
            value = extra.get(name)
            if value is None:
                continue
            if isinstance(widget, QComboBox):
                i = widget.findData(value)
                if i >= 0:
                    widget.setCurrentIndex(i)
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))
        # POTA: parks, entity, and location.
        names = extra.get("park_names")
        if isinstance(names, dict):
            self._park_names.update({str(k): str(v) for k, v in names.items()})
        if self._park_list is not None:
            for ref in _split_parks(str(extra.get("park", ""))):
                self._park_list.addItem(ref)
        if self._entity_edit is not None and extra.get("entity"):
            self._entity_edit.setText(str(extra["entity"]))
        if self._location_combo is not None and extra.get("location"):
            loc = str(extra["location"]).upper()
            if self._location_combo.findText(loc) < 0:
                self._location_combo.addItem(loc)
            self._location_combo.setCurrentText(loc)

    def _select_default_contest(self) -> None:
        """Default a new log to the contest nearest today's date (calendar #23).

        Falls back to the combo's existing default when no nearby event maps to a
        registered contest, so behaviour is unchanged where the calendar is silent.
        """
        contest_id = nearest_contest_id(utcnow())
        if contest_id is None:
            return
        idx = self._contest.findData(contest_id)
        if idx >= 0:
            self._contest.setCurrentIndex(idx)

    def _rebuild_contest_fields(self) -> None:
        while self._dyn.rowCount():
            self._dyn.removeRow(0)
        self._exchange_edits = {}
        self._config_widgets = {}
        self._park_status = None
        self._park_edit = None  # POTA: the "add a park" entry field
        self._park_list = None  # POTA: the list of added park references
        self._entity_edit = None  # POTA: DX entity of the operating site
        self._location_combo = None  # POTA: location code (selectable if ambiguous)
        self._park_names: dict[str, str] = {}  # POTA: park ref -> name (from Verify)

        contest = get_contest(self._contest.currentData())
        for fld in contest.exchange_fields():
            if not fld.sent:
                continue  # received-only (e.g. a P2P park) — not part of our sent exchange
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
        """Multi-park entry for a POTA activation: add park references one at a
        time (n-fer activations span overlapping parks). They're stored
        comma-separated and exported as the activator's ``MY_POTA_REF``."""
        self._park_edit = QLineEdit()
        make_upper(self._park_edit)
        self._park_edit.setPlaceholderText("US-1234")
        self._park_edit.returnPressed.connect(self._add_park_ref)
        add = QPushButton("Add")
        add.clicked.connect(self._add_park_ref)
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.addWidget(self._park_edit, 1)
        hbox.addWidget(add)
        self._dyn.addRow(cfg.label, row)

        self._park_list = QListWidget()
        self._park_list.setMaximumHeight(90)
        self._dyn.addRow("", self._park_list)
        # Remove + Verify share a row; Verify looks up every park in the list.
        actions = QWidget()
        ahbox = QHBoxLayout(actions)
        ahbox.setContentsMargins(0, 0, 0, 0)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_park_ref)
        verify = QPushButton("Verify")
        verify.clicked.connect(self._verify_all_parks)
        ahbox.addWidget(remove)
        ahbox.addWidget(verify)
        self._dyn.addRow("", actions)

        self._park_status = QLabel("")
        self._park_status.setWordWrap(True)
        self._dyn.addRow("", self._park_status)

        # Where the operation is physically located. Usually derived from the park
        # (filled in by Verify); editable, and a selectable list when a park spans
        # more than one location.
        self._entity_edit = QLineEdit()
        self._entity_edit.setPlaceholderText("e.g. United States Of America")
        self._dyn.addRow("DX entity", self._entity_edit)
        self._location_combo = QComboBox()
        self._location_combo.setEditable(True)
        make_upper(self._location_combo.lineEdit())
        self._location_combo.lineEdit().setPlaceholderText("e.g. US-WA")
        self._dyn.addRow("Location", self._location_combo)

        # Seed from the default (may be a comma-separated list when reused).
        for ref in _split_parks(cfg.default):
            self._park_list.addItem(ref)

    def _current_parks(self) -> list[str]:
        """Parks added to the list, plus any valid-but-not-yet-added entry text."""
        if self._park_list is None:
            return []
        parks = [self._park_list.item(i).text() for i in range(self._park_list.count())]
        pending = self._park_edit.text().strip().upper() if self._park_edit is not None else ""
        if pending and is_valid_park(pending) and pending not in parks:
            parks.append(pending)
        return parks

    def _add_park_ref(self) -> None:
        if self._park_edit is None or self._park_list is None:
            return
        ref = self._park_edit.text().strip().upper()
        if not ref:
            return
        if not is_valid_park(ref):
            self._park_status.setText(f"{ref} doesn't look like a park (e.g. US-1234).")
            return
        existing = {self._park_list.item(i).text() for i in range(self._park_list.count())}
        if ref in existing:
            self._park_status.setText(f"{ref} is already added.")
        else:
            self._park_list.addItem(ref)
            self._park_status.setText("")
        self._park_edit.clear()
        self._park_edit.setFocus()

    def _remove_park_ref(self) -> None:
        if self._park_list is None:
            return
        for item in self._park_list.selectedItems():
            self._park_list.takeItem(self._park_list.row(item))

    def _verify_all_parks(self) -> None:
        """Look up every park in the list via the POTA API and aggregate the DX
        entity + all candidate locations. When more than one distinct location
        turns up (e.g. US-4403 spans several), the operator must pick one before
        the dialog can be accepted."""
        if self._park_status is None:
            return
        parks = self._current_parks()
        if not parks:
            self._park_status.setText("Add a park to verify.")
            return
        self._park_status.setText(f"Verifying {len(parks)} park(s)…")
        entity = ""
        locations: list[str] = []
        failed: list[str] = []
        for ref in parks:
            info = self._verify_fn(ref)
            if not info:
                failed.append(ref)
                continue
            if info.get("name"):
                self._park_names[ref] = str(info["name"])
            if info.get("entity") and not entity:
                entity = str(info["entity"])
            opts = info.get("locations") or ([info["location"]] if info.get("location") else [])
            for loc in opts:
                if loc and loc not in locations:
                    locations.append(loc)
        self._apply_verify_results(entity, locations)
        parts = [f"Verified {len(parks) - len(failed)}/{len(parks)} park(s)"]
        if failed:
            parts.append(f"couldn't verify {', '.join(failed)} (offline/unknown)")
        if len(locations) > 1:
            parts.append(f"{len(locations)} locations — select where you're operating")
        self._park_status.setText("  ·  ".join(parts))

    def _apply_verify_results(self, entity: str, locations: list[str]) -> None:
        """Fill the DX entity (if blank) and rebuild the location options. A single
        location auto-selects; multiple force an explicit choice; a selection the
        operator already made is preserved."""
        if self._entity_edit is not None and entity and not self._entity_edit.text().strip():
            self._entity_edit.setText(entity)
        combo = self._location_combo
        if combo is None:
            return
        prior = combo.currentText().strip()
        combo.clear()
        combo.addItems(locations)
        if prior:
            combo.setCurrentText(prior)  # keep an existing choice/entry
        elif len(locations) == 1:
            combo.setCurrentText(locations[0])
        else:
            combo.setCurrentIndex(-1)  # ambiguous (or none) -> force a pick
            combo.lineEdit().clear()

    def _on_accept(self) -> None:
        if not self._call.text().strip():
            self._call.setFocus()
            return
        # A park spanning multiple locations must be resolved before continuing.
        if (
            self._location_combo is not None
            and self._location_combo.count() > 1
            and not self._location_combo.currentText().strip()
        ):
            if self._park_status is not None:
                self._park_status.setText(
                    "This park spans multiple locations — select where you're operating."
                )
            self._location_combo.setFocus()
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
        # POTA park(s): the multi-park list, stored comma-separated (MY_POTA_REF).
        parks = self._current_parks()
        if parks:
            extra["park"] = ",".join(parks)
            names = {ref: self._park_names[ref] for ref in parks if ref in self._park_names}
            if names:
                extra["park_names"] = names
        # Operating site: DX entity + location (derived from the park, or manual).
        if self._entity_edit is not None and self._entity_edit.text().strip():
            extra["entity"] = self._entity_edit.text().strip()
        if self._location_combo is not None and self._location_combo.currentText().strip():
            extra["location"] = self._location_combo.currentText().strip().upper()
        return {
            "contest_id": self._contest.currentData(),
            "my_call": call,
            "operator": self._operator.text().strip().upper() or call,
            "network": self._network.text().strip(),
            "sent_exchange": {n: e.text().strip().upper() for n, e in self._exchange_edits.items()},
            "extra": extra,
        }
