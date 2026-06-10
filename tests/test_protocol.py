"""Wire protocol: encode/decode round-trips for every message type."""

from __future__ import annotations

import pytest
from factories import make_qso

from partyhams.core.models import Mode
from partyhams.net import protocol as p

NET = "fd-2026-W7AAA"
SENDER = "abc12345"


def roundtrip(msg):
    network, sender, decoded = p.decode(p.encode(msg, NET, SENDER))
    assert network == NET
    assert sender == SENDER
    return decoded


def test_qso_message_roundtrip():
    q = make_qso("K1ABC", mode=Mode.USB)
    decoded = roundtrip(p.QsoMessage(qso=q))
    assert isinstance(decoded, p.QsoMessage)
    assert decoded.qso.uuid == q.uuid
    assert decoded.qso.call == "K1ABC"
    assert decoded.qso.mode is Mode.USB
    assert decoded.qso.exchange_rcvd == q.exchange_rcvd
    assert decoded.qso.timestamp == q.timestamp
    assert decoded.qso.operator == q.operator
    assert decoded.qso.station_callsign == q.station_callsign  # carried over the wire


def test_hello_roundtrip():
    decoded = roundtrip(p.Hello(operator="OP1", call="W7AAA", high_water={"s1": 5}))
    assert isinstance(decoded, p.Hello)
    assert decoded.operator == "OP1"
    assert decoded.high_water == {"s1": 5}


def test_sync_request_response_roundtrip():
    req = roundtrip(p.SyncRequest(high_water={"s1": 2, "s2": 7}))
    assert isinstance(req, p.SyncRequest)
    assert req.high_water == {"s1": 2, "s2": 7}

    qsos = [make_qso("K1A"), make_qso("K2B")]
    resp = roundtrip(p.SyncResponse(qsos=qsos))
    assert isinstance(resp, p.SyncResponse)
    assert [q.call for q in resp.qsos] == ["K1A", "K2B"]


def test_full_log_request_roundtrip():
    assert isinstance(roundtrip(p.FullLogRequest()), p.FullLogRequest)


def test_heartbeat_roundtrip():
    decoded = roundtrip(p.Heartbeat(count=42, log_hash="deadbeef", lamport_max=99))
    assert isinstance(decoded, p.Heartbeat)
    assert decoded.count == 42
    assert decoded.log_hash == "deadbeef"


def test_station_status_roundtrip():
    decoded = roundtrip(
        p.StationStatus(operator="N0AW", call="W7ABC", freq_hz=14_040_000, mode="CW")
    )
    assert isinstance(decoded, p.StationStatus)
    assert decoded.operator == "N0AW"
    assert decoded.freq_hz == 14_040_000
    assert decoded.mode == "CW"


def test_chat_roundtrip():
    decoded = roundtrip(
        p.Chat(from_op="N0AW", to_op="*", text="hi all", ts="2026-06-27T18:00:00+00:00")
    )
    assert isinstance(decoded, p.Chat)
    assert decoded.from_op == "N0AW"
    assert decoded.to_op == "*"
    assert decoded.text == "hi all"


def test_rejects_wrong_version():
    data = p.encode(p.Heartbeat(count=1, log_hash="x", lamport_max=1), NET, SENDER)
    tampered = data.replace(b'"v":1', b'"v":999')
    with pytest.raises(ValueError):
        p.decode(tampered)


def test_rejects_unknown_type():
    with pytest.raises(ValueError):
        p.decode(b'{"v":1,"net":"n","sender":"s","type":"nope"}')
