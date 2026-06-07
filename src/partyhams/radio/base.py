"""The radio backend interface and shared types.

Backends are async (CAT I/O is inherently I/O-bound and we run on an asyncio loop
bridged to Qt via qasync). A backend advertises its :class:`Capability` set so the
UI can disable controls a given rig/backend can't do (e.g. no sub-receiver).
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass

from partyhams.core.models import Mode


class Capability(enum.Flag):
    """What a backend/rig can do. Combined with ``|``; tested with ``in``."""

    NONE = 0
    FREQUENCY = enum.auto()
    MODE = enum.auto()
    VFO_AB = enum.auto()
    SPLIT = enum.auto()
    PTT = enum.auto()
    S_METER = enum.auto()
    RIT_XIT = enum.auto()
    SEND_CW = enum.auto()
    SUB_RECEIVER = enum.auto()  # Flex slices / IC-7610 dual receive
    SPECTRUM = enum.auto()


class RadioUnsupported(Exception):
    """Raised when a backend is asked to do something it doesn't support."""


@dataclass
class RadioState:
    """A snapshot of the radio's relevant state."""

    freq_hz: int = 0
    mode: Mode = Mode.CW
    vfo: str = "A"
    split: bool = False
    ptt: bool = False
    s_meter_db: int | None = None  # dB relative to S9, if available


class Radio(ABC):
    """Abstract CAT backend. One instance controls one radio."""

    #: Stable backend id, e.g. ``"hamlib"``.
    backend_id: str = ""
    #: Human-readable backend name.
    backend_name: str = ""

    @property
    @abstractmethod
    def capabilities(self) -> Capability:
        """The capability set for this backend/connection."""

    def supports(self, cap: Capability) -> bool:
        return cap in self.capabilities

    @abstractmethod
    async def connect(self) -> None:
        """Open the connection to the radio."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection."""

    @abstractmethod
    async def read_state(self) -> RadioState:
        """Poll current frequency/mode/etc. (used to auto-fill the entry window)."""

    @abstractmethod
    async def set_frequency(self, freq_hz: int) -> None:
        """QSY the active VFO (e.g. click-to-tune from the band map)."""

    @abstractmethod
    async def set_mode(self, mode: Mode) -> None:
        """Set the operating mode."""

    async def set_ptt(self, on: bool) -> None:
        """Key/unkey the transmitter. Override if ``Capability.PTT`` is advertised."""
        raise RadioUnsupported(f"{self.backend_name} does not support PTT")

    async def send_cw(self, text: str, wpm: int | None = None) -> None:
        """Send CW via the rig's keyer. Override if ``Capability.SEND_CW``."""
        raise RadioUnsupported(f"{self.backend_name} does not support CW keying")
