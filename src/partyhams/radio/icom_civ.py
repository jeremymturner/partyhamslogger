"""Icom CI-V native backend — validation targets: IC-705, IC-7610, IC-7300 MK2.

One driver for all of them (they share CI-V; only the default address differs).
Talks the CI-V serial protocol (``radio/civ_protocol.py``) over a USB/serial port
via pyserial. Serial I/O is blocking, so each transaction runs in a thread executor
to keep the asyncio loop responsive; transactions are serialized with a lock.

The CI-V command set itself lives in :class:`~partyhams.radio.civ_commands.CivRadio`
and is shared with the network backend (``radio/icom_net.py``); this module only
provides the serial transport.

Native (vs. Hamlib) for fast polling, the spectrum scope, and dual-watch on the
IC-7610.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from partyhams.radio.base import RadioUnsupported
from partyhams.radio.civ_commands import CivRadio
from partyhams.radio.civ_protocol import (
    ACK_OK,
    CIV_ADDR_IC705,
    CIV_ADDR_IC7300MK2,
    CIV_ADDR_IC7610,
    CMD_READ_FREQ,
    CONTROLLER_ADDR,
    build_frame,
    parse_frames,
)
from partyhams.radio.registry import register

log = logging.getLogger(__name__)

# CI-V USB speeds to try when none is configured, most common first. Icom rigs default
# to "Auto" on USB, but many owners (and wfview's setup guide) pin 115200, and a fixed
# speed that doesn't match the rig gives total silence rather than an error.
AUTO_BAUDS = (115200, 19200, 9600, 38400, 57600, 4800)

_MODEL_NAMES = {
    CIV_ADDR_IC705: "IC-705",
    CIV_ADDR_IC7610: "IC-7610",
    CIV_ADDR_IC7300MK2: "IC-7300 MK2",
}


@register
class IcomCIV(CivRadio):
    backend_id = "icom-civ"
    backend_name = "Icom CI-V"

    def __init__(
        self,
        port: str,
        baud: int | None = None,  # None = auto-detect on connect (see AUTO_BAUDS)
        civ_address: int = CIV_ADDR_IC705,
        serial_factory: Callable[[], object] | None = None,
    ) -> None:
        self.port = port  # e.g. "/dev/cu.usbmodem..." (IC-705 USB)
        self.baud = baud
        self.civ_address = civ_address
        self._serial_factory = serial_factory  # injected in tests
        self._serial: object | None = None
        self._lock = asyncio.Lock()

    def description(self) -> str:
        model = _MODEL_NAMES.get(self.civ_address, "CI-V")
        return f"Icom {model} @ {self.port}"

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> None:
        loop = asyncio.get_running_loop()
        self._wpm_misses = 0
        serial_obj = await loop.run_in_executor(None, self._open)
        try:
            baud = await loop.run_in_executor(None, self._find_baud, serial_obj)
        except BaseException:
            await loop.run_in_executor(None, serial_obj.close)
            raise
        log.debug("CI-V %s answering at %d baud", self.port, baud)
        self.baud = baud
        self._serial = serial_obj

    def _open(self) -> object:
        if self._serial_factory is not None:
            return self._serial_factory()
        import serial  # imported lazily so the headless core needn't have pyserial

        # Open with RTS/DTR held low: pyserial raises both by default, and many rigs
        # (IC-7610 "USB SEND"/"USB Keying") can be set to key the transmitter on them.
        # Lock the port (POSIX; Windows ports are always exclusive) so a second user —
        # e.g. the radio dialog's Verify — can't open it and steal our replies.
        serial_obj = serial.Serial()
        serial_obj.port = self.port
        serial_obj.baudrate = self.baud or AUTO_BAUDS[0]
        serial_obj.timeout = 0.2
        serial_obj.rts = False
        serial_obj.dtr = False
        serial_obj.exclusive = True
        serial_obj.open()
        return serial_obj

    def _find_baud(self, serial_obj) -> int:
        """Return the first speed at which the rig answers "read frequency"."""
        candidates = (self.baud,) if self.baud else AUTO_BAUDS
        for baud in candidates:
            serial_obj.baudrate = baud
            if hasattr(serial_obj, "reset_input_buffer"):
                serial_obj.reset_input_buffer()
            if self._exchange(serial_obj, bytes([CMD_READ_FREQ]), CMD_READ_FREQ, False, True):
                return baud
        tried = ", ".join(str(b) for b in candidates)
        raise OSError(
            f"no CI-V reply from {self.port} (tried {tried} baud) — check it's the rig's "
            f"CI-V port and the CI-V address is {self.civ_address:#04x}"
        )

    async def disconnect(self) -> None:
        serial_obj = self._serial
        self._serial = None
        if serial_obj is not None:
            await asyncio.get_running_loop().run_in_executor(None, serial_obj.close)

    # ------------------------------------------------------------------ #
    # transport
    # ------------------------------------------------------------------ #
    async def _transact(
        self,
        payload: bytes,
        response_cmd: int | None = None,
        ack: bool = False,
        expect: bool = True,
    ) -> bytes | None:
        if self._serial is None:
            raise RadioUnsupported("Icom CI-V backend is not connected")
        async with self._lock:
            return await asyncio.get_running_loop().run_in_executor(
                None, self._transact_sync, payload, response_cmd, ack, expect
            )

    def _transact_sync(
        self, payload: bytes, response_cmd: int | None, ack: bool, expect: bool
    ) -> bytes | None:
        return self._exchange(self._serial, payload, response_cmd, ack, expect)

    def _exchange(
        self, serial_obj, payload: bytes, response_cmd: int | None, ack: bool, expect: bool
    ) -> bytes | None:
        # Drop anything left from an earlier command we didn't wait on (e.g. the ACK
        # to a fire-and-forget set_wpm), so it can't be taken as this one's reply.
        if hasattr(serial_obj, "reset_input_buffer"):
            serial_obj.reset_input_buffer()
        serial_obj.write(build_frame(self.civ_address, CONTROLLER_ADDR, payload))
        if not expect:
            return None
        buf = b""
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            # Read what has arrived (min 1 byte). A fixed read(64) blocks for the whole
            # port timeout whenever the reply is shorter — ~200 ms per command.
            chunk = serial_obj.read(getattr(serial_obj, "in_waiting", 0) or 1)
            if not chunk:
                continue
            buf += chunk
            frames, buf = parse_frames(buf)
            for frame in frames:
                if frame.to_addr != CONTROLLER_ADDR or not frame.payload:
                    continue  # skip the command echo and frames for others
                if ack and frame.payload[0] in (ACK_OK, 0xFA):
                    return frame.payload
                if not ack and response_cmd is not None and frame.payload[0] == response_cmd:
                    return frame.payload
        return None


# ---------------------------------------------------------------------- #
# port discovery + verify (used by the radio dialog)
# ---------------------------------------------------------------------- #
_ICOM_USB_VID = 0x0C26  # Icom's own USB vendor ID (e.g. IC-705)


@dataclass(frozen=True)
class SerialPort:
    device: str  # what goes in the connection field, e.g. "/dev/cu.usbserial-123220"
    label: str  # human-readable dropdown text
    is_icom: bool  # looks like an Icom rig's USB port


def _port_rank(device: str) -> int:
    # macOS lists each USB serial port twice (cu./tty.); the cu. node is the one to
    # use. Prefer the built-in driver's usbserial-/usbmodem names over vendor aliases.
    name = device.rsplit("/", 1)[-1]
    return 0 if name.startswith(("cu.usbserial", "cu.usbmodem")) else 1


def list_serial_ports(comports: Callable[[], list] | None = None) -> list[SerialPort]:
    """USB serial ports, Icom-looking ones first, one entry per physical port.

    ``comports`` is ``serial.tools.list_ports.comports`` (injected in tests). Ports
    with no hardware ID (Bluetooth, debug consoles) are skipped, and duplicate device
    nodes for the same physical port are collapsed.
    """
    if comports is None:
        try:
            from serial.tools.list_ports import comports
        except ImportError:
            return []
    best: dict[str, object] = {}
    for p in comports():
        if not p.hwid or p.hwid == "n/a" or "/tty." in p.device:
            continue
        key = p.hwid
        if key not in best or _port_rank(p.device) < _port_rank(best[key].device):
            best[key] = p
    ports = []
    for p in best.values():
        serial_no = p.serial_number or ""
        is_icom = p.vid == _ICOM_USB_VID or serial_no.startswith("IC-")
        name = serial_no if serial_no.startswith("IC-") else (p.product or p.description)
        label = f"{name} — {p.device}" if name and name != "n/a" else p.device
        ports.append(SerialPort(p.device, label, is_icom))
    ports.sort(key=lambda sp: (not sp.is_icom, sp.label))
    return ports


def probe_port(
    port: str,
    civ_address: int,
    serial_factory: Callable[[], object] | None = None,
    baud: int | None = None,
) -> int | None:
    """Blocking check: the CI-V speed ``port`` answers at for ``civ_address``, or None.

    Opens the port (locked, RTS/DTR low) and sends only "read frequency" — never
    transmits. Raises ``OSError`` if the port can't be opened, including when it is
    busy because this app (or another program) already has it.
    """
    radio = IcomCIV(port, baud=baud, civ_address=civ_address, serial_factory=serial_factory)
    serial_obj = radio._open()
    try:
        return radio._find_baud(serial_obj)
    except OSError:
        return None
    finally:
        serial_obj.close()
