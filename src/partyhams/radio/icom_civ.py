"""Icom CI-V native backend — validation targets: IC-705 and IC-7610.

⚠️ **Skeleton.** Declares capabilities and the CI-V framing constants; the serial
read/write and CI-V command encoders are a Phase-1 task. One driver covers both
rigs (they share the CI-V protocol); only the default CI-V address differs.

CI-V frame: ``FE FE <to> <from> <cmd> [data...] FD``. Frequencies are sent as
little-endian BCD. Native (vs. Hamlib) to get fast polling, the spectrum scope
stream, and dual-watch on the IC-7610.
"""

from __future__ import annotations

from partyhams.core.models import Mode
from partyhams.radio.base import Capability, Radio, RadioState
from partyhams.radio.registry import register

# CI-V default transceiver addresses.
CIV_ADDR_IC705 = 0xA4
CIV_ADDR_IC7610 = 0x98
CIV_CONTROLLER_ADDR = 0xE0  # this app, as the controller

# Frame delimiters.
CIV_PREAMBLE = 0xFE
CIV_END = 0xFD


@register
class IcomCIV(Radio):
    backend_id = "icom-civ"
    backend_name = "Icom CI-V"

    def __init__(
        self,
        port: str,
        baud: int = 19200,
        civ_address: int = CIV_ADDR_IC705,
    ) -> None:
        self.port = port  # e.g. "/dev/cu.usbmodem..." (IC-705 USB)
        self.baud = baud
        self.civ_address = civ_address

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
        )
        # Dual receive (sub-receiver) is an IC-7610 feature, not IC-705.
        if self.civ_address == CIV_ADDR_IC7610:
            caps |= Capability.SUB_RECEIVER
        return caps

    async def connect(self) -> None:  # pragma: no cover - Phase-1 driver
        raise NotImplementedError("Icom CI-V driver: Phase 1")

    async def disconnect(self) -> None:  # pragma: no cover
        raise NotImplementedError("Icom CI-V driver: Phase 1")

    async def read_state(self) -> RadioState:  # pragma: no cover
        raise NotImplementedError("Icom CI-V driver: Phase 1")

    async def set_frequency(self, freq_hz: int) -> None:  # pragma: no cover
        raise NotImplementedError("Icom CI-V driver: Phase 1")

    async def set_mode(self, mode: Mode) -> None:  # pragma: no cover
        raise NotImplementedError("Icom CI-V driver: Phase 1")
