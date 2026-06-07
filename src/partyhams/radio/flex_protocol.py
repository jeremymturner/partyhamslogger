"""FlexRadio SmartSDR (6000-series) wire protocol — pure parsing/encoding.

Two wire formats, both kept here (no I/O) so they're unit-testable:

* **Discovery** — the radio broadcasts a VITA-49 UDP datagram on port 4992 once a
  second. After a 28-byte VITA header (whose Class ID carries the FlexRadio OUI
  ``0x1C2D``) the payload is an ASCII ``key=value`` string with radio info.

* **TCP control** — a line-oriented ASCII protocol on port 4992:
    - ``V<version>``                     handshake: API version
    - ``H<handle>``                      handshake: our client handle (hex)
    - ``C<seq>|<command>``  (we send)    a command, tagged with a sequence number
    - ``R<seq>|<hexcode>|<message>``     the reply to command ``seq`` (0 == OK)
    - ``S<handle>|<path...> <k=v>...``   an async status update (slice, radio, band)
    - ``M<hexcode>|<text>``              a message from the radio
"""

from __future__ import annotations

from dataclasses import dataclass, field

FLEX_OUI = 0x1C2D  # FlexRadio Systems, in the VITA-49 Class ID
VITA_HEADER_BYTES = 28
DISCOVERY_PORT = 4992
CONTROL_PORT = 4992


# --------------------------------------------------------------------------- #
# Discovery (VITA-49 UDP)
# --------------------------------------------------------------------------- #
def parse_discovery(datagram: bytes) -> dict[str, str] | None:
    """Parse a Flex discovery datagram into a ``key=value`` dict, or None.

    Returns None if the datagram isn't a FlexRadio discovery packet.
    """
    if len(datagram) < VITA_HEADER_BYTES:
        return None
    # Class ID lives in words 2-3; the OUI is the low 24 bits of word 2.
    oui = int.from_bytes(datagram[8:12], "big") & 0x00FFFFFF
    if oui != FLEX_OUI:
        return None
    payload = datagram[VITA_HEADER_BYTES:]
    text = payload.decode("ascii", "ignore").strip("\x00").strip()
    fields = _parse_kv(text)
    return fields or None


def _parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in text.split():
        if "=" in token:
            key, _, value = token.partition("=")
            out[key] = value
    return out


# --------------------------------------------------------------------------- #
# TCP control protocol
# --------------------------------------------------------------------------- #
@dataclass
class VersionLine:
    version: str


@dataclass
class HandleLine:
    handle: str


@dataclass
class ReplyLine:
    seq: int
    code: int  # 0 == success
    message: str


@dataclass
class StatusLine:
    """An ``S`` status update. ``path`` is the non-``k=v`` leading tokens
    (e.g. ``["slice", "0"]`` or ``["radio"]``); ``fields`` is the parsed pairs."""

    handle: str
    path: list[str] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class MessageLine:
    code: int
    text: str


ParsedLine = VersionLine | HandleLine | ReplyLine | StatusLine | MessageLine | None


def parse_line(line: str) -> ParsedLine:
    """Parse one line of the TCP control protocol. None if unrecognized/empty."""
    line = line.rstrip("\r\n")
    if not line:
        return None
    tag, rest = line[0], line[1:]

    if tag == "V":
        return VersionLine(version=rest)
    if tag == "H":
        return HandleLine(handle=rest)
    if tag == "R":
        parts = rest.split("|", 2)
        if len(parts) < 2:
            return None
        seq = _to_int(parts[0])
        code = _hex_to_int(parts[1])
        message = parts[2] if len(parts) > 2 else ""
        return ReplyLine(seq=seq, code=code, message=message)
    if tag == "S":
        handle, _, payload = rest.partition("|")
        path: list[str] = []
        fields: dict[str, str] = {}
        for token in payload.split():
            if "=" in token:
                key, _, value = token.partition("=")
                fields[key] = value
            else:
                path.append(token)
        return StatusLine(handle=handle, path=path, fields=fields)
    if tag == "M":
        code_str, _, text = rest.partition("|")
        return MessageLine(code=_hex_to_int(code_str), text=text)
    return None


def command(seq: int, text: str) -> bytes:
    """Encode a client command (``C<seq>|<text>\\n``)."""
    return f"C{seq}|{text}\n".encode()


# --------------------------------------------------------------------------- #
# Frequency / mode helpers
# --------------------------------------------------------------------------- #
def mhz_to_hz(value: str) -> int:
    try:
        return round(float(value) * 1_000_000)
    except (ValueError, TypeError):
        return 0


def hz_to_mhz(freq_hz: int) -> str:
    return f"{freq_hz / 1_000_000:.6f}"


def _to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return -1


def _hex_to_int(value: str) -> int:
    try:
        return int(value, 16)
    except ValueError:
        return -1
