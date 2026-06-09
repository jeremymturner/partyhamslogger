"""FlexRadio native backend (SmartSDR Ethernet API) — validation target: FLEX-6500.

Native (vs. Hamlib) because the Flex API exposes slices, the panadapter/spectrum,
streaming meters, and band data the generic CAT path can't. This module:

* discovers radios on the LAN from their VITA-49 UDP broadcasts (:func:`discover`),
* opens the line-oriented TCP control connection, does the V/H handshake, and
  subscribes to slice/radio/band status,
* tracks per-slice frequency/mode and band info, exposed via the
  :class:`~partyhams.radio.base.Radio` interface plus Flex-specific getters.

Wire-format parsing lives in :mod:`partyhams.radio.flex_protocol` (unit-tested).
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import time
from dataclasses import dataclass, field

from partyhams.core.models import Band, Mode, band_for_freq
from partyhams.radio.base import Capability, Radio, RadioState, RadioUnsupported
from partyhams.radio.flex_protocol import (
    CONTROL_PORT,
    DISCOVERY_PORT,
    HandleLine,
    MessageLine,
    ReplyLine,
    StatusLine,
    VersionLine,
    command,
    hz_to_mhz,
    mhz_to_hz,
    parse_discovery,
    parse_line,
)
from partyhams.radio.registry import register

# FlexRadio mode token <-> our Mode.
_FLEX_TO_MODE: dict[str, Mode] = {
    "USB": Mode.USB,
    "LSB": Mode.LSB,
    "CW": Mode.CW,
    "AM": Mode.AM,
    "SAM": Mode.AM,
    "FM": Mode.FM,
    "NFM": Mode.FM,
    "DFM": Mode.FM,
    "DIGU": Mode.FT8,
    "DIGL": Mode.FT8,
    "RTTY": Mode.RTTY,
}
_MODE_TO_FLEX: dict[Mode, str] = {
    Mode.USB: "USB",
    Mode.LSB: "LSB",
    Mode.CW: "CW",
    Mode.AM: "AM",
    Mode.FM: "FM",
    Mode.RTTY: "RTTY",
    Mode.FT8: "DIGU",
    Mode.FT4: "DIGU",
    Mode.PSK31: "DIGU",
}


@dataclass
class FlexRadioInfo:
    """Identity/info for a discovered radio (from the discovery broadcast)."""

    model: str = ""
    serial: str = ""
    version: str = ""
    nickname: str = ""
    callsign: str = ""
    ip: str = ""
    port: int = CONTROL_PORT
    raw: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_discovery(cls, fields: dict[str, str], src_ip: str) -> FlexRadioInfo:
        port = fields.get("port", "")
        return cls(
            model=fields.get("model", ""),
            serial=fields.get("serial", ""),
            version=fields.get("version", ""),
            nickname=fields.get("nickname", ""),
            callsign=fields.get("callsign", ""),
            ip=fields.get("ip", src_ip),
            port=int(port) if port.isdigit() else CONTROL_PORT,
            raw=fields,
        )

    def label(self) -> str:
        name = self.nickname or self.callsign or self.model or "FlexRadio"
        return f"{name} ({self.model or 'FlexRadio'} @ {self.ip})"


async def discover(timeout: float = 2.0, port: int = DISCOVERY_PORT) -> list[FlexRadioInfo]:
    """Listen for FlexRadio discovery broadcasts; return the radios seen."""
    loop = asyncio.get_running_loop()
    found: dict[str, FlexRadioInfo] = {}

    class _DiscoveryProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple) -> None:
            fields = parse_discovery(data)
            if fields:
                info = FlexRadioInfo.from_discovery(fields, addr[0])
                found[info.serial or info.ip or addr[0]] = info

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        with contextlib.suppress(OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("", port))
    transport, _ = await loop.create_datagram_endpoint(_DiscoveryProtocol, sock=sock)
    try:
        await asyncio.sleep(timeout)
    finally:
        transport.close()
    return list(found.values())


def discover_sync(timeout: float = 2.0, port: int = DISCOVERY_PORT) -> list[FlexRadioInfo]:
    """Blocking discovery for callers off the asyncio loop (e.g. a Qt dialog).

    Listens for FlexRadio VITA-49 broadcasts on a plain socket so it can run in a
    worker thread without an event loop.
    """
    found: dict[str, FlexRadioInfo] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        with contextlib.suppress(OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    try:
        sock.bind(("", port))
    except OSError:
        sock.close()
        return []
    sock.settimeout(0.3)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            fields = parse_discovery(data)
            if fields:
                info = FlexRadioInfo.from_discovery(fields, addr[0])
                found[info.serial or info.ip or addr[0]] = info
    finally:
        sock.close()
    return list(found.values())


def verify_connectivity(host: str, port: int = CONTROL_PORT, timeout: float = 2.0) -> bool:
    """True if a TCP connection to the radio's control port succeeds."""
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@register
class FlexRadio(Radio):
    backend_id = "flex"
    backend_name = "FlexRadio (SmartSDR API)"

    def __init__(self, host: str | None = None, port: int = CONTROL_PORT) -> None:
        # host=None -> discover a radio on the LAN at connect() time.
        self.host = host
        self.port = port
        self.info: FlexRadioInfo | None = None
        self.version: str = ""
        self.handle: str = ""

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._seq = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._slices: dict[int, dict[str, str]] = {}
        self._radio_status: dict[str, str] = {}
        self._bands: dict[str, dict[str, str]] = {}
        self._ready = asyncio.Event()

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

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> None:
        if self.host is None:
            radios = await discover()
            if not radios:
                raise RadioUnsupported("no FlexRadio found on the network")
            self.info = radios[0]
            self.host, self.port = self.info.ip, self.info.port
        elif self.info is None:
            # Best-effort: pull full identity (model/serial/nickname) from a
            # discovery broadcast matching this host. Broadcast may be blocked, so
            # don't fail the connection if it doesn't arrive.
            with contextlib.suppress(Exception):
                for radio in await discover(timeout=1.5):
                    if radio.ip == self.host:
                        self.info = radio
                        break

        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        self._reader_task = asyncio.create_task(self._read_loop())
        # Subscribe to the data we care about; the radio pushes current state back.
        await self._command("sub slice all")
        await self._command("sub radio all")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._ready.wait(), timeout=2.0)

    async def disconnect(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
        self._reader = self._writer = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    # ------------------------------------------------------------------ #
    # reads (Radio interface)
    # ------------------------------------------------------------------ #
    async def read_state(self) -> RadioState:
        slc = self._active_slice()
        freq = mhz_to_hz(slc.get("RF_frequency", "0"))
        mode = _FLEX_TO_MODE.get(slc.get("mode", "USB"), Mode.USB)
        return RadioState(freq_hz=freq, mode=mode)

    async def set_frequency(self, freq_hz: int) -> None:
        idx = self._active_index()
        if idx is None:
            raise RadioUnsupported("no active slice to tune")
        await self._command(f"slice tune {idx} {hz_to_mhz(freq_hz)}")

    async def set_mode(self, mode: Mode) -> None:
        idx = self._active_index()
        if idx is None:
            raise RadioUnsupported("no active slice")
        flex_mode = _MODE_TO_FLEX.get(mode)
        if flex_mode is None:
            raise RadioUnsupported(f"FlexRadio has no mapping for {mode}")
        await self._command(f"slice set {idx} mode={flex_mode}")

    async def send_cw(self, text: str, wpm: int | None = None) -> None:
        # SmartSDR CWX: spaces must be sent as 0x7F, not a literal space.
        if wpm is not None:
            await self._command(f"cwx wpm {wpm}")
        await self._command("cwx send " + text.replace(" ", "\x7f"))

    async def stop_tx(self) -> None:
        # Clear the CWX buffer — aborts CW in progress (best effort).
        try:
            await self._command("cwx clear")
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Flex-specific info (the point of a native driver)
    # ------------------------------------------------------------------ #
    def description(self) -> str:
        info = self.radio_info()
        parts = ["FlexRadio"]
        if info.model:
            parts.append(info.model)
        if info.nickname and info.nickname != info.model:
            parts.append(f"({info.nickname})")
        text = " ".join(parts)
        where = info.ip or self.host
        return f"{text} @ {where}" if where else text

    def radio_info(self) -> FlexRadioInfo:
        """Identity/info for the connected radio (from discovery + status)."""
        info = self.info or FlexRadioInfo(ip=self.host or "", port=self.port)
        # Enrich from live radio status / the handshake where present.
        for attr in ("model", "callsign", "nickname", "version", "serial"):
            value = self._radio_status.get(attr)
            if value and not getattr(info, attr):
                setattr(info, attr, value)
        if self.version and not info.version:
            info.version = self.version
        return info

    def current_band(self) -> Band | None:
        """The amateur band the active slice is on, derived from its frequency."""
        freq = mhz_to_hz(self._active_slice().get("RF_frequency", "0"))
        return band_for_freq(freq) if freq else None

    def slices(self) -> list[dict]:
        """A summary of each in-use slice: index, freq, mode, band."""
        out: list[dict] = []
        for idx in sorted(self._slices):
            s = self._slices[idx]
            if s.get("in_use") == "0":
                continue
            freq = mhz_to_hz(s.get("RF_frequency", "0"))
            band = band_for_freq(freq)
            out.append(
                {
                    "index": idx,
                    "freq_hz": freq,
                    "mode": _FLEX_TO_MODE.get(s.get("mode", "USB"), Mode.USB),
                    "band": band.label if band else "?",
                    "active": s.get("active") == "1",
                }
            )
        return out

    def bands(self) -> dict[str, dict[str, str]]:
        """Per-band settings the radio has reported (RF power, tune power, etc.)."""
        return dict(self._bands)

    def radio_status(self) -> dict[str, str]:
        """Raw key/value fields from the radio's ``radio`` status object."""
        return dict(self._radio_status)

    def raw_slices(self) -> dict[int, dict[str, str]]:
        """Raw key/value fields per slice (for debugging field names)."""
        return {i: dict(s) for i, s in self._slices.items()}

    # ------------------------------------------------------------------ #
    # protocol plumbing
    # ------------------------------------------------------------------ #
    def _active_index(self) -> int | None:
        in_use = [i for i, s in self._slices.items() if s.get("in_use", "1") != "0"]
        active = [i for i in in_use if self._slices[i].get("active") == "1"]
        if active:
            return min(active)
        if in_use:
            return min(in_use)
        return min(self._slices) if self._slices else None

    def _active_slice(self) -> dict[str, str]:
        idx = self._active_index()
        return self._slices.get(idx, {}) if idx is not None else {}

    async def _command(self, text: str) -> ReplyLine:
        if self._writer is None:
            raise RadioUnsupported("FlexRadio backend is not connected")
        self._seq += 1
        seq = self._seq
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[seq] = fut
        self._writer.write(command(seq, text))
        await self._writer.drain()
        reply: ReplyLine = await asyncio.wait_for(fut, timeout=5.0)
        if reply.code != 0:
            raise OSError(f"FlexRadio error {reply.code} for command: {text}")
        return reply

    async def _read_loop(self) -> None:
        assert self._reader is not None
        while True:
            raw = await self._reader.readline()
            if not raw:
                break
            self._dispatch(parse_line(raw.decode(errors="replace")))

    def _dispatch(self, parsed) -> None:
        if isinstance(parsed, VersionLine):
            self.version = parsed.version
        elif isinstance(parsed, HandleLine):
            self.handle = parsed.handle
        elif isinstance(parsed, ReplyLine):
            fut = self._pending.pop(parsed.seq, None)
            if fut is not None and not fut.done():
                fut.set_result(parsed)
        elif isinstance(parsed, StatusLine):
            self._apply_status(parsed)
        elif isinstance(parsed, MessageLine):
            pass  # informational; surfaced later if needed

    def _apply_status(self, status: StatusLine) -> None:
        if not status.path:
            return
        obj = status.path[0]
        if obj == "slice" and len(status.path) >= 2 and status.path[1].isdigit():
            idx = int(status.path[1])
            if "removed" in status.path:
                self._slices.pop(idx, None)
                return
            self._slices.setdefault(idx, {}).update(status.fields)
            if status.fields.get("RF_frequency"):
                self._ready.set()
        elif obj == "radio":
            self._radio_status.update(status.fields)
        elif obj == "band" and len(status.path) >= 2:
            self._bands.setdefault(status.path[1], {}).update(status.fields)
