"""FlexRadio wire-protocol parsing: discovery datagrams and TCP control lines."""

from __future__ import annotations

from fake_flex import build_discovery_packet

from partyhams.radio.flex_protocol import (
    HandleLine,
    MessageLine,
    ReplyLine,
    StatusLine,
    VersionLine,
    hz_to_mhz,
    mhz_to_hz,
    parse_discovery,
    parse_line,
)


def test_parse_discovery():
    packet = build_discovery_packet(
        {
            "model": "FLEX-6500",
            "serial": "1234-5678-9012-3456",
            "version": "3.2.39.1",
            "nickname": "ShackFlex",
            "callsign": "W7ABC",
            "ip": "192.168.1.50",
            "port": "4992",
        }
    )
    fields = parse_discovery(packet)
    assert fields is not None
    assert fields["model"] == "FLEX-6500"
    assert fields["serial"] == "1234-5678-9012-3456"
    assert fields["ip"] == "192.168.1.50"


def test_parse_discovery_rejects_non_flex():
    assert parse_discovery(b"not a flex packet at all, too short") is None
    # 28+ bytes but wrong OUI in the Class ID.
    bogus = bytes(28) + b"model=FOO"
    assert parse_discovery(bogus) is None


def test_parse_control_lines():
    assert parse_line("V1.4.0.0") == VersionLine(version="1.4.0.0")
    assert parse_line("H1A2B3C4D") == HandleLine(handle="1A2B3C4D")

    reply = parse_line("R7|0|")
    assert isinstance(reply, ReplyLine)
    assert reply.seq == 7 and reply.code == 0

    err = parse_line("R8|50000015|bad")
    assert isinstance(err, ReplyLine)
    assert err.code == 0x50000015

    msg = parse_line("M10000000|something happened")
    assert isinstance(msg, MessageLine)
    assert msg.text == "something happened"


def test_parse_status_line():
    line = "S1A2B3C4D|slice 0 in_use=1 RF_frequency=14.074000 mode=USB rxant=ANT1"
    status = parse_line(line)
    assert isinstance(status, StatusLine)
    assert status.path == ["slice", "0"]
    assert status.fields["RF_frequency"] == "14.074000"
    assert status.fields["mode"] == "USB"

    radio = parse_line("S1A2B3C4D|radio callsign=W7ABC model=FLEX-6500")
    assert isinstance(radio, StatusLine)
    assert radio.path == ["radio"]
    assert radio.fields["callsign"] == "W7ABC"


def test_freq_helpers():
    assert mhz_to_hz("14.074000") == 14_074_000
    assert mhz_to_hz("") == 0
    assert hz_to_mhz(7_030_000) == "7.030000"


def test_parse_line_ignores_empty_and_unknown():
    assert parse_line("") is None
    assert parse_line("Z garbage") is None
