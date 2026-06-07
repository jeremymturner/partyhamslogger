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

# Commands
CMD_READ_FREQ = 0x03
CMD_READ_MODE = 0x04
CMD_SET_FREQ = 0x05
CMD_SET_MODE = 0x06
CMD_SEND_CW = 0x17
CMD_PTT = 0x1C  # subcommand 0x00 = TX/RX
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
            return frames, b""
        end = buf.find(bytes([END]), start + 2)
        if end < 0:
            return frames, buf[start:]  # incomplete — keep for next read
        body = buf[start + 2 : end]  # to, from, payload...
        if len(body) >= 3:
            frames.append(Frame(to_addr=body[0], from_addr=body[1], payload=body[2:]))
        buf = buf[end + 1 :]
