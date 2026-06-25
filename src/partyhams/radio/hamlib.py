"""Hamlib backend — the universal base, via a ``rigctld`` TCP connection.

Covers hundreds of radios (the Yaesu FT-891 is our validation target). Talks to a
running ``rigctld`` daemon over its text protocol, using the *extended* response
mode (commands prefixed with ``+``) so every reply is terminated by an ``RPRT``
line and is therefore unambiguous to parse.

Start the daemon with e.g. ``rigctld -m 1041 -r /dev/cu.usbserial-XXXX -s 38400``
(``-m 1041`` = FT-891). The app connects to ``localhost:4532`` by default.
"""

from __future__ import annotations

import asyncio

from partyhams.core.models import Mode
from partyhams.radio.base import Capability, Radio, RadioState, RadioUnsupported
from partyhams.radio.registry import register

# our Mode -> hamlib mode token
_TO_HAMLIB: dict[Mode, str] = {
    Mode.CW: "CW",
    Mode.USB: "USB",
    Mode.LSB: "LSB",
    Mode.FM: "FM",
    Mode.AM: "AM",
    Mode.RTTY: "RTTY",
    Mode.PSK31: "PKTUSB",
    Mode.FT8: "PKTUSB",
    Mode.FT4: "PKTUSB",
}

def _looks_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


# hamlib mode token -> our Mode (best effort; passband is ignored)
_FROM_HAMLIB: dict[str, Mode] = {
    "CW": Mode.CW,
    "CWR": Mode.CW,
    "USB": Mode.USB,
    "LSB": Mode.LSB,
    "FM": Mode.FM,
    "AM": Mode.AM,
    "RTTY": Mode.RTTY,
    "RTTYR": Mode.RTTY,
    "PKTUSB": Mode.FT8,
    "PKTLSB": Mode.FT8,
}


@register
class HamlibRadio(Radio):
    backend_id = "hamlib"
    backend_name = "Hamlib (rigctld)"

    def __init__(self, host: str = "127.0.0.1", port: int = 4532) -> None:
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        # Once a KEYSPD level read fails, stop polling it (rig lacks the level) so
        # read_state() doesn't pay a failing round-trip on every poll.
        self._keyspd_ok = True

    @property
    def capabilities(self) -> Capability:
        return (
            Capability.FREQUENCY
            | Capability.MODE
            | Capability.VFO_AB
            | Capability.SPLIT
            | Capability.PTT
            | Capability.S_METER
            | Capability.SEND_CW
            | Capability.KEYER_SPEED
        )

    def description(self) -> str:
        return f"Hamlib @ {self.host}:{self.port}"

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)

    async def disconnect(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = self._writer = None

    async def read_state(self) -> RadioState:
        freq_fields = await self._command("f")
        mode_fields = await self._command("m")
        freq_hz = int(freq_fields.get("Frequency", "0"))
        mode_token = mode_fields.get("Mode", "CW")
        return RadioState(
            freq_hz=freq_hz,
            mode=_FROM_HAMLIB.get(mode_token, Mode.CW),
            wpm=await self._poll_wpm(),
        )

    async def _poll_wpm(self) -> int | None:
        """Best-effort KEYSPD read for read_state; latches off on first failure so
        a rig without a keyer-speed level isn't probed on every poll."""
        if not self._keyspd_ok:
            return None
        try:
            return await self.read_wpm()
        except OSError:
            self._keyspd_ok = False
            return None

    async def set_frequency(self, freq_hz: int) -> None:
        await self._command(f"F {freq_hz}")

    async def set_mode(self, mode: Mode) -> None:
        token = _TO_HAMLIB.get(mode)
        if token is None:
            raise RadioUnsupported(f"hamlib mapping missing for mode {mode}")
        # Passband 0 == let the rig pick its default.
        await self._command(f"M {token} 0")

    async def set_ptt(self, on: bool) -> None:
        await self._command(f"T {1 if on else 0}")

    async def send_cw(self, text: str, wpm: int | None = None) -> None:
        if wpm is not None:
            await self._command(f"L KEYSPD {wpm}")
        await self._command(f"b {text}")

    async def read_wpm(self) -> int | None:
        """Read the keyer speed via ``l KEYSPD``. Returns ``None`` if the rig
        reports no usable value (real rigctld labels the value ``KEYSPD: <n>``;
        this path is unverified against hardware)."""
        fields = await self._command("l KEYSPD")
        raw = fields.get("KEYSPD")
        if raw is None:
            raw = next((v for v in fields.values() if _looks_numeric(v)), None)
        if raw is None:
            return None
        try:
            return int(round(float(raw)))
        except ValueError:
            return None

    async def set_wpm(self, wpm: int) -> None:
        await self._command(f"L KEYSPD {int(wpm)}")

    async def stop_tx(self) -> None:
        # Abort CW being keyed (\stop_morse), then drop PTT — best effort.
        for cmd in ("\\stop_morse", "T 0"):
            try:
                await self._command(cmd)
            except OSError:
                pass

    # --- protocol plumbing ---
    async def _command(self, cmd: str) -> dict[str, str]:
        """Send one extended-mode command; return parsed ``Key: value`` fields.

        Raises on transport loss or a non-zero ``RPRT`` return code.
        """
        if self._reader is None or self._writer is None:
            raise RadioUnsupported("hamlib backend is not connected")
        async with self._lock:
            self._writer.write(f"+{cmd}\n".encode())
            await self._writer.drain()
            fields: dict[str, str] = {}
            while True:
                raw = await self._reader.readline()
                if not raw:
                    raise ConnectionError("rigctld closed the connection")
                line = raw.decode(errors="replace").strip()
                if line.startswith("RPRT"):
                    code = int(line.split()[1])
                    if code != 0:
                        raise OSError(f"rigctld error {code} for command {cmd!r}")
                    return fields
                if ":" in line:
                    key, _, value = line.partition(":")
                    value = value.strip()
                    if value:  # skip the echoed command header line ("get_freq:")
                        fields[key.strip()] = value
