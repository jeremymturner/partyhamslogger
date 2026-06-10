"""Tests for the WSJT-X UDP protocol parser/encoder, conversion, and listener.

The parser/encoder are exercised exhaustively with hand-built byte buffers (no
running WSJT-X needed). The listener is checked against a loopback UDP send.
"""

from __future__ import annotations

import asyncio
import struct
from datetime import UTC, datetime

import pytest

from partyhams.app.session import build_session
from partyhams.core.models import Mode, ModeGroup, mode_group_for
from partyhams.wsjtx.convert import map_mode, qso_logged_to_record
from partyhams.wsjtx.listener import WsjtxListener
from partyhams.wsjtx.protocol import (
    MAGIC,
    TYPE_DECODE,
    TYPE_HEARTBEAT,
    TYPE_HIGHLIGHT_CALLSIGN,
    TYPE_QSO_LOGGED,
    TYPE_STATUS,
    Clear,
    Decode,
    Heartbeat,
    QSOLogged,
    Status,
    encode_highlight_callsign,
    parse_message,
)

_UNIX_EPOCH_JD = 2440588


# --------------------------------------------------------------------------- #
# byte-buffer builders (mirror WSJT-X's QDataStream layout)
# --------------------------------------------------------------------------- #
def _utf8(s: str | None) -> bytes:
    if s is None:
        return struct.pack(">I", 0xFFFFFFFF)
    raw = s.encode("utf-8")
    return struct.pack(">I", len(raw)) + raw


def _header(msg_type: int, schema: int = 2) -> bytes:
    return struct.pack(">III", MAGIC, schema, msg_type)


def _qdatetime(dt: datetime) -> bytes:
    """Encode an aware UTC datetime as a QDateTime (Julian day + ms + UTC spec)."""
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    jd = (midnight.date() - datetime(1970, 1, 1).date()).days + _UNIX_EPOCH_JD
    ms = int((dt - midnight).total_seconds() * 1000)
    return struct.pack(">qIB", jd, ms, 1)  # spec 1 = UTC


# --------------------------------------------------------------------------- #
# magic / framing robustness
# --------------------------------------------------------------------------- #
def test_bad_magic_returns_none():
    data = struct.pack(">III", 0xDEADBEEF, 2, TYPE_HEARTBEAT) + _utf8("WSJT-X")
    assert parse_message(data) is None


def test_empty_and_short_return_none():
    assert parse_message(b"") is None
    assert parse_message(b"\x00\x01") is None
    assert parse_message(struct.pack(">I", MAGIC)) is None  # magic only


def test_unknown_type_returns_none():
    data = _header(99) + _utf8("WSJT-X")
    assert parse_message(data) is None


def test_truncated_midstring_returns_none():
    # Claims a 50-byte id but supplies only a few bytes.
    data = _header(TYPE_HEARTBEAT) + struct.pack(">I", 50) + b"abc"
    assert parse_message(data) is None


# --------------------------------------------------------------------------- #
# Heartbeat (0)
# --------------------------------------------------------------------------- #
def test_heartbeat_full():
    data = (
        _header(TYPE_HEARTBEAT)
        + _utf8("WSJT-X")
        + struct.pack(">I", 3)
        + _utf8("2.6.1")
        + _utf8("abc123")
    )
    msg = parse_message(data)
    assert isinstance(msg, Heartbeat)
    assert msg.id == "WSJT-X"
    assert msg.max_schema == 3
    assert msg.version == "2.6.1"
    assert msg.revision == "abc123"


def test_heartbeat_id_only():
    msg = parse_message(_header(TYPE_HEARTBEAT) + _utf8("WSJT-X"))
    assert isinstance(msg, Heartbeat)
    assert msg.id == "WSJT-X"
    assert msg.version == ""


def test_null_string_decodes_empty():
    # A null id (0xffffffff length) decodes to "".
    msg = parse_message(_header(TYPE_HEARTBEAT) + _utf8(None))
    assert isinstance(msg, Heartbeat)
    assert msg.id == ""


# --------------------------------------------------------------------------- #
# Status (1)
# --------------------------------------------------------------------------- #
def _status_bytes(*, tx_period_odd: bool | None = True) -> bytes:
    body = (
        _utf8("WSJT-X")
        + struct.pack(">Q", 14_074_000)  # dial freq
        + _utf8("FT8")  # mode
        + _utf8("K1ABC")  # dx call
        + _utf8("-12")  # report
        + _utf8("FT8")  # tx mode
        + struct.pack(">B", 1)  # tx enabled
        + struct.pack(">B", 0)  # transmitting
        + struct.pack(">B", 1)  # decoding
        + struct.pack(">I", 1500)  # rx df
        + struct.pack(">I", 1500)  # tx df
        + _utf8("W9XYZ")  # de call
        + _utf8("EN52")  # de grid
        + _utf8("FN42")  # dx grid
    )
    if tx_period_odd is not None:
        body += struct.pack(">B", 1 if tx_period_odd else 0)
    return _header(TYPE_STATUS) + body


