"""Radio-selection screen — shown after a log is set up if no radio is configured.

Separate from log creation on purpose: the radio is a per-station hardware choice,
not part of the log/event. "None" is a valid, remembered answer (manual band/mode).

For FlexRadio the dialog auto-discovers radios on the LAN (populating a dropdown),
lets you type an IP directly, and offers a Verify button to test connectivity. For
Icom CI-V serial it lists the machine's USB serial ports, and Verify checks the rig
actually answers on the chosen one.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from partyhams.radio.icom_kinds import SERIAL_KINDS, TCP_LAN_KINDS, UDP_LAN_KINDS

# Icom kinds reached over the network: native UDP (user/password) or plain TCP CI-V.
_LAN_KINDS = {**UDP_LAN_KINDS, **TCP_LAN_KINDS}
_CIV_BAUD_RATES = (4800, 9600, 19200, 38400, 57600, 115200)
_ICOM_LAN_DEFAULT_PORT = 50001
_SERIAL_PATH = re.compile(r"^(/|com\d+$)", re.IGNORECASE)  # /dev/… or Windows COMn


def _is_serial_path(text: str) -> bool:
    return bool(_SERIAL_PATH.match(text.strip()))


class _DiscoverWorker(QThread):
    """Runs a blocking Flex LAN discovery off the UI thread."""

    found = Signal(list)

    def run(self) -> None:
        from partyhams.radio.flex import discover_sync

        try:
            self.found.emit(discover_sync(timeout=2.0))
        except Exception:  # noqa: BLE001 - discovery never crashes the dialog
            self.found.emit([])


def verify_serial(kind: str, port: str, baud: int | None = None) -> tuple[bool, str]:
    """Check the Icom rig for ``kind`` answers CI-V on serial ``port``.

    ``baud`` None tries the common speeds, like connecting does.
    """
    from partyhams.radio.icom_civ import probe_port

    port = port.strip()
    if not port:
        return False, "pick a serial port"
    try:
        found = probe_port(port, SERIAL_KINDS[kind], baud=baud)
    except OSError as exc:
        text = str(exc).lower()
        # POSIX: our exclusive lock is held; Windows: "Access is denied" = port open.
        if any(s in text for s in ("lock", "busy", "access is denied")):
            return False, f"{port} is in use — already connected, or another program has it"
        return False, f"can't open {port}"
    if found is None:
        speed = f" at {baud} baud" if baud else ""
        return False, f"no CI-V reply on {port}{speed}"
    return True, f"radio answering at {found} baud"


def verify_radio(
    kind: str, conn: str, timeout: float = 2.0, lan_port: int | None = None
) -> bool:
    """Reachability check matching how ``kind`` actually talks to the rig.

    Flex and rigctld are TCP (ports 4992 / 4532); Icom native LAN is UDP 50001 with
    its own "are you there" handshake, so a TCP probe would always fail for it; the
    IC-7300 MK2 LAN is plain TCP. ``conn`` is ``host`` or ``host:port`` (a serial
    port path for CI-V serial kinds); for Icom LAN kinds ``lan_port`` is the port
    field, used when ``conn`` names no port.
    """
    if kind in SERIAL_KINDS:
        return verify_serial(kind, conn)[0]
    host, _, port_str = conn.strip().partition(":")
    host = host.strip()
    port = int(port_str) if port_str.strip().isdigit() else None
    if not host:
        return False
    port = port or lan_port
    if kind in UDP_LAN_KINDS:
        from partyhams.radio.icom_net import verify_reachable
        from partyhams.radio.icom_net_protocol import DEFAULT_CONTROL_PORT

        return verify_reachable(host, port or DEFAULT_CONTROL_PORT, timeout=timeout)
    if kind in TCP_LAN_KINDS:
        from partyhams.radio.icom_tcp import DEFAULT_PORT
        from partyhams.radio.icom_tcp import verify_connectivity as tcp_verify

        return tcp_verify(host, port or DEFAULT_PORT, timeout=timeout)

    from partyhams.radio.flex import verify_connectivity  # generic TCP connect

    default_port = 4532 if kind == "hamlib" else 4992
    return verify_connectivity(host, port or default_port, timeout=timeout)


class _VerifyWorker(QThread):
    """Runs :func:`verify_serial` / :func:`verify_radio` off the UI thread."""

    done = Signal(bool, str)

    def __init__(self, kind: str, conn: str, lan_port: int | None, baud: int | None,
                 parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._conn = conn
        self._lan_port = lan_port
        self._baud = baud

    def run(self) -> None:
        if self._kind in SERIAL_KINDS:
            self.done.emit(*verify_serial(self._kind, self._conn, self._baud))
            return
        host = self._conn.partition(":")[0].strip()
        try:
            ok = verify_radio(self._kind, self._conn, lan_port=self._lan_port)
        except Exception:  # noqa: BLE001 - verify never crashes the dialog
            ok = False
        self.done.emit(ok, f"reachable: {host}" if ok else f"no response: {host}")


class RadioDialog(QDialog):
    def __init__(self, current: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PartyHams Logger — Select Radio")
        self.setMinimumWidth(420)
        self._disc_worker: _DiscoverWorker | None = None
        self._verify_worker: _VerifyWorker | None = None

        self._radio = QComboBox()
        self._radio.addItem("None — manual band/mode", "none")
        self._radio.addItem("Hamlib (rigctld)", "hamlib")
        self._radio.addItem("FlexRadio (native)", "flex")
        self._radio.addItem("Icom IC-705 (CI-V serial)", "icom705")
        self._radio.addItem("Icom IC-7610 (CI-V serial)", "icom7610")
        self._radio.addItem("Icom IC-7300 MK2 (CI-V serial)", "icom7300mk2")
        self._radio.addItem("Icom IC-705 (LAN / Ethernet)", "icom705-lan")
        self._radio.addItem("Icom IC-7610 (LAN / Ethernet)", "icom7610-lan")
        self._radio.addItem("Icom IC-7300 MK2 (LAN / Ethernet)", "icom7300mk2-lan")
        self._conn = QLineEdit()
        self._conn.setEnabled(False)

        # CI-V serial speed (serial kinds). Auto tries the common speeds on connect —
        # a speed that doesn't match the rig's CI-V USB setting just gets silence.
        self._baud = QComboBox()
        self._baud.addItem("Auto (detect)", 0)
        for rate in _CIV_BAUD_RATES:
            self._baud.addItem(str(rate), rate)

        # Icom LAN control port (shown for *-lan kinds; Icom default is 50001).
        self._lan_port = QSpinBox()
        self._lan_port.setRange(1, 65535)
        self._lan_port.setValue(_ICOM_LAN_DEFAULT_PORT)

        self._user = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)

        # FlexRadio discovery row: a dropdown of found radios + a rescan button.
        self._flex_combo = QComboBox()
        self._flex_combo.addItem("(scan to find radios)", "")
        self._flex_combo.currentIndexChanged.connect(lambda _i: self._on_flex_pick())
        self._discover_btn = QPushButton("Rescan")
        self._discover_btn.clicked.connect(self._start_discovery)
        flex_row = QWidget()
        fr = QHBoxLayout(flex_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.addWidget(self._flex_combo, stretch=1)
        fr.addWidget(self._discover_btn)
        self._flex_row = flex_row

        # Serial-port row (CI-V serial): a dropdown of USB serial ports + a rescan button.
        self._port_combo = QComboBox()
        self._port_combo.currentIndexChanged.connect(lambda _i: self._on_port_pick())
        self._port_rescan_btn = QPushButton("Rescan")
        self._port_rescan_btn.clicked.connect(self._scan_ports)
        port_row = QWidget()
        pr = QHBoxLayout(port_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.addWidget(self._port_combo, stretch=1)
        pr.addWidget(self._port_rescan_btn)
        self._port_row = port_row

        # Verify-connectivity row (IP-based connections).
        self._verify_btn = QPushButton("Verify")
        self._verify_btn.clicked.connect(self._verify)
        self._verify_status = QLabel("")
        verify_row = QWidget()
        vr = QHBoxLayout(verify_row)
        vr.setContentsMargins(0, 0, 0, 0)
        vr.addWidget(self._verify_btn)
        vr.addWidget(self._verify_status, stretch=1)
        self._verify_row = verify_row

        if current:
            idx = self._radio.findData(current.get("kind", "none"))
            if idx >= 0:
                self._radio.setCurrentIndex(idx)
            self._conn.setText(current.get("conn", ""))
            baud_idx = self._baud.findData(current.get("baud") or 0)
            if baud_idx >= 0:
                self._baud.setCurrentIndex(baud_idx)
            self._lan_port.setValue(current.get("port", _ICOM_LAN_DEFAULT_PORT))
            self._user.setText(current.get("user", ""))
            self._password.setText(current.get("password", ""))

        info = QLabel(
            "Choose how to read frequency/mode from your rig. You can change this "
            "later, and 'None' is fine — you'll just pick band/mode manually."
        )
        info.setWordWrap(True)

        outer = QVBoxLayout(self)
        outer.addWidget(info)
        self._form = QFormLayout()
        self._form.addRow("Radio", self._radio)
        self._form.addRow("Discovered", self._flex_row)
        self._form.addRow("Serial port", self._port_row)
        self._form.addRow("Connection", self._conn)
        self._form.addRow("Baud rate", self._baud)
        self._form.addRow("Port", self._lan_port)
        self._form.addRow("", self._verify_row)
        self._form.addRow("Username", self._user)
        self._form.addRow("Password", self._password)
        outer.addLayout(self._form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        # Connect only after the form exists — restoring `current` above can fire it.
        self._radio.currentIndexChanged.connect(lambda _i: self._on_radio_changed())
        self.finished.connect(lambda _r: self._stop_workers())
        self._on_radio_changed()

    def _stop_workers(self) -> None:
        # Let in-flight discovery/verify threads finish so they aren't destroyed
        # mid-run (Qt aborts on that). Wait without a limit: each is bounded by its
        # own timeouts (a serial probe of a silent port takes ~4 s), and a timed
        # wait that returns early would bring back that abort.
        for worker in (self._disc_worker, self._verify_worker):
            if worker is not None and worker.isRunning():
                worker.wait()

    # ------------------------------------------------------------------ #
    # per-kind visibility + placeholders
    # ------------------------------------------------------------------ #
    def _on_radio_changed(self) -> None:
        kind = self._radio.currentData()
        is_udp_lan = kind in UDP_LAN_KINDS
        is_tcp_civ_lan = kind in TCP_LAN_KINDS
        is_serial = kind in SERIAL_KINDS
        is_flex = kind == "flex"
        has_lan_port = is_udp_lan or is_tcp_civ_lan
        ip_based = is_flex or has_lan_port or kind == "hamlib"
        self._conn.setEnabled(kind != "none")
        self._form.setRowVisible(self._flex_row, is_flex)
        self._form.setRowVisible(self._port_row, is_serial)
        self._form.setRowVisible(self._baud, is_serial)
        self._form.setRowVisible(self._lan_port, has_lan_port)
        self._form.setRowVisible(self._verify_row, ip_based or is_serial)
        self._form.setRowVisible(self._user, is_udp_lan)
        self._form.setRowVisible(self._password, is_udp_lan)
        self._verify_status.setText("")
        if kind == "hamlib":
            self._conn.setPlaceholderText("rigctld host:port (default 127.0.0.1:4532)")
        elif is_flex:
            self._conn.setPlaceholderText("radio IP (blank = auto-discover)")
        elif is_serial:
            self._conn.setPlaceholderText("serial port (pick above, or type a path)")
        elif is_tcp_civ_lan:
            self._conn.setPlaceholderText("radio IP or hostname")
        elif is_udp_lan:
            self._conn.setPlaceholderText("radio IP or hostname (Network function must be On)")
        else:
            self._conn.setPlaceholderText("")
        if is_flex and self._flex_combo.count() <= 1:
            self._start_discovery()  # auto-discover on first switch to Flex
        # A connection left over from the other family is never right: an IP isn't a
        # serial port, and a /dev path isn't a host.
        conn = self._conn.text().strip()
        if conn and is_serial != _is_serial_path(conn):
            self._conn.clear()
        if is_serial:
            self._scan_ports()
            if not self._conn.text().strip():
                self._on_port_pick()

    # ------------------------------------------------------------------ #
    # serial ports
    # ------------------------------------------------------------------ #
    def _scan_ports(self) -> None:
        from partyhams.radio.icom_civ import list_serial_ports

        try:
            ports = list_serial_ports()
        except Exception:  # noqa: BLE001 - listing never crashes the dialog
            ports = []
        current = self._conn.text().strip()
        self._port_combo.blockSignals(True)
        self._port_combo.clear()
        for sp in ports:
            self._port_combo.addItem(sp.label, sp.device)
        if not ports:
            self._port_combo.addItem("(no USB serial ports found — plug in the radio)", "")
        idx = self._port_combo.findData(current) if current else -1
        if current and idx < 0 and _is_serial_path(current):
            self._port_combo.insertItem(0, current, current)  # typed / not plugged in
            idx = 0
        self._port_combo.setCurrentIndex(max(idx, 0))
        self._port_combo.blockSignals(False)

    def _on_port_pick(self) -> None:
        device = self._port_combo.currentData()
        if device:
            self._conn.setText(device)
            self._verify_status.setText("")

    # ------------------------------------------------------------------ #
    # Flex discovery + verify
    # ------------------------------------------------------------------ #
    def _start_discovery(self) -> None:
        if self._disc_worker is not None and self._disc_worker.isRunning():
            return
        self._discover_btn.setEnabled(False)
        self._verify_status.setText("Scanning…")
        self._disc_worker = _DiscoverWorker(self)
        self._disc_worker.found.connect(self._on_discovered)
        self._disc_worker.start()

    def _on_discovered(self, radios: list) -> None:
        self._discover_btn.setEnabled(True)
        keep = self._conn.text().strip()
        self._flex_combo.blockSignals(True)
        self._flex_combo.clear()
        if radios:
            self._flex_combo.addItem("— pick a discovered radio —", "")
            for r in radios:
                self._flex_combo.addItem(r.label(), r.ip)
            self._verify_status.setText(f"Found {len(radios)} radio(s)")
        else:
            self._flex_combo.addItem("(none found — enter an IP)", "")
            self._verify_status.setText("No radios found")
        self._flex_combo.blockSignals(False)
        self._conn.setText(keep)  # don't clobber a manually typed IP

    def _on_flex_pick(self) -> None:
        ip = self._flex_combo.currentData()
        if ip:
            self._conn.setText(ip)

    def _verify(self) -> None:
        conn = self._conn.text().strip()
        if self._radio.currentData() in SERIAL_KINDS:
            if not conn:
                self._verify_status.setText("Pick a serial port to verify")
                return
        elif not conn.partition(":")[0].strip():
            self._verify_status.setText("Enter an IP to verify")
            return
        if self._verify_worker is not None and self._verify_worker.isRunning():
            return
        kind = self._radio.currentData()
        self._verify_btn.setEnabled(False)
        self._verify_status.setText("Checking…")
        self._verify_worker = _VerifyWorker(
            kind, conn, self._lan_port.value() if kind in _LAN_KINDS else None,
            self._baud.currentData() or None, self,
        )
        self._verify_worker.done.connect(self._on_verified)
        self._verify_worker.start()

    def _on_verified(self, ok: bool, message: str) -> None:
        self._verify_btn.setEnabled(True)
        self._verify_status.setText(f"✓ {message}" if ok else f"✗ {message}")

    def settings(self) -> dict:
        return {
            "kind": self._radio.currentData(),
            "conn": self._conn.text().strip(),
            "baud": self._baud.currentData() or None,
            "port": self._lan_port.value(),
            "user": self._user.text().strip(),
            "password": self._password.text(),
        }
