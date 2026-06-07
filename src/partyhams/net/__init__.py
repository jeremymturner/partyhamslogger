"""Peer-to-peer LAN synchronization (decision #1).

Every station holds the full log in its own SQLite store and shares changes over
UDP multicast. ``protocol`` defines the (JSON, inspectable) wire format; ``sync``
holds the deterministic merge/reconciliation logic, kept transport-free so it can
be unit-tested without sockets.
"""

from partyhams.net.protocol import (
    PROTOCOL_VERSION,
    Heartbeat,
    Hello,
    QsoMessage,
    SyncRequest,
    SyncResponse,
    decode,
    encode,
    qso_from_wire,
    qso_to_wire,
)
from partyhams.net.sync import LogMerge

__all__ = [
    "PROTOCOL_VERSION",
    "Heartbeat",
    "Hello",
    "QsoMessage",
    "SyncRequest",
    "SyncResponse",
    "decode",
    "encode",
    "qso_from_wire",
    "qso_to_wire",
    "LogMerge",
]