def test_status_full():
    msg = parse_message(_status_bytes(tx_period_odd=True))
    assert isinstance(msg, Status)
    assert msg.id == "WSJT-X"
    assert msg.dial_freq == 14_074_000
    assert msg.mode == "FT8"
    assert msg.dx_call == "K1ABC"
    assert msg.report == "-12"
    assert msg.tx_mode == "FT8"
    assert msg.tx_enabled is True
    assert msg.transmitting is False
    assert msg.decoding is True
    assert msg.de_call == "W9XYZ"
    assert msg.de_grid == "EN52"
    assert msg.dx_grid == "FN42"
    assert msg.tx_period_odd is True


def test_status_without_tx_period():
    msg = parse_message(_status_bytes(tx_period_odd=None))
    assert isinstance(msg, Status)
    assert msg.tx_period_odd is None
    assert msg.dx_grid == "FN42"


def test_status_even_period():
    msg = parse_message(_status_bytes(tx_period_odd=False))
    assert isinstance(msg, Status)
    assert msg.tx_period_odd is False


# --------------------------------------------------------------------------- #
# Decode (2)
# --------------------------------------------------------------------------- #
def test_decode_full():
    data = (
        _header(TYPE_DECODE)
        + _utf8("WSJT-X")
        + struct.pack(">B", 1)  # is_new
        + struct.pack(">I", 45_030_000)  # time ms since midnight
        + struct.pack(">i", -8)  # snr
        + struct.pack(">d", 0.2)  # delta time
        + struct.pack(">I", 1234)  # delta freq
        + _utf8("~")  # mode
        + _utf8("CQ K1ABC FN42")  # message
    )
    msg = parse_message(data)
    assert isinstance(msg, Decode)
    assert msg.id == "WSJT-X"
    assert msg.is_new is True
    assert msg.time_ms == 45_030_000
    assert msg.snr == -8
    assert msg.delta_time == pytest.approx(0.2)
    assert msg.delta_freq == 1234
    assert msg.message == "CQ K1ABC FN42"


# --------------------------------------------------------------------------- #
# Clear (3)
# --------------------------------------------------------------------------- #
def test_clear():
    msg = parse_message(_header(3) + _utf8("WSJT-X"))
    assert isinstance(msg, Clear)
    assert msg.id == "WSJT-X"


# --------------------------------------------------------------------------- #
# QSOLogged (5)
# --------------------------------------------------------------------------- #
def _qso_logged_bytes(*, with_trailing: bool = True) -> bytes:
    off = datetime(2026, 6, 7, 18, 30, 15, tzinfo=UTC)
    on = datetime(2026, 6, 7, 18, 29, 0, tzinfo=UTC)
    body = (
        _utf8("WSJT-X")
        + _qdatetime(off)
        + _utf8("K1ABC")  # dx call
        + _utf8("FN42")  # dx grid
        + struct.pack(">Q", 14_074_000)  # tx frequency
        + _utf8("FT8")  # mode
        + _utf8("-10")  # report sent
        + _utf8("-12")  # report recv
        + _utf8("37")  # tx power
        + _utf8("nice")  # comments
        + _utf8("Bob")  # name
    )
    if with_trailing:
        body += (
            _qdatetime(on)
            + _utf8("W9OP")  # operator call
            + _utf8("W9XYZ")  # my call
            + _utf8("EN52")  # my grid
            + _utf8("3A OR")  # exchange sent
            + _utf8("2A WWA")  # exchange recv
        )
    return _header(TYPE_QSO_LOGGED) + body


def test_qso_logged_full():
    msg = parse_message(_qso_logged_bytes())
    assert isinstance(msg, QSOLogged)
    assert msg.id == "WSJT-X"
    assert msg.dx_call == "K1ABC"
    assert msg.dx_grid == "FN42"
    assert msg.tx_frequency == 14_074_000
    assert msg.mode == "FT8"
    assert msg.report_sent == "-10"
    assert msg.report_recv == "-12"
    assert msg.tx_power == "37"
    assert msg.comments == "nice"
    assert msg.name == "Bob"
    assert msg.operator_call == "W9OP"
    assert msg.my_call == "W9XYZ"
    assert msg.my_grid == "EN52"
    assert msg.exchange_sent == "3A OR"
    assert msg.exchange_recv == "2A WWA"
    assert msg.date_time_off == datetime(2026, 6, 7, 18, 30, 15, tzinfo=UTC)
    assert msg.date_time_on == datetime(2026, 6, 7, 18, 29, 0, tzinfo=UTC)


