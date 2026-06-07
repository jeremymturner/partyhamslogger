"""UDP multicast transport for peer-to-peer sync.

The :class:`Transport` ABC is what :class:`~partyhams.net.engine.SyncEngine`
depends on; :class:`MulticastTransport` is the real LAN implementation and
``net/loopback.py`` provides an in-memory one for deterministic tests.

Received datagrams are decoded, filtered (wrong network or our own multicast
echo are dropped), and pushed onto :attr:`Transport.inbox` for the engine to
drain. Sending encodes a :class:`~partyhams.net.protocol.Message` and multicasts
it to the group.
"""

from __future__ import annotations

import asyncio
import socket
import struct
from abc import ABC, abstractmethod

from partyhams.net.protocol import Message, decode, encode

# Default multicast group + port for the LAN sync bus. 239.0.0.0/8 is the
# administratively-scoped block (RFC 2365); datagrams are filtered by the
# per-event network name inside each payload.
DEFAULT_MCAST_GROUP = "239.73.73.1"
DEFAULT_PORT = 12373

# Cadence for the liveness + divergence heartbeat.
HEARTBEAT_INTERVAL_S = 5.0


class Transport(ABC):
    """Abstract message bus. Implementations deliver onto :attr:`inbox`."""

    def __init__(self, network: str, station_id: str) -> None:
        self.network = network
        self.station_id = station_id
        self.inbox: asyncio.Queue[tuple[str, Message]] = asyncio.Queue()

    @abstractmethod
    async def start(self) -> None:
        """Begin receiving (and, for multicast, join the group)."""

    @abstractmethod
    async def send(self, message: Message) -> None:
        """Broadcast a message to all peers."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop receiving and release resources."""


class NullTransport(Transport):
    """A no-op transport for offline / single-station operation.

    Lets the app always run through a :class:`~partyhams.net.engine.SyncEngine`
    (uniform code path) even when there's no network — sends go nowhere and the
    inbox never fills.
    """

    async def start(self) -> None:
        pass

    async def send(self, message: Message) -> None:
        pass

    async def stop(self) -> None:
        pass


class MulticastTransport(Transport):
    """Real LAN transport over UDP multicast.

    Two instances on the *same* host can both join (e.g. two terminals for a
    demo) because the socket sets ``SO_REUSEPORT`` and enables multicast
    loopback. ``IP_MULTICAST_TTL`` is 1, so traffic stays on the local subnet.
    """

    def __init__(
        self,
        network: str,
        station_id: str,
        group: str = DEFAULT_MCAST_GROUP,
        port: int = DEFAULT_PORT,
    ) -> None:
        super().__init__(network, station_id)
        self.group = group
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        sock = self._make_socket()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _McastProtocol(self), sock=sock
        )

    async def send(self, message: Message) -> None:
        if self._transport is None:
            raise RuntimeError("MulticastTransport.send before start()")
        data = encode(message, self.network, self.station_id)
        self._transport.sendto(data, (self.group, self.port))

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def _make_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # SO_REUSEPORT lets multiple instances on one host share the port.
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        sock.bind(("", self.port))
        # Join the multicast group on the default interface.
        mreq = struct.pack("=4sl", socket.inet_aton(self.group), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        # Loopback on so co-located instances see each other.
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        sock.setblocking(False)
        return sock


class _McastProtocol(asyncio.DatagramProtocol):
    """asyncio glue: decode, filter, and enqueue incoming datagrams."""

    def __init__(self, owner: MulticastTransport) -> None:
        self._owner = owner

    def datagram_received(self, data: bytes, addr: object) -> None:
        try:
            network, sender, message = decode(data)
        except (ValueError, KeyError, UnicodeDecodeError):
            return  # ignore anything that isn't a well-formed message for us
        if network != self._owner.network:
            return  # a different event sharing the LAN
        if sender == self._owner.station_id:
            return  # our own multicast echo
        self._owner.inbox.put_nowait((sender, message))
