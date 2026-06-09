"""Telnet DX-cluster client: connect, parse spots, tune the radio.

Parsing is kept pure and unit-testable (:func:`parse_spot`); the transport
(:class:`ClusterClient`) is a thin async wrapper over :func:`asyncio.open_connection`
that logs in, reads lines, parses spots, and fires an ``on_spot`` callback.

A spot line from a DX cluster looks like::

    DX de W3LPL:     14025.0  DX0CALL      CW 599 NICE SIGNAL          1234Z

The numeric field is the spotted frequency in kHz; we convert it to Hz so the
rest of the app (which works in Hz) can tune to it directly.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from partyhams.core.models import band_for_freq

#: Well-known public DX clusters, as ``(name, host, port)``. These are reasonable
#: defaults; live connectivity can't be verified in this environment, so the user
#: can also enter a free-form ``host:port`` in the UI.
DEFAULT_CLUSTERS: list[tuple[str, str, int]] = [
    ("DX Summit / OH2AQ", "dxc.oh2aq.fi", 8000),
    ("VE7CC", "dxc.ve7cc.net", 23),
    ("W3LPL", "w3lpl.net", 7373),
    ("NC7J", "dxc.nc7j.com", 23),
    ("K3LR", "dxc.k3lr.com", 23),
    ("AE5E", "dxc.ae5e.com", 7300),
]

# "DX de <spotter>: <freq-kHz> <dx-call> <comment...> <time>Z". The spotter and
# DX-call fields may carry a trailing ``-#`` SSID or hyphenated suffix; the
# comment is free-form and optional; the trailing time token is ``HHMMZ``.
_SPOT_RE = re.compile(
    r"""^DX\s+de\s+
        (?P<spotter>[A-Za-z0-9/\-]+?):?\s+
        (?P<freq>\d+(?:\.\d+)?)\s+
        (?P<dx>[A-Za-z0-9/]+)
        (?:\s+(?P<comment>.*?))?
        \s*(?P<time>\d{3,4})Z?\s*$
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Spot:
    """A single DX-cluster spot, with the frequency normalised to Hz."""

    spotter: str
    freq_hz: int
    dx_call: str
    comment: str
    time: str  # the cluster's "HHMMZ" timestamp, as sent
    band: str  # band label (e.g. "20m"), or "?" if out of band


def parse_spot(line: str) -> Spot | None:
    """Parse one DX-cluster line into a :class:`Spot`, or ``None`` if it isn't one.

    Handles varying whitespace and an optional colon after the spotter. The
    frequency is given in kHz on the wire and converted to Hz. Non-spot lines
    (login prompts, chatter, WWV/WCY bulletins) return ``None``.
    """
    text = line.strip()
    if not text.upper().startswith("DX DE"):
        return None
    match = _SPOT_RE.match(text)
    if match is None:
        return None
    try:
        freq_khz = float(match.group("freq"))
    except ValueError:
        return None
    freq_hz = int(round(freq_khz * 1000))
    if freq_hz <= 0:
        return None
    band = band_for_freq(freq_hz)
    comment = (match.group("comment") or "").strip()
    return Spot(
        spotter=match.group("spotter").upper(),
        freq_hz=freq_hz,
        dx_call=match.group("dx").upper(),
        comment=comment,
        time=f"{match.group('time')}Z",
        band=band.label if band is not None else "?",
    )


# A login prompt typically asks for a call ("login:", "Please enter your call",
# "callsign:"). We answer the first such prompt with our callsign.
_LOGIN_RE = re.compile(r"(login|call(sign)?|enter your call)", re.IGNORECASE)

OnSpot = Callable[[Spot], None] | Callable[[Spot], Awaitable[None]]


class ClusterClient:
    """Async telnet DX-cluster client.

    Connects to ``host:port``, sends ``login_call`` when the cluster prompts for
    a login, then reads lines, parses spots, and invokes ``on_spot`` for each.
    Disconnects are graceful: :meth:`run` returns when the peer closes the stream
    or :meth:`disconnect` is called.

    Live connectivity to real clusters can't be verified in this environment; the
    parsing and the login/read loop are exercised against a fake server in tests.
    """

    def __init__(
        self,
        host: str,
        port: int,
        login_call: str,
        on_spot: OnSpot | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.login_call = login_call
        self.on_spot = on_spot
        self.on_status = on_status
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._logged_in = False
        self._running = False

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        self._logged_in = False
        self._status(f"Connected to {self.host}:{self.port}")

    async def run(self) -> None:
        """Read lines until the stream closes or :meth:`disconnect` is called."""
        if self._reader is None:
            await self.connect()
        assert self._reader is not None
        self._running = True
        try:
            while self._running:
                raw = await self._reader.readline()
                if not raw:
                    break  # peer closed the connection
                line = raw.decode(errors="replace").rstrip("\r\n")
                await self._handle_line(line)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._running = False
            self._status("Disconnected")

    async def _handle_line(self, line: str) -> None:
        if not self._logged_in and _LOGIN_RE.search(line):
            await self._send_login()
            return
        spot = parse_spot(line)
        if spot is None or self.on_spot is None:
            return
        result = self.on_spot(spot)
        if asyncio.iscoroutine(result):
            await result

    async def _send_login(self) -> None:
        if self._writer is None:
            return
        self._writer.write(f"{self.login_call}\r\n".encode())
        await self._writer.drain()
        self._logged_in = True
        self._status(f"Logged in as {self.login_call}")

    async def disconnect(self) -> None:
        self._running = False
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        self._reader = self._writer = None

    def _status(self, message: str) -> None:
        if self.on_status is not None:
            self.on_status(message)