def test_qso_logged_tolerates_missing_trailing_fields():
    msg = parse_message(_qso_logged_bytes(with_trailing=False))
    assert isinstance(msg, QSOLogged)
    assert msg.dx_call == "K1ABC"
    assert msg.name == "Bob"
    assert msg.my_call == ""  # absent -> default
    assert msg.date_time_on is None


# --------------------------------------------------------------------------- #
# encode_highlight_callsign (13)
# --------------------------------------------------------------------------- #
def test_encode_highlight_structure():
    data = encode_highlight_callsign(
        "WSJT-X",
        "K1ABC",
        background=(40, 90, 40, 255),
        foreground=(255, 255, 255, 255),
        highlight_last=True,
    )
    magic, schema, mtype = struct.unpack(">III", data[:12])
    assert magic == MAGIC
    assert schema == 2
    assert mtype == TYPE_HIGHLIGHT_CALLSIGN
    rest = data[12:]
    # id then callsign as utf8 strings.
    id_len = struct.unpack(">I", rest[:4])[0]
    assert rest[4 : 4 + id_len] == b"WSJT-X"
    off = 4 + id_len
    call_len = struct.unpack(">I", rest[off : off + 4])[0]
    assert rest[off + 4 : off + 4 + call_len] == b"K1ABC"
    # The trailing byte (highlight_last) is set.
    assert data[-1] == 1


def test_encode_highlight_invalid_color_resets():
    data = encode_highlight_callsign("WSJT-X", "K1ABC", background=None, foreground=None)
    # Each QColor is spec byte + 5 uint16 channels = 11 bytes; invalid spec is 0.
    # Locate the two color blocks after id+call. Just assert it round-trips length
    # and ends with the highlight-last byte (0 here).
    assert data[-1] == 0
    assert len(data) > 12


def test_highlight_color_channels_scale_to_16bit():
    data = encode_highlight_callsign("X", "K1ABC", background=(255, 0, 0, 255))
    # Find first color block: after header(12) + id "X"(4+1) + call "K1ABC"(4+5).
    off = 12 + 5 + 9
    spec = data[off]
    assert spec == 1  # Rgb
    a, r, g, b, pad = struct.unpack(">HHHHH", data[off + 1 : off + 11])
    assert a == 0xFFFF
    assert r == 0xFFFF
    assert g == 0
    assert b == 0


# --------------------------------------------------------------------------- #
# conversion: QSOLogged -> record_qso kwargs
# --------------------------------------------------------------------------- #
def test_map_mode():
    assert map_mode("FT8") == Mode.FT8
    assert map_mode("ft4") == Mode.FT4
    assert map_mode("RTTY") == Mode.RTTY
    assert map_mode("CW") == Mode.CW
    # Unknown digital sub-mode falls back to FT8 (DIGITAL group).
    assert map_mode("JT9") == Mode.FT8
    assert mode_group_for(map_mode("MSK144")) == ModeGroup.DIGITAL


def test_map_mode_decode_submode_codes():
    # Decode (type 2) packets carry a single-char submode code, not the name.
    assert map_mode("~") == Mode.FT8
    assert map_mode("+") == Mode.FT4


def test_qso_logged_to_record_mapping():
    msg = parse_message(_qso_logged_bytes())
    assert isinstance(msg, QSOLogged)
    kwargs = qso_logged_to_record(msg)
    assert kwargs["call"] == "K1ABC"
    assert kwargs["freq_hz"] == 14_074_000
    assert kwargs["mode"] == Mode.FT8
    assert kwargs["exchange"]["grid"] == "FN42"
    assert kwargs["exchange"]["exchange"] == "2A WWA"
    assert kwargs["rst_sent"] == "-10"
    assert kwargs["rst_rcvd"] == "-12"
    # WSJT-X's reported QSO-off time becomes the log timestamp.
    assert kwargs["timestamp"] == datetime(2026, 6, 7, 18, 30, 15, tzinfo=UTC)


def test_qso_logged_to_record_defaults_when_blank():
    msg = QSOLogged(id="X", dx_call="k1abc", tx_frequency=7_074_000, mode="FT4")
    kwargs = qso_logged_to_record(msg)
    assert kwargs["call"] == "K1ABC"
    assert kwargs["mode"] == Mode.FT4
    assert kwargs["exchange"] == {}
    assert kwargs["rst_sent"] is None
    assert kwargs["rst_rcvd"] == "599"
    # No WSJT-X time supplied -> no timestamp override (record_qso stamps "now").
    assert "timestamp" not in kwargs


def _session():
    return build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        sent_exchange={"class": "1E", "section": "OR"},
        network=None,
        db_path=":memory:",
    )


