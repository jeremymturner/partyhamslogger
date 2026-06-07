"""Wire protocol for peer-to-peer log sync.

JSON over UDP — deliberately human-readable so the protocol is inspectable
(a design principle). Every datagram is one :class:`Message` wrapped in an
envelope carrying the protocol version, the event's network name (so multiple
events on one LAN don't cross-talk), and the sender's station id.

A change to a QSO — add, edit, or delete — is always a single :class:`QsoMessage`
carrying the *full* QSO (with its ``lamport`` and ``deleted`` flag). Merge is an
idempotent upsert keyed by ``uuid``; there is no separate delete message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from partyhams.core.models import QSO, Mode

PROTOCOL_VERSION = 1


# --------------------------------------------------------------------------- #
# QSO <-> wire dict
# --------------------------------------------------------------------------- #
def qso_to_wire(qso: QSO) -> dict:
    return {
        "uuid": qso.uuid,
        "station_id": qso.station_id,
        "operator": qso.operator,
        "lamport": qso.lamport,
        "deleted": qso.deleted,
        "call": qso.call,
        "timestamp": qso.timestamp.isoformat(),
        "freq_hz": qso.freq_hz,
        "mode": qso.mode.value,
        "rst_sent": qso.rst_sent,
        "rst_rcvd": qso.rst_rcvd,
        "serial_sent": qso.serial_sent,
        "exchange_rcvd": qso.exchange_rcvd,
        "exchange_sent": qso.exchange_sent,
    }


def qso_from_wire(d: dict) -> QSO:
    return QSO(
        uuid=d["uuid"],
        station_id=d["station_id"],
        operator=d["operator"],
        lamport=d["lamport"],
        deleted=d["deleted"],
        call=d["call"],
        timestamp=datetime.fromisoformat(d["timestamp"]),
        freq_hz=d["freq_hz"],
        mode=Mode(d["mode"]),
        rst_sent=d["rst_sent"],
        rst_rcvd=d["rst_rcvd"],
        serial_sent=d["serial_sent"],
        exchange_rcvd=dict(d["exchange_rcvd"]),
        exchange_sent=dict(d["exchange_sent"]),
    )


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #
@dataclass
class Hello:
    """Announce presence on join, advertising what this station has already seen."""

    operator: str
    call: str
    high_water: dict[str, int] = field(default_factory=dict)  # station_id -> max lamport
    type: str = "hello"


@dataclass
class QsoMessage:
    """An add/edit/delete of one QSO (full record)."""

    qso: QSO
    type: str = "qso"


@dataclass
class SyncRequest:
    """Ask peers for everything past the given per-station high-water marks."""

    high_water: dict[str, int] = field(default_factory=dict)
    type: str = "sync_request"


@dataclass
class SyncResponse:
    """A batch of QSOs answering a :class:`SyncRequest`."""

    qsos: list[QSO] = field(default_factory=list)
    type: str = "sync_response"


@dataclass
class Heartbeat:
    """Periodic liveness + divergence detector (``log_hash`` compares logs)."""

    count: int
    log_hash: str
    lamport_max: int
    type: str = "heartbeat"


Message = Hello | QsoMessage | SyncRequest | SyncResponse | Heartbeat


# --------------------------------------------------------------------------- #
# Envelope encode / decode
# --------------------------------------------------------------------------- #
def encode(msg: Message, network: str, sender: str) -> bytes:
    """Serialize a message into a UDP datagram payload."""
    body = _body_to_dict(msg)
    envelope = {"v": PROTOCOL_VERSION, "net": network, "sender": sender, **body}
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")


def decode(data: bytes) -> tuple[str, str, Message]:
    """Parse a datagram into ``(network, sender, message)``.

    Raises ``ValueError`` on a malformed payload or unknown/mismatched version.
    """
    obj = json.loads(data.decode("utf-8"))
    if obj.get("v") != PROTOCOL_VERSION:
        raise ValueError(f"unsupported protocol version: {obj.get('v')}")
    network = obj["net"]
    sender = obj["sender"]
    return network, sender, _body_from_dict(obj)


def _body_to_dict(msg: Message) -> dict:
    if isinstance(msg, Hello):
        return {"type": "hello", "operator": msg.operator, "call": msg.call,
                "high_water": msg.high_water}
    if isinstance(msg, QsoMessage):
        return {"type": "qso", "qso": qso_to_wire(msg.qso)}
    if isinstance(msg, SyncRequest):
        return {"type": "sync_request", "high_water": msg.high_water}
    if isinstance(msg, SyncResponse):
        return {"type": "sync_response", "qsos": [qso_to_wire(q) for q in msg.qsos]}
    if isinstance(msg, Heartbeat):
        return {"type": "heartbeat", "count": msg.count, "log_hash": msg.log_hash,
                "lamport_max": msg.lamport_max}
    raise TypeError(f"cannot encode message of type {type(msg).__name__}")


def _body_from_dict(obj: dict) -> Message:
    t = obj.get("type")
    if t == "hello":
        return Hello(operator=obj["operator"], call=obj["call"],
                     high_water=dict(obj.get("high_water", {})))
    if t == "qso":
        return QsoMessage(qso=qso_from_wire(obj["qso"]))
    if t == "sync_request":
        return SyncRequest(high_water=dict(obj.get("high_water", {})))
    if t == "sync_response":
        return SyncResponse(qsos=[qso_from_wire(q) for q in obj.get("qsos", [])])
    if t == "heartbeat":
        return Heartbeat(count=obj["count"], log_hash=obj["log_hash"],
                         lamport_max=obj["lamport_max"])
    raise ValueError(f"unknown message type: {t!r}")
