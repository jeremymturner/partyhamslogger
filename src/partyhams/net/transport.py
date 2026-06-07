"""UDP multicast transport for peer-to-peer sync.

⚠️ **Skeleton.** The wire format (``protocol``) and merge logic (``sync``) are
done and tested; this glue — the actual sockets and the join/heartbeat/catch-up
state machine — is the first Phase-0 spike to flesh out and exercise on a real LAN.

Design notes captured here so the spike starts from intent, not a blank file.
"""

from __future__ import annotations

from collections.abc import Callable

from partyhams.net.protocol import Message

# Default multicast group + port for the LAN sync bus. Multicast (not broadcast)
# keeps switch traffic clean and is filtered by the per-event network name inside
# each datagram.
DEFAULT_MCAST_GROUP = "239.73.73.1"  # 239.x = admin-scoped; .73 == 'I' for fun
DEFAULT_PORT = 12373

# Cadence for the liveness + divergence heartbeat.
HEARTBEAT_INTERVAL_S = 5.0


class MulticastTransport:
    """Join a multicast group, send/receive datagrams, fan messages to a handler.

    Intended usage (asyncio):

        transport = MulticastTransport(network="fd-2026-W7AAA", station_id=sid,
                                       on_message=engine.handle)
        await transport.start()
        await transport.send(QsoMessage(qso=q))   # broadcast a logged QSO

    The ``on_message`` callback receives ``(sender_station_id, Message)`` for every
    datagram whose ``net`` matches ours and whose ``sender`` is not us (we ignore
    our own multicast echoes).
    """

    def __init__(
        self,
        network: str,
        station_id: str,
        on_message: Callable[[str, Message], None],
        group: str = DEFAULT_MCAST_GROUP,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.network = network
        self.station_id = station_id
        self.on_message = on_message
        self.group = group
        self.port = port

    async def start(self) -> None:  # pragma: no cover - Phase-0 spike
        """Open the multicast socket and begin receiving. TODO: implement."""
        raise NotImplementedError("MulticastTransport.start is the Phase-0 sync spike")

    async def send(self, message: Message) -> None:  # pragma: no cover - spike
        """Encode and multicast a message to the event bus. TODO: implement."""
        raise NotImplementedError("MulticastTransport.send is the Phase-0 sync spike")

    async def stop(self) -> None:  # pragma: no cover - spike
        """Leave the group and close the socket. TODO: implement."""
        raise NotImplementedError("MulticastTransport.stop is the Phase-0 sync spike")
