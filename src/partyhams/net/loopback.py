"""In-memory transport for deterministic, socket-free tests.

A :class:`LoopbackBus` connects several :class:`LoopbackTransport` instances.
``send`` serializes through the *real* wire format (:mod:`partyhams.net.protocol`)
and delivers a freshly-decoded copy to every other attached transport — so tests
exercise encode/decode and get independent object copies (no shared mutation),
exactly like the multicast path, but with no network and no timing flakiness.
"""

from __future__ import annotations

from partyhams.net.protocol import Message, decode, encode
from partyhams.net.transport import Transport


class LoopbackBus:
    """A shared in-process channel that fans datagrams out to its members."""

    def __init__(self) -> None:
        self._members: list[LoopbackTransport] = []
        # Optional set of station_ids that are currently "partitioned" (their
        # outbound traffic is dropped) — used to simulate dropped packets.
        self.partitioned: set[str] = set()

    def attach(self, transport: LoopbackTransport) -> None:
        self._members.append(transport)

    def detach(self, transport: LoopbackTransport) -> None:
        if transport in self._members:
            self._members.remove(transport)

    def deliver(self, data: bytes) -> None:
        network, sender, _ = decode(data)
        if sender in self.partitioned:
            return  # simulate this station's packet being lost
        for member in self._members:
            if member.station_id == sender:
                continue  # don't echo to self
            if member.network != network:
                continue  # different event
            # Decode a fresh copy per recipient (independent objects).
            _, _, message = decode(data)
            member.inbox.put_nowait((sender, message))


class LoopbackTransport(Transport):
    def __init__(self, bus: LoopbackBus, network: str, station_id: str) -> None:
        super().__init__(network, station_id)
        self._bus = bus

    async def start(self) -> None:
        self._bus.attach(self)

    async def send(self, message: Message) -> None:
        self._bus.deliver(encode(message, self.network, self.station_id))

    async def stop(self) -> None:
        self._bus.detach(self)
