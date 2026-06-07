"""The peer-to-peer sync engine.

Ties a :class:`~partyhams.net.transport.Transport` to a
:class:`~partyhams.net.sync.LogMerge` and a Lamport clock. Responsibilities:

* **Join** — announce ourselves (:class:`Hello`) so peers send us what we're missing.
* **Log** — stamp a local QSO with a fresh lamport, merge it, broadcast it.
* **Receive** — merge remote QSOs; answer catch-up requests; reconcile on divergence.
* **Heartbeat** — periodically advertise ``(count, log_hash)`` so a peer that has
  drifted (dropped packet, late join after a partition) notices and re-syncs.

The receive handling is split so tests can drive it deterministically:
``join()`` + manual :meth:`pump_once` (no background tasks), while ``start()``
runs the real background receive + heartbeat loops.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from partyhams.core.clock import LamportClock, new_uuid
from partyhams.core.models import QSO, Mode
from partyhams.net.protocol import (
    Heartbeat,
    Hello,
    Message,
    QsoMessage,
    SyncRequest,
    SyncResponse,
)
from partyhams.net.sync import LogMerge
from partyhams.net.transport import HEARTBEAT_INTERVAL_S, Transport


class SyncEngine:
    def __init__(
        self,
        transport: Transport,
        *,
        operator: str,
        call: str,
        log: LogMerge | None = None,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_S,
        on_qso: Callable[[QSO], None] | None = None,
    ) -> None:
        self.transport = transport
        self.station_id = transport.station_id
        self.operator = operator
        self.call = call
        self.log = log if log is not None else LogMerge()
        self.clock = LamportClock()
        self.heartbeat_interval = heartbeat_interval
        # Fired whenever a QSO is applied locally or from a peer (state changed).
        # The app layer uses this to persist + refresh the UI.
        self.on_qso = on_qso
        # station_id -> operator label, for the "who's on" view.
        self.peers: dict[str, str] = {}
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def _notify(self, qso: QSO) -> None:
        if self.on_qso is not None:
            self.on_qso(qso)

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    async def join(self) -> None:
        """Open the transport and announce ourselves (no background loops)."""
        await self.transport.start()
        await self._announce()

    async def start(self) -> None:
        """Join and run the background receive + heartbeat loops."""
        await self.join()
        self._running = True
        self._tasks = [
            asyncio.create_task(self._recv_loop()),
            asyncio.create_task(self._heartbeat_loop()),
        ]

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
        await self.transport.stop()

    async def _announce(self) -> None:
        await self.transport.send(
            Hello(operator=self.operator, call=self.call, high_water=self.log.high_water())
        )

    # ------------------------------------------------------------------ #
    # local actions
    # ------------------------------------------------------------------ #
    async def log_qso(
        self,
        *,
        call: str,
        freq_hz: int,
        mode: Mode,
        exchange_rcvd: dict[str, str] | None = None,
        rst_sent: str = "599",
        rst_rcvd: str = "599",
    ) -> QSO:
        """Create, store, and broadcast a new QSO."""
        qso = QSO(
            uuid=new_uuid(),
            station_id=self.station_id,
            operator=self.operator,
            lamport=self.clock.tick(),
            call=call.upper(),
            freq_hz=freq_hz,
            mode=mode,
            rst_sent=rst_sent,
            rst_rcvd=rst_rcvd,
            exchange_rcvd=exchange_rcvd or {},
        )
        self.log.apply(qso)
        self._notify(qso)
        await self.transport.send(QsoMessage(qso=qso))
        return qso

    async def send_heartbeat(self) -> None:
        await self.transport.send(
            Heartbeat(
                count=len(self.log),
                log_hash=self.log.log_hash(),
                lamport_max=self.clock.value,
            )
        )

    # ------------------------------------------------------------------ #
    # receive
    # ------------------------------------------------------------------ #
    async def pump_once(self) -> bool:
        """Drain and handle all currently-queued messages. Returns True if any."""
        handled = False
        while not self.transport.inbox.empty():
            sender, message = self.transport.inbox.get_nowait()
            await self._handle(sender, message)
            handled = True
        return handled

    async def _recv_loop(self) -> None:
        while self._running:
            sender, message = await self.transport.inbox.get()
            await self._handle(sender, message)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            await self.send_heartbeat()

    async def _handle(self, sender: str, message: Message) -> None:
        self.peers.setdefault(sender, sender)

        if isinstance(message, QsoMessage):
            self.clock.update(message.qso.lamport)
            if self.log.apply(message.qso):
                self._notify(message.qso)

        elif isinstance(message, Hello):
            self.peers[sender] = message.call or message.operator or sender
            # The newcomer told us what it has; send back anything it's missing.
            await self._send_diff(message.high_water)

        elif isinstance(message, SyncRequest):
            await self._send_diff(message.high_water)

        elif isinstance(message, SyncResponse):
            for qso in message.qsos:
                self.clock.update(qso.lamport)
                if self.log.apply(qso):
                    self._notify(qso)

        elif isinstance(message, Heartbeat):
            self.clock.update(message.lamport_max)
            # Divergence backstop: if our merged state differs, ask for the delta.
            if message.log_hash != self.log.log_hash():
                await self.transport.send(SyncRequest(high_water=self.log.high_water()))

    async def _send_diff(self, remote_high_water: dict[str, int]) -> None:
        missing = self.log.diff_since(remote_high_water)
        if missing:
            await self.transport.send(SyncResponse(qsos=missing))
