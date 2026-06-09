"""Unit tests for the pure Icom LAN protocol (passcode + packet build/parse)."""

from __future__ import annotations

import struct

from partyhams.radio import icom_net_protocol as p


def test_passcode_known_vectors():
    # Hand-computed from the obfuscation table: out[i] = seq[ascii[i] + i].
    assert p.passcode("A") == bytes([0x5E])
    assert p.passcode("AB") == bytes([0x5E, 0x3E])
    # Empty in, empty out; length is capped at 16.
    assert p.passcode("") == b""
    assert len(p.passcode("X" * 40)) == 16


def test_passcode_wraps_above_126():
    # ascii + position can exceed 126 and must wrap into the table, not crash.
    assert len(p.passcode("~~~~")) == 4


def test_make_id():
    # octet3<<24 | octet4<<16 | port
    assert p.make_id("192.168.1.50", 0x1234) == (1 << 24) | (50 << 16) | 0x1234
    assert p.make_id("bogus", 7) == (0 << 24) | (1 << 16) | 7  # falls back to 127.0.0.1


def test_control_roundtrip():
    pkt = p.control(p.TYPE_AREYOUTHERE, seq=0, sentid=0xAABBCCDD, rcvdid=0)
    assert len(pkt) == p.CONTROL_SIZE
    h = p.parse_header(pkt)
    assert (h.length, h.type, h.sentid, h.rcvdid) == (0x10, p.TYPE_AREYOUTHERE, 0xAABBCCDD, 0)


def test_ping_layout():
    pkt = p.ping(seq=5, sentid=1, rcvdid=2, reply=0, time_ms=0x01020304)
    assert len(pkt) == p.PING_SIZE
    assert pkt[0x10] == 0  # reply byte
    assert struct.unpack_from("<I", pkt, 0x11)[0] == 0x01020304


def test_openclose_layout():
    pkt = p.openclose(seq=0, sentid=1, rcvdid=2, sendseq=0x0009, close=False)
    assert len(pkt) == p.OPENCLOSE_SIZE
    assert struct.unpack_from("<H", pkt, 0x10)[0] == 0x01C0
    assert struct.unpack_from(">H", pkt, 0x13)[0] == 0x0009  # sendseq is big-endian
    assert pkt[0x15] == 0x04  # open magic (0x00 = close)
    assert p.openclose(0, 1, 2, 0, close=True)[0x15] == 0x00


def test_civ_data_wraps_frame():
    frame = bytes([0xFE, 0xFE, 0xA4, 0xE0, 0x03, 0xFD])
    pkt = p.civ_data(seq=1, sentid=1, rcvdid=2, sendseq=0x0007, civ_frame=frame)
    h = p.parse_header(pkt)
    assert h.length == p.DATA_HEADER_SIZE + len(frame)
    assert pkt[0x10] == 0xC1
    assert struct.unpack_from("<H", pkt, 0x11)[0] == len(frame)  # datalen (LE)
    assert struct.unpack_from(">H", pkt, 0x13)[0] == 0x0007  # sendseq (BE)
    assert p.extract_civ(pkt) == frame


def test_login_layout():
    pkt = p.login(sentid=1, rcvdid=2, innerseq=3, tokrequest=0x4321,
                  username="user", password="pass", name="pc-app")
    assert len(pkt) == p.LOGIN_SIZE
    assert pkt[0x15] == 0x00  # requesttype = login
    assert struct.unpack_from(">I", pkt, 0x10)[0] == p.LOGIN_SIZE - 0x10  # payloadsize BE
    assert struct.unpack_from(">H", pkt, 0x16)[0] == 3  # innerseq BE
    assert struct.unpack_from("<H", pkt, 0x1A)[0] == 0x4321  # tokrequest LE
    assert pkt[0x40:0x44] == p.passcode("user")
    assert pkt[0x50:0x54] == p.passcode("pass")
    assert pkt[0x60:0x66] == b"pc-app"


def test_token_layout():
    pkt = p.token(sentid=1, rcvdid=2, innerseq=4, tokrequest=0x1111, tok=0xDEADBEEF,
                  magic=p.TOKEN_CONFIRM)
    assert len(pkt) == p.TOKEN_SIZE
    assert pkt[0x15] == p.TOKEN_CONFIRM
    assert struct.unpack_from("<I", pkt, 0x1C)[0] == 0xDEADBEEF
    assert struct.unpack_from(">H", pkt, 0x24)[0] == 0x0798


def test_conninfo_request_mac_and_guid():
    mac = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x11])
    pkt = p.conninfo_request(1, 2, 5, 0x2222, 0xAABBCCDD, name="IC-7610",
                             username="op", use_guid=False, guid=b"", mac=mac,
                             civ_local_port=0x1111, audio_local_port=0x2222)
    assert len(pkt) == p.CONNINFO_SIZE
    assert pkt[0x15] == 0x03  # request stream
    assert struct.unpack_from("<H", pkt, 0x27)[0] == 0x8010  # commoncap
    assert pkt[0x2A:0x30] == mac
    assert struct.unpack_from(">I", pkt, 0x7C)[0] == 0x1111  # civ local port BE
    assert pkt[0x40:0x47] == b"IC-7610"
    assert pkt[0x72] == 0x00 and pkt[0x73] == 0x00  # control-only: no codecs

    guid = bytes(range(16))
    gp = p.conninfo_request(1, 2, 5, 0, 0, name="r", username="op", use_guid=True,
                            guid=guid, mac=b"", civ_local_port=1, audio_local_port=2)
    assert gp[0x20:0x30] == guid


def test_parse_status():
    buf = bytearray(p.STATUS_SIZE)
    struct.pack_into("<I", buf, 0x30, 0)  # error ok
    buf[0x40] = 0x00
    struct.pack_into(">H", buf, 0x42, 50002)  # civ port BE
    struct.pack_into(">H", buf, 0x46, 50003)  # audio port BE
    out = p.parse_status(bytes(buf))
    assert out["civ_port"] == 50002 and out["audio_port"] == 50003
    assert out["error"] == 0 and out["disconnected"] is False


def test_parse_login_response():
    buf = bytearray(p.LOGIN_RESPONSE_SIZE)
    struct.pack_into("<H", buf, 0x1A, 0x4321)
    struct.pack_into("<I", buf, 0x1C, 0xCAFEF00D)
    struct.pack_into("<I", buf, 0x30, 0)
    buf[0x40:0x44] = b"FTTH"
    out = p.parse_login_response(bytes(buf))
    assert out["token"] == 0xCAFEF00D and out["tokrequest"] == 0x4321
    assert out["connection"] == "FTTH" and out["error"] == 0


def test_parse_capabilities():
    cap = bytearray(p.CAPABILITIES_SIZE)
    struct.pack_into("<H", cap, 0x40, 1)  # numradios
    block = bytearray(p.RADIO_CAP_SIZE)
    struct.pack_into("<H", block, 0x07, 0x8010)  # commoncap -> use MAC
    block[0x0A:0x10] = bytes([1, 2, 3, 4, 5, 6])
    block[0x10:0x17] = b"IC-7610"
    block[0x52] = 0x98  # CI-V address
    struct.pack_into(">I", block, 0x5A, 115200)
    radios = p.parse_capabilities(bytes(cap) + bytes(block))
    assert len(radios) == 1
    r = radios[0]
    assert r.name == "IC-7610" and r.civ_address == 0x98 and r.use_guid is False
    assert r.mac == bytes([1, 2, 3, 4, 5, 6]) and r.baudrate == 115200
