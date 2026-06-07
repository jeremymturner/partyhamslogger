"""Peer-to-peer LAN synchronization (decision #1).

Every station holds the full log in its own SQLite store and shares changes over
UDP multicast. ``protocol`` defines the (JSON, inspectable) wire format; ``sync``
holds the deterministic merge/reconciliation logic, kept transport-free so it can
be unit-tested without sockets.
"""

from partyhams.net.engine import SyncEngine
from partyhams.net.protocol import (
    PROTOCOL_VERSION,
    Chat,
    Heartbeat,
    Hello,
    QsoMessage,
    StationStatus,
    SyncRequest,
    SyncResponse,
    decode,
    encode,
    qso_from_wire,
    qso_to_wire,
)
from partyhams.net.sync import LogMerge
from partyhams.net.transport import (
    DEFAULT_MCAST_GROUP,
    DEFAULT_PORT,
    MulticastTransport,
    Transport,
)

__all__ = [
    "PROTOCOL_VERSION",
    "Chat",
    "Heartbeat",
    "Hello",
    "QsoMessage",
    "StationStatus",
    "SyncRequest",
    "SyncResponse",
    "decode",
    "encode",
    "qso_from_wire",
    "qso_to_wire",
    "LogMerge",
    "SyncEngine",
    "Transport",
    "MulticastTransport",
    "DEFAULT_MCAST_GROUP",
    "DEFAULT_PORT",
]
