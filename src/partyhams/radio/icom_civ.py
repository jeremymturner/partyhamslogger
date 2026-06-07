"""Icom CI-V native backend — validation targets: IC-705 and IC-7610.

One driver for both radios (they share CI-V; only the default address differs).
Talks the CI-V serial protocol (``radio/civ_protocol.py``) over a USB/serial port
via pyserial. Serial I/O is blocking, so each transaction runs in a thread executor
to keep the asyncio loop responsive; transactions are serialized with a lock.

Native (vs. Hamlib) for fast polling, the spectrum scope, and dual-watch on the
IC-7610.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from partyhams.core.models import Mode
from partyhams.radio.base import Capability, Radio, RadioState, RadioUnsupported
from partyhams.radio.civ_protocol import (
    ACK_OK,
    CIV_ADDR_IC705,
    CIV_ADDR_IC7610,
    CMD_PTT,
    CMD_READ_FREQ,
    CMD_READ_MODE,
    CMD_SEND_CW,
    CMD_SET_FREQ,
    CMD_SET_MODE,
    CONTROLLER_ADDR,
    bcd_to_freq,
    build_frame,
    civ_to_mode,
    freq_to_bcd,
    mode_to_civ,
    parse_frames,
)
from partyhams.radio.registry import register

_MODEL_NAMES = {CIV_ADDR_IC705: "IC-705", CIV_ADDR_IC7610: "IC-7610"}


@register
class IcomCIV(Radio):
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

    @property
    def capabilities(self) -> Capability:
        caps = (
            Capability.FREQUENCY
            | Capability.MODE
            | Capability.VFO_AB
            | Capability.SPLIT
            | Capability.PTT
            | Capability.S_METER
            | Capability.RIT_XIT
            | Capability.SPECTRUM
            | Capability.SEND_CW
        )
        if self.civ_address == CIV_ADDR_IC7610:
            caps |= Capability.SUB_RECEIVER  # dual receive
        return caps

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
    # Radio interface
    # ------------------------------------------------------------------ #
    async def read_state(self) -> RadioState:
        freq_payload = await self._transact(bytes([CMD_READ_FREQ]), response_cmd=CMD_READ_FREQ)
        mode_payload = await self._transact(bytes([CMD_READ_MODE]), response_cmd=CMD_READ_MODE)
        freq = bcd_to_freq(freq_payload[1:6]) if freq_payload and len(freq_payload) >= 6 else 0
        mode = civ_to_mode(mode_payload[1]) if mode_payload and len(mode_payload) >= 2 else Mode.USB
        return RadioState(freq_hz=freq, mode=mode)

    async def set_frequency(self, freq_hz: int) -> None:
        await self._transact(bytes([CMD_SET_FREQ]) + freq_to_bcd(freq_hz), ack=True)

    async def set_mode(self, mode: Mode) -> None:
        civ = mode_to_civ(mode)
        if civ is None:
            raise RadioUnsupported(f"Icom CI-V has no mapping for {mode}")
        await self._transact(bytes([CMD_SET_MODE, civ]), ack=True)

    async def set_ptt(self, on: bool) -> None:
        await self._transact(bytes([CMD_PTT, 0x00, 0x01 if on else 0x00]), ack=True)

    async def send_cw(self, text: str, wpm: int | None = None) -> None:
        # CI-V "send CW message" (0x17) + ASCII; the radio keys it at its set speed.
        await self._transact(bytes([CMD_SEND_CW]) + text.encode("ascii", "ignore"), expect=False)

    async def stop_tx(self) -> None:
        # 0x17 0xFF cancels CW; then drop PTT — best effort.
        try:
            await self._transact(bytes([CMD_SEND_CW, 0xFF]), expect=False)
        except OSError:
            pass
        try:
            await self._transact(bytes([CMD_PTT, 0x00, 0x00]), ack=True)
        except OSError:
            pass

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