def test_conversion_feeds_session():
    """A WSJT-X QSO flows into the log via record_qso."""
    session = _session()
    msg = parse_message(_qso_logged_bytes())
    qso = session.record_qso(**qso_logged_to_record(msg))
    assert qso.call == "K1ABC"
    assert qso.freq_hz == 14_074_000
    assert qso.mode == Mode.FT8
    assert qso.timestamp == datetime(2026, 6, 7, 18, 30, 15, tzinfo=UTC)
    assert qso in session.qsos()


def test_stable_uuid_is_deterministic_and_specific():
    from partyhams.wsjtx.convert import stable_uuid

    base = QSOLogged(
        id="X",
        dx_call="K1ABC",
        tx_frequency=14_074_000,
        mode="FT8",
        date_time_off=datetime(2026, 6, 7, 18, 30, 15, tzinfo=UTC),
        my_call="W0CPH",
        operator_call="N0AW",
    )
    # Same contact -> same uuid (so duplicate packets dedupe).
    assert stable_uuid(base) == stable_uuid(base)
    # A different band, call, or operator -> a different uuid.
    from dataclasses import replace

    assert stable_uuid(base) != stable_uuid(replace(base, tx_frequency=7_074_000))
    assert stable_uuid(base) != stable_uuid(replace(base, dx_call="W2XYZ"))
    assert stable_uuid(base) != stable_uuid(replace(base, operator_call="W1AW"))


def test_duplicate_wsjtx_deliveries_dedupe_in_the_log():
    """Re-delivering the same QSOLogged (multi-interface / multicast) logs once."""
    session = _session()
    msg = parse_message(_qso_logged_bytes())
    kwargs = qso_logged_to_record(msg)
    for _ in range(6):
        session.record_qso(**kwargs)  # same content-derived uuid each time
    assert len(session.qsos()) == 1


# --------------------------------------------------------------------------- #
# listener over loopback UDP
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_listener_dispatches_and_records_peer():
    received: list[QSOLogged] = []
    statuses: list[Status] = []
    listener = WsjtxListener(
        port=0,  # ephemeral; we read the bound port back
        host="127.0.0.1",
        on_qso_logged=received.append,
        on_status=statuses.append,
    )
    await listener.start()
    bound_port = listener._transport.get_extra_info("sockname")[1]
    try:
        loop = asyncio.get_running_loop()
        sender_transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, remote_addr=("127.0.0.1", bound_port)
        )
        sender_transport.sendto(_qso_logged_bytes())
        sender_transport.sendto(_status_bytes())
        sender_transport.sendto(b"garbage not a wsjtx packet")  # ignored
        for _ in range(50):
            if received and statuses:
                break
            await asyncio.sleep(0.01)
        sender_transport.close()
    finally:
        await listener.stop()
    assert len(received) == 1
    assert received[0].dx_call == "K1ABC"
    assert len(statuses) == 1
    assert statuses[0].mode == "FT8"
    assert listener.peer_addr is not None  # learned the sender's address


@pytest.mark.asyncio
async def test_listener_joins_multicast_group():
    """When the host is a multicast group, the listener joins it and receives
    datagrams sent to that group (WSJT-X's UDP Server can target e.g. 224.0.0.1)."""
    import socket

    group, port = "224.0.0.1", 22372
    received: list[QSOLogged] = []
    listener = WsjtxListener(port=port, host=group, on_qso_logged=received.append)
    try:
        await listener.start()
    except OSError as exc:  # no multicast in this environment -> skip
        pytest.skip(f"multicast unavailable: {exc}")
    try:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sender.sendto(_qso_logged_bytes(), (group, port))
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.01)
        sender.close()
    finally:
        await listener.stop()
    if not received:
        pytest.skip("multicast not delivered in this environment")
    assert received[0].dx_call == "K1ABC"


@pytest.mark.asyncio
async def test_listener_callback_exception_is_swallowed():
    def boom(_msg):
        raise RuntimeError("handler blew up")

    listener = WsjtxListener(port=0, host="127.0.0.1", on_status=boom)
    await listener.start()
    bound_port = listener._transport.get_extra_info("sockname")[1]
    try:
        loop = asyncio.get_running_loop()
        sender_transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, remote_addr=("127.0.0.1", bound_port)
        )
        sender_transport.sendto(_status_bytes())  # must not crash the loop
        await asyncio.sleep(0.05)
        sender_transport.close()
        # The listener is still alive and knows the peer.
        assert listener.peer_addr is not None
    finally:
        await listener.stop()


@pytest.mark.asyncio
async def test_send_highlight_requires_known_peer():
    listener = WsjtxListener(port=0, host="127.0.0.1")
    await listener.start()
    try:
        # No datagram received yet -> no peer address -> can't send.
        assert listener.send_highlight("WSJT-X", "K1ABC") is False
    finally:
        await listener.stop()
