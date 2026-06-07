"""FlexRadio native backend (SmartSDR TCP API) — validation target: FLEX-6500.

⚠️ **Skeleton.** Declares the capability set and connection parameters; the
SmartSDR TCP/VITA-49 implementation is a Phase-1 task. Native (vs. Hamlib) because
the Flex API exposes slices, panadapter/spectrum, and streaming meters that the
generic CAT path can't.

SmartSDR discovery: radios announce themselves via UDP broadcast on port 4992;
control is a line-oriented TCP API on port 4992. Each *slice* is an independent
receiver — this backend maps the active slice to the entry window, and additional
slices feed the band map / sub-receiver features.
"""

from __future__ import annotations

from partyhams.core.models import Mode
from partyhams.radio.base import Capability, Radio, RadioState
from partyhams.radio.registry import register

DEFAULT_API_PORT = 4992


@register
class FlexRadio(Radio):
    backend_id = "flex"
    backend_name = "FlexRadio (SmartSDR API)"

    def __init__(self, host: str | None = None, slice_letter: str = "A") -> None:
        # host=None -> use UDP discovery to find a radio on the LAN.
        self.host = host
        self.slice_letter = slice_letter

    @property
    def capabilities(self) -> Capability:
        return (
            Capability.FREQUENCY
            | Capability.MODE
            | Capability.SPLIT
            | Capability.PTT
            | Capability.S_METER
            | Capability.RIT_XIT
            | Capability.SUB_RECEIVER
            | Capability.SPECTRUM
            | Capability.SEND_CW
        )

    async def connect(self) -> None:  # pragma: no cover - Phase-1 driver
        raise NotImplementedError("FlexRadio SmartSDR API driver: Phase 1")

    async def disconnect(self) -> None:  # pragma: no cover
        raise NotImplementedError("FlexRadio SmartSDR API driver: Phase 1")

    async def read_state(self) -> RadioState:  # pragma: no cover
        raise NotImplementedError("FlexRadio SmartSDR API driver: Phase 1")

    async def set_frequency(self, freq_hz: int) -> None:  # pragma: no cover
        raise NotImplementedError("FlexRadio SmartSDR API driver: Phase 1")

    async def set_mode(self, mode: Mode) -> None:  # pragma: no cover
        raise NotImplementedError("FlexRadio SmartSDR API driver: Phase 1")
