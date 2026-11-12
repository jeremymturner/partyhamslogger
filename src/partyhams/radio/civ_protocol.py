"""Icom CI-V wire protocol — pure framing/encoding (no I/O), unit-tested.

A CI-V frame is ``FE FE <to> <from> <payload...> FD``. The controller address is
``0xE0``; the radio's address depends on the model (IC-705 ``0xA4``, IC-7610
``0x98``). Frequencies are 5-byte little-endian BCD. CI-V is a shared bus, so the
controller also hears its own command echoed back — the backend skips any frame
whose ``to`` isn't the controller.
"""

from __future__ import annotations

from dataclasses import dataclass

from partyhams.core.models import Mode

PREAMBLE = b"\xfe\xfe"
END = 0xFD
CONTROLLER_ADDR = 0xE0
CIV_ADDR_IC705 = 0xA4
CIV_ADDR_IC7610 = 0x98
CIV_ADDR_IC7300MK2 = 0xB6  # original IC-7300 is 0x94; the MK2 ships as 0xB6

# Commands
CMD_READ_FREQ = 0x03
CMD_READ_MODE = 0x04
CMD_SET_FREQ = 0x05
CMD_SET_MODE = 0x06
CMD_SEND_CW = 0x17
CMD_PTT = 0x1C  # subcommand 0x00 = TX/RX
CMD_LEVEL = 0x14  # read/set a level; subcommand selects which
SUB_KEYER_SPEED = 0x0C  # keyer speed: level 0000 = 6 WPM … 0255 = 48 WPM
ACK_OK = 0xFB
ACK_NG = 0xFA

# CI-V mode byte <-> our Mode
_CIV_TO_MODE: dict[int, Mode] = {
    0x00: Mode.LSB,
    0x01: Mode.USB,
    0x02: Mode.AM,
    0x03: Mode.CW,
    0x04: Mode.RTTY,
    0x05: Mode.FM,
    0x07: Mode.CW,  # CW-R
    0x08: Mode.RTTY,  # RTTY-R
}
_MODE_TO_CIV: dict[Mode, int] = {
    Mode.LSB: 0x00,
    Mode.USB: 0x01,
    Mode.AM: 0x02,
    Mode.CW: 0x03,
    Mode.RTTY: 0x04,
    Mode.FM: 0x05,
    Mode.FT8: 0x01,  # data-USB
    Mode.FT4: 0x01,
    Mode.PSK31: 0x01,
}


def civ_to_mode(byte: int) -> Mode:
    return _CIV_TO_MODE.get(byte, Mode.USB)


def mode_to_civ(mode: Mode) -> int | None:
    return _MODE_TO_CIV.get(mode)


def freq_to_bcd(hz: int) -> bytes:
    """Encode a frequency (Hz) as 5 little-endian BCD bytes."""
    digits = f"{hz:010d}"  # 10 digits, most significant first
    out = bytearray(5)
    for i in range(5):
        lo = int(digits[9 - i * 2])
        hi = int(digits[9 - i * 2 - 1])
        out[i] = (hi << 4) | lo
    return bytes(out)


def bcd_to_freq(data: bytes) -> int:
    """Decode 5 little-endian BCD bytes into a frequency in Hz."""
    hz = 0
    for i, byte in enumerate(data):
        hz += ((byte & 0x0F) + (byte >> 4) * 10) * (100**i)
    return hz


def build_frame(to_addr: int, from_addr: int, payload: bytes) -> bytes:
    return PREAMBLE + bytes([to_addr, from_addr]) + payload + bytes([END])


@dataclass
class Frame:
    to_addr: int
    from_addr: int
    payload: bytes  # command byte + data (no preamble/addresses/terminator)


def parse_frames(buffer: bytes) -> tuple[list[Frame], bytes]:
    """Pull complete frames out of ``buffer``; return ``(frames, leftover)``."""
    frames: list[Frame] = []
    buf = buffer
    while True:
        start = buf.find(PREAMBLE)
        if start < 0:
            # Keep a trailing lone 0xFE: it may be the first half of the next preamble,
            # split across serial reads. Dropping it loses that whole frame.
            return frames, buf[-1:] if buf.endswith(PREAMBLE[:1]) else b""
        end = buf.find(bytes([END]), start + 2)
        if end < 0:
            return frames, buf[start:]  # incomplete — keep for next read
        body = buf[start + 2 : end]  # to, from, payload...
        if len(body) >= 3:
            frames.append(Frame(to_addr=body[0], from_addr=body[1], payload=body[2:]))
        buf = buf[end + 1 :]


# --- CW keyer ------------------------------------------------------------- #
KEY_SPEED_MIN_WPM = 6
KEY_SPEED_MAX_WPM = 48
#: Most characters one "send CW message" (0x17) command accepts.
CW_MAX_CHARS = 30
# What Icom's keyer can send via 0x17 ("^" joins the next two letters as a prosign).
_CW_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/?.-,:'()=+\"@^ ")


def _level_bcd(level: int) -> bytes:
    """A 0–255 level as Icom's 2-byte big-endian BCD (e.g. 128 -> ``01 28``)."""
    digits = f"{level:04d}"
    return bytes([int(digits[0]) << 4 | int(digits[1]), int(digits[2]) << 4 | int(digits[3])])


def _bcd_level(data: bytes) -> int:
    return int(f"{data[0]:02x}{data[1]:02x}")


def wpm_to_level(wpm: int) -> bytes:
    """Keyer speed in WPM -> the 2-byte BCD level for ``14 0C`` (clamped 6–48)."""
    wpm = max(KEY_SPEED_MIN_WPM, min(KEY_SPEED_MAX_WPM, int(wpm)))
    span = KEY_SPEED_MAX_WPM - KEY_SPEED_MIN_WPM
    return _level_bcd(round((wpm - KEY_SPEED_MIN_WPM) * 255 / span))


def level_to_wpm(data: bytes) -> int:
    """The 2-byte BCD level from a ``14 0C`` reply -> keyer speed in WPM."""
    span = KEY_SPEED_MAX_WPM - KEY_SPEED_MIN_WPM
    return KEY_SPEED_MIN_WPM + round(_bcd_level(data) * span / 255)


def cw_chunks(text: str) -> list[bytes]:
    """Split ``text`` into 0x17-sized pieces of characters the keyer can send.

    Upper-cases, drops anything Icom's keyer can't send (which would otherwise NG
    the whole command), and cuts at :data:`CW_MAX_CHARS`, preferring a space.
    """
    clean = "".join(c for c in text.upper() if c in _CW_CHARS)
    chunks: list[bytes] = []
    while clean:
        if len(clean) <= CW_MAX_CHARS:
            cut = len(clean)
        else:
            space = clean.rfind(" ", 1, CW_MAX_CHARS + 1)
            cut = space if space > 0 else CW_MAX_CHARS
            # Never split "^" from the two letters it joins into a prosign.
            caret = clean.rfind("^", max(0, cut - 2), cut)
            if caret > 0:
                cut = caret
        piece, clean = clean[:cut], clean[cut:]
        if clean.startswith(" ") and len(piece) < CW_MAX_CHARS:
            piece, clean = piece + " ", clean[1:]  # keep the word gap in this piece
        chunks.append(piece.encode("ascii"))
    return chunks
