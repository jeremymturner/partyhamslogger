"""DX Cluster window: connect to a telnet cluster and click spots to tune.

A cluster picker (the bundled :data:`~partyhams.cluster.DEFAULT_CLUSTERS` plus a
free-form ``host:port`` field), Connect/Disconnect, and a live grid of incoming
spots (newest on top, capped). Double-clicking a spot row tunes the currently
selected radio to that frequency via the :class:`RadioPoller`.
"""

from __future__ import annotations

import asyncio

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from partyhams.app.radio import RadioPoller
from partyhams.cluster import DEFAULT_CLUSTERS, ClusterClient, Spot
from partyhams.radio.base import Capability

#: Cap the grid so a busy cluster can't grow it without bound.
MAX_SPOTS = 300

_COLUMNS = ["Time", "Call", "Freq (MHz)", "Band", "Spotter", "Comment"]

# Qt user-data role for stashing the spot's frequency on the row's items.
_FREQ_ROLE = int(Qt.ItemDataRole.UserRole)


def _freq_mhz(freq_hz: int) -> str:
    """Format a frequency in Hz as MHz with kHz precision, e.g. ``14.025.00``."""
    mhz, khz, hz = freq_hz // 1_000_000, (freq_hz // 1000) % 1000, (freq_hz % 1000) // 10
    return f"{mhz}.{khz:03d}.{hz:02d}"


class ClusterWindow(QWidget):
    def __init__(
        self,
        poller: RadioPoller | None = None,
        login_call: str = "",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        super().__init__()
        self._poller = poller
        self._login_call = login_call or "N0CALL"
        self._loop = loop
        self._client: ClusterClient | None = None
        self._task: asyncio.Task | None = None

        self.setWindowTitle("PartyHams Logger — DX Cluster")
        self.resize(720, 460)

        self._picker = QComboBox()
        for name, host, port in DEFAULT_CLUSTERS:
            self._picker.addItem(f"{name}  ({host}:{port})", (host, port))
        self._picker.addItem("Custom…", None)
        self._picker.currentIndexChanged.connect(self._on_picker_changed)

        self._host_field = QLineEdit()
        self._host_field.setPlaceholderText("host:port")
        self._host_field.setMaximumWidth(180)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._toggle_connect)

        self._status = QLabel("Not connected")

        top = QHBoxLayout()
        top.addWidget(QLabel("Cluster"))
        top.addWidget(self._picker)
        top.addWidget(self._host_field)
        top.addWidget(self._connect_btn)
        top.addWidget(self._status, stretch=1)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.horizontalHeader().setSectionResizeMode(
            len(_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch
        )
        self._table.cellDoubleClicked.connect(self._on_row_activated)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._table, stretch=1)

        self._on_picker_changed()

    # ------------------------------------------------------------------ #
    # connection
    # ------------------------------------------------------------------ #
    def set_poller(self, poller: RadioPoller | None) -> None:
        """Track the app's currently selected radio (called when it changes)."""
        self._poller = poller

    def set_login_call(self, call: str) -> None:
        if call:
            self._login_call = call

    def _on_picker_changed(self) -> None:
        self._host_field.setVisible(self._picker.currentData() is None)

    def _selected_endpoint(self) -> tuple[str, int] | None:
        data = self._picker.currentData()
        if data is not None:
            return data
        text = self._host_field.text().strip()
        if not text:
            return None
        host, sep, port_text = text.partition(":")
        host = host.strip()
        if not host:
            return None
        try:
            port = int(port_text) if sep else 23
        except ValueError:
            return None
        return host, port

    def _toggle_connect(self) -> None:
        if self._task is not None:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        if self._loop is None or not self._loop.is_running():
            self._status.setText("No event loop — cannot connect")
            return
        endpoint = self._selected_endpoint()
        if endpoint is None:
            self._status.setText("Enter a valid host:port")
            return
        host, port = endpoint
        self._client = ClusterClient(
            host, port, self._login_call, on_spot=self._on_spot, on_status=self._set_status
        )
        self._status.setText(f"Connecting to {host}:{port}…")
        self._connect_btn.setText("Disconnect")
        self._task = self._loop.create_task(self._run_client())

    async def _run_client(self) -> None:
        client = self._client
        if client is None:
            return
        try:
            await client.run()
        except Exception as exc:  # noqa: BLE001 - surface, never crash the UI
            self._set_status(f"Cluster error: {exc}")
        finally:
            self._task = None
            self._client = None
            self._connect_btn.setText("Connect")

    def _disconnect(self) -> None:
        if self._client is not None and self._loop is not None:
            self._loop.create_task(self._client.disconnect())
        if self._task is not None:
            self._task.cancel()
        self._task = None
        self._client = None
        self._connect_btn.setText("Connect")
        self._set_status("Disconnected")

    def _set_status(self, message: str) -> None:
        self._status.setText(message)

    # ------------------------------------------------------------------ #
    # spots grid
    # ------------------------------------------------------------------ #
    def _on_spot(self, spot: Spot) -> None:
        self._table.insertRow(0)  # newest on top
        values = [
            spot.time,
            spot.dx_call,
            _freq_mhz(spot.freq_hz),
            spot.band,
            spot.spotter,
            spot.comment,
        ]
        for col, val in enumerate(values):
            item = QTableWidgetItem(val)
            item.setData(_FREQ_ROLE, spot.freq_hz)
            self._table.setItem(0, col, item)
        while self._table.rowCount() > MAX_SPOTS:
            self._table.removeRow(self._table.rowCount() - 1)

    def _on_row_activated(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item is None:
            return
        freq_hz = item.data(_FREQ_ROLE)
        if freq_hz is None:
            return
        poller = self._poller
        if poller is None:
            self._set_status("No radio selected — can't tune")
            return
        if not poller.radio.supports(Capability.FREQUENCY):
            self._set_status("Selected radio can't set frequency")
            return
        if self._loop is None or not self._loop.is_running():
            self._set_status("No event loop — can't tune")
            return
        self._loop.create_task(poller.radio.set_frequency(int(freq_hz)))
        self._set_status(f"Tuned to {_freq_mhz(int(freq_hz))} MHz")
