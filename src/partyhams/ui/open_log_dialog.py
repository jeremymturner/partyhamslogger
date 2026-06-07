"""Open Log chooser — pick one of the saved logs (or browse for a file)."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from partyhams.app.session import list_logs

_COLUMNS = ["Activity", "Call", "QSOs", "Modified"]


class OpenLogDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PartyHams Logger — Open Log")
        self.resize(520, 340)
        self._chosen: str | None = None
        self._logs = list_logs()

        self._table = QTableWidget(len(self._logs), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.setColumnWidth(0, 160)
        self._table.setColumnWidth(1, 90)
        self._table.setColumnWidth(2, 60)
        for row, log in enumerate(self._logs):
            modified = datetime.fromtimestamp(log["mtime"]).strftime("%Y-%m-%d %H:%M")
            values = [log["contest"], log["call"], str(log["qsos"]), modified]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, log["path"])
                self._table.setItem(row, col, item)
        if self._logs:
            self._table.selectRow(0)
        self._table.doubleClicked.connect(lambda _i: self._accept_selection())

        buttons = QDialogButtonBox()
        buttons.addButton("Browse…", QDialogButtonBox.ButtonRole.ActionRole).clicked.connect(
            self._browse
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Open).clicked.connect(
            self._accept_selection
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addWidget(buttons)

    def _accept_selection(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < len(self._logs):
            self._chosen = self._logs[row]["path"]
            self.accept()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Log", "", "PartyHams log (*.sqlite)")
        if path:
            self._chosen = path
            self.accept()

    def selected_path(self) -> str | None:
        return self._chosen
