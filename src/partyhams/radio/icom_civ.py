"""Icom CI-V native backend — validation targets: IC-705 and IC-7610.

One driver for both radios (they share CI-V; only the default address differs).
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
import time
from collections.abc import Callable

from partyhams.radio.base import RadioUnsupported
from partyhams.radio.civ_commands import CivRadio
from partyhams.radio.civ_protocol import (
    ACK_OK,
    CIV_ADDR_IC705,
    CIV_ADDR_IC7610,
    CONTROLLER_ADDR,
    build_frame,
    parse_frames,
)
from partyhams.radio.registry import register

_MODEL_NAMES = {CIV_ADDR_IC705: "IC-705", CIV_ADDR_IC7610: "IC-7610"}


@register
class IcomCIV(CivRadio):
    backend_id = "icom-civ"
    backend_name = "Icom CI-V"

    def __init__(
        self,
        port: str,
        baud: int = 19200,
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
        self._serial = await asyncio.get_running_loop().run_in_executor(None, self._open)

    def _open(self) -> object:
        if self._serial_factory is not None:
            return self._serial_factory()
        import serial  # imported lazily so the headless core needn't have pyserial

        return serial.Serial(self.port, self.baud, timeout=0.2)

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
        serial_obj = self._serial
        serial_obj.write(build_frame(self.civ_address, CONTROLLER_ADDR, payload))
        if not expect:
            return None
        buf = b""
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            chunk = serial_obj.read(64)
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
