"""Icom LAN (UDP) remote-control wire protocol — pure framing, no I/O.

Modern network-equipped Icom rigs (IC-705, IC-7610, IC-9700, IC-7850…) speak a
proprietary UDP protocol, *not* plain CI-V-over-a-socket. There are three streams
on separate UDP ports — control (default 50001), CI-V/"serial" (50002) and audio
(50003). A logger only needs control + CI-V, so the audio stream is never opened.

Every packet starts with a common 16-byte little-endian header
``<len:u32, type:u16, seq:u16, sentid:u32, rcvdid:u32>``. ``sentid`` is our id,
``rcvdid`` is the radio's (learned from its "I am here"). Auth packets carry a
big-endian ``payloadsize``/``innerseq`` and the CI-V data stream wraps raw CI-V
frames (``FE FE … FD``) after a 21-byte data header.

Layouts and the username/password obfuscation table are transcribed from wfview
(GPLv3, Phil Taylor M0VSE et al.) — ``packettypes.h`` / ``icomudpbase.h``. This
module is pure and unit-tested; the transport lives in ``radio/icom_net.py``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

DEFAULT_CONTROL_PORT = 50001

# Common-header packet "type" values (control packets).
TYPE_IDLE = 0x00
TYPE_RETRANSMIT = 0x01
TYPE_AREYOUTHERE = 0x03
TYPE_IAMHERE = 0x04
TYPE_DISCONNECT = 0x05
TYPE_READY = 0x06  # "are you ready" (to radio) / "I am ready" (from radio)
TYPE_PING = 0x07

# Fixed packet lengths (also used to classify inbound packets by size).
CONTROL_SIZE = 0x10
PING_SIZE = 0x15
OPENCLOSE_SIZE = 0x16
TOKEN_SIZE = 0x40
STATUS_SIZE = 0x50
LOGIN_RESPONSE_SIZE = 0x60
LOGIN_SIZE = 0x80
CONNINFO_SIZE = 0x90
CAPABILITIES_SIZE = 0x42
RADIO_CAP_SIZE = 0x66
DATA_HEADER_SIZE = 0x15  # CI-V data packets: 21-byte header then raw CI-V bytes

# token requesttype "magic" values
TOKEN_DELETE = 0x01
TOKEN_CONFIRM = 0x02
TOKEN_RENEW = 0x05

_HEADER = struct.Struct("<IHHII")  # len, type, seq, sentid, rcvdid

# Username/password obfuscation table (wfview icomudpbase.h `passcode`). Indexed
# by (ascii + position); the first 32 and trailing slots are unused (zero).
_PASSCODE_SEQ = bytes(
    [
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0x47, 0x5D, 0x4C, 0x42, 0x66, 0x20, 0x23, 0x46, 0x4E, 0x57, 0x45, 0x3D, 0x67, 0x76, 0x60, 0x41,  # noqa: E501
        0x62, 0x39, 0x59, 0x2D, 0x68, 0x7E, 0x7C, 0x65, 0x7D, 0x49, 0x29, 0x72, 0x73, 0x78, 0x21, 0x6E,  # noqa: E501
        0x5A, 0x5E, 0x4A, 0x3E, 0x71, 0x2C, 0x2A, 0x54, 0x3C, 0x3A, 0x63, 0x4F, 0x43, 0x75, 0x27, 0x79,  # noqa: E501
        0x5B, 0x35, 0x70, 0x48, 0x6B, 0x56, 0x6F, 0x34, 0x32, 0x6C, 0x30, 0x61, 0x6D, 0x7B, 0x2F, 0x4B,  # noqa: E501
        0x64, 0x38, 0x2B, 0x2E, 0x50, 0x40, 0x3F, 0x55, 0x33, 0x37, 0x25, 0x77, 0x24, 0x26, 0x74, 0x6A,  # noqa: E501
        0x28, 0x53, 0x4D, 0x69, 0x22, 0x5C, 0x44, 0x31, 0x36, 0x58, 0x3B, 0x7A, 0x51, 0x5F, 0x52, 0,  # noqa: E501
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    ]
)


def passcode(text: str) -> bytes:
    """Obfuscate a username/password the way the radio expects (max 16 chars)."""
    raw = text.encode("latin-1", "ignore")
    out = bytearray()
    for i, ch in enumerate(raw[:16]):
        p = ch + i
        if p > 126:
            p = 32 + p % 127
        out.append(_PASSCODE_SEQ[p])
    return bytes(out)


def _fixed(text: str, width: int) -> bytes:
    """``text`` as exactly ``width`` bytes (truncated / null-padded)."""
    raw = text.encode("latin-1", "ignore")[:width]
    return raw + b"\x00" * (width - len(raw))


def make_id(local_ip: str, local_port: int) -> int:
    """Compute our ``sentid`` from the local IP's low two octets and port.

    Mirrors wfview: ``octet3 << 24 | octet4 << 16 | (port & 0xffff)``.
    """
    try:
        octets = [int(p) for p in local_ip.split(".")]
    except ValueError:
        octets = []
    if len(octets) != 4:
        octets = [127, 0, 0, 1]
    return ((octets[2] & 0xFF) << 24) | ((octets[3] & 0xFF) << 16) | (local_port & 0xFFFF)


# ---------------------------------------------------------------------- #
# Builders
# ---------------------------------------------------------------------- #
def control(ptype: int, seq: int, sentid: int, rcvdid: int) -> bytes:
    return _HEADER.pack(CONTROL_SIZE, ptype, seq, sentid, rcvdid)


def ping(seq: int, sentid: int, rcvdid: int, reply: int, time_ms: int) -> bytes:
    head = _HEADER.pack(PING_SIZE, TYPE_PING, seq, sentid, rcvdid)
    return head + struct.pack("<BI", reply, time_ms & 0xFFFFFFFF)


def openclose(seq: int, sentid: int, rcvdid: int, sendseq: int, *, close: bool) -> bytes:
    head = _HEADER.pack(OPENCLOSE_SIZE, TYPE_IDLE, seq, sentid, rcvdid)
    magic = 0x00 if close else 0x04
    # data(0x01c0, LE) + unused + sendseq(BE) + magic
    return head + struct.pack("<H", 0x01C0) + b"\x00" + struct.pack(">H", sendseq) + bytes([magic])


def civ_data(seq: int, sentid: int, rcvdid: int, sendseq: int, civ_frame: bytes) -> bytes:
    head = _HEADER.pack(DATA_HEADER_SIZE + len(civ_frame), TYPE_IDLE, seq, sentid, rcvdid)
    inner = struct.pack("<BH", 0xC1, len(civ_frame)) + struct.pack(">H", sendseq)
    return head + inner + civ_frame


def _auth_header(length: int, sentid: int, rcvdid: int, requestreply: int,
                 requesttype: int, innerseq: int, tokrequest: int, token: int) -> bytearray:
    buf = bytearray(length)
    buf[0:16] = _HEADER.pack(length, TYPE_IDLE, 0, sentid, rcvdid)
    struct.pack_into(">I", buf, 0x10, length - 0x10)  # payloadsize (BE)
    buf[0x14] = requestreply
    buf[0x15] = requesttype
    struct.pack_into(">H", buf, 0x16, innerseq & 0xFFFF)  # innerseq (BE)
    struct.pack_into("<H", buf, 0x1A, tokrequest & 0xFFFF)  # tokrequest (LE)
    struct.pack_into("<I", buf, 0x1C, token & 0xFFFFFFFF)  # token (LE)
    return buf


def login(sentid: int, rcvdid: int, innerseq: int, tokrequest: int,
          username: str, password: str, name: str) -> bytes:
    buf = _auth_header(LOGIN_SIZE, sentid, rcvdid, 0x01, 0x00, innerseq, tokrequest, 0)
    user_enc, pass_enc = passcode(username), passcode(password)
    buf[0x40:0x40 + len(user_enc)] = user_enc  # username[16], null-padded
    buf[0x50:0x50 + len(pass_enc)] = pass_enc  # password[16]
    buf[0x60:0x70] = _fixed(name, 16)
    return bytes(buf)


def token(sentid: int, rcvdid: int, innerseq: int, tokrequest: int, tok: int,
          magic: int) -> bytes:
    buf = _auth_header(TOKEN_SIZE, sentid, rcvdid, 0x01, magic, innerseq, tokrequest, tok)
    struct.pack_into(">H", buf, 0x24, 0x0798)  # resetcap (BE) — observed constant
    return bytes(buf)


def conninfo_request(sentid: int, rcvdid: int, innerseq: int, tokrequest: int, tok: int,
                     *, name: str, username: str, use_guid: bool, guid: bytes, mac: bytes,
                     civ_local_port: int, audio_local_port: int) -> bytes:
    """Request the radio open its CI-V (and audio) streams back to our local ports.

    Audio is requested with no codec (control-only); the radio still reports an
    audio port which we ignore.
    """
    buf = _auth_header(CONNINFO_SIZE, sentid, rcvdid, 0x01, 0x03, innerseq, tokrequest, tok)
    if use_guid:
        buf[0x20:0x30] = (guid + b"\x00" * 16)[:16]
    else:
        struct.pack_into("<H", buf, 0x27, 0x8010)  # commoncap
        buf[0x2A:0x30] = (mac + b"\x00" * 6)[:6]
    buf[0x40:0x60] = _fixed(name, 32)
    buf[0x60:0x70] = (passcode(username) + b"\x00" * 16)[:16]
    buf[0x70] = 0x00  # rxenable — control only
    buf[0x71] = 0x00  # txenable
    buf[0x72] = 0x00  # rxcodec  (0 = no audio)
    buf[0x73] = 0x00  # txcodec
    struct.pack_into(">I", buf, 0x74, 0)  # rxsample
    struct.pack_into(">I", buf, 0x78, 0)  # txsample
    struct.pack_into(">I", buf, 0x7C, civ_local_port)
    struct.pack_into(">I", buf, 0x80, audio_local_port)
    struct.pack_into(">I", buf, 0x84, 0)  # txbuffer
    buf[0x88] = 0x01  # convert
    return bytes(buf)


# ---------------------------------------------------------------------- #
# Parsers
# ---------------------------------------------------------------------- #
@dataclass
class Header:
    length: int
    type: int
    seq: int
    sentid: int
    rcvdid: int


def parse_header(data: bytes) -> Header | None:
    if len(data) < CONTROL_SIZE:
        return None
    return Header(*_HEADER.unpack_from(data, 0))


def parse_login_response(data: bytes) -> dict:
    token_val = struct.unpack_from("<I", data, 0x1C)[0]
    tokrequest = struct.unpack_from("<H", data, 0x1A)[0]
    error = struct.unpack_from("<I", data, 0x30)[0]
    connection = data[0x40:0x50].split(b"\x00", 1)[0].decode("latin-1", "ignore")
    return {"token": token_val, "tokrequest": tokrequest, "error": error, "connection": connection}


def parse_status(data: bytes) -> dict:
    error = struct.unpack_from("<I", data, 0x30)[0]
    disc = data[0x40]
    civ_port = struct.unpack_from(">H", data, 0x42)[0]
    audio_port = struct.unpack_from(">H", data, 0x46)[0]
    return {"error": error, "disconnected": disc == 0x01, "civ_port": civ_port,
            "audio_port": audio_port}


def parse_token_response(data: bytes) -> dict:
    return {
        "requestreply": data[0x14],
        "requesttype": data[0x15],
        "tokrequest": struct.unpack_from("<H", data, 0x1A)[0],
        "token": struct.unpack_from("<I", data, 0x1C)[0],
        "response": struct.unpack_from("<I", data, 0x30)[0],
        "sentid": struct.unpack_from("<I", data, 0x08)[0],
    }


@dataclass
class RadioCap:
    name: str
    civ_address: int
    use_guid: bool
    guid: bytes
    mac: bytes
    baudrate: int


def _parse_radio_cap(block: bytes) -> RadioCap:
    commoncap = struct.unpack_from("<H", block, 0x07)[0]
    mac = block[0x0A:0x10]
    guid = block[0x00:0x10]
    name = block[0x10:0x30].split(b"\x00", 1)[0].decode("latin-1", "ignore")
    civ_address = block[0x52]
    baudrate = struct.unpack_from(">I", block, 0x5A)[0]
    use_guid = commoncap != 0x8010
    return RadioCap(name=name, civ_address=civ_address, use_guid=use_guid, guid=guid,
                    mac=mac, baudrate=baudrate)


def parse_capabilities(data: bytes) -> list[RadioCap]:
    """Parse a capabilities packet into the list of radios the server offers."""
    if (len(data) - CAPABILITIES_SIZE) % RADIO_CAP_SIZE != 0:
        return []
    radios = []
    for off in range(CAPABILITIES_SIZE, len(data), RADIO_CAP_SIZE):
        radios.append(_parse_radio_cap(data[off:off + RADIO_CAP_SIZE]))
    return radios


def is_capabilities(data: bytes) -> bool:
    return (
        len(data) >= CAPABILITIES_SIZE + RADIO_CAP_SIZE
        and (len(data) - CAPABILITIES_SIZE) % RADIO_CAP_SIZE == 0
    )


def extract_civ(data: bytes) -> bytes:
    """Raw CI-V bytes carried by a CI-V data packet (everything after the header)."""
    if len(data) <= DATA_HEADER_SIZE:
        return b""
    return data[DATA_HEADER_SIZE:]
