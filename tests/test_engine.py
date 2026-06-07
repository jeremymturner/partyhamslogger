"""SyncEngine convergence over the in-memory loopback bus.

These drive the engine deterministically (manual ``pump_once``, no background
tasks or sleeps) so they're fast and CI-stable, while still exercising the real
wire format via the loopback transport.
"""

from __future__ import annotations

import itertools

from partyhams.core.clock import new_station_id
from partyhams.core.models import Mode
from partyhams.net.engine import SyncEngine
from partyhams.net.loopback import LoopbackBus, LoopbackTransport
from partyhams.net.protocol import QsoMessage

NETWORK = "test-net"
_FREQ = 14_040_000


async def make_engine(bus: LoopbackBus, call: str, network: str = NETWORK) -> SyncEngine:
    transport = LoopbackTransport(bus, network, station_id=new_station_id())
    engine = SyncEngine(transport, operator=call, call=call)
    await engine.join()
    return engine


async def converge(*engines: SyncEngine, max_rounds: int = 200) -> None:
    """Pump all engines until no messages remain to process."""
    for _ in range(max_rounds):
        progressed = False
        for engine in engines:
            if await engine.pump_once():
                progressed = True
        if not progressed:
            return
    raise AssertionError("engines did not reach a quiescent state")


def assert_converged(*engines: SyncEngine) -> None:
    hashes = {e.log.log_hash() for e in engines}
    counts = {len(e.log) for e in engines}
    assert len(hashes) == 1, f"log hashes diverged: {hashes}"
    assert len(counts) == 1, f"qso counts diverged: {counts}"


async def log_some(engine: SyncEngine, n: int, prefix: str) -> None:
    for i in range(n):
        await engine.log_qso(
            call=f"{prefix}{i:03d}",
            freq_hz=_FREQ,
            mode=Mode.CW,
            exchange_rcvd={"class": "1B", "section": "DX"},
        )


async def test_live_qso_propagates_both_ways():
    bus = LoopbackBus()
    a = await make_engine(bus, "W1AAA")
    b = await make_engine(bus, "K2BBB")

    await a.log_qso(call="DX1", freq_hz=_FREQ, mode=Mode.CW)
    await converge(a, b)
    assert [q.call for q in b.log.qsos()] == ["DX1"]

    await b.log_qso(call="DX2", freq_hz=_FREQ, mode=Mode.USB)
    await converge(a, b)
    assert {q.call for q in a.log.qsos()} == {"DX1", "DX2"}
    assert_converged(a, b)


async def test_three_stations_converge():
    bus = LoopbackBus()
    a = await make_engine(bus, "W1AAA")
    b = await make_engine(bus, "K2BBB")
    c = await make_engine(bus, "N3CCC")

    await log_some(a, 3, "AAA")
    await log_some(b, 2, "BBB")
    await log_some(c, 4, "CCC")
    await converge(a, b, c)

    assert_converged(a, b, c)
    assert len(a.log) == 9


async def test_late_joiner_catches_up_via_hello():
    bus = LoopbackBus()
    a = await make_engine(bus, "W1AAA")
    await log_some(a, 5, "PRE")  # logged before anyone else is present

    # New station joins; its Hello should prompt A to send the backlog.
    c = await make_engine(bus, "N3CCC")
    await converge(a, c)

    assert len(c.log) == 5
    assert_converged(a, c)


async def test_heartbeat_reconciles_after_dropped_packets():
    bus = LoopbackBus()
    a = await make_engine(bus, "W1AAA")
    b = await make_engine(bus, "K2BBB")

    # Partition A's outbound traffic, then log — B misses these entirely.
    bus.partitioned.add(a.station_id)
    await log_some(a, 2, "LOST")
    await converge(a, b)
    assert len(b.log) == 0  # B heard nothing

    # Heal the partition. A's next heartbeat advertises a different log hash;
    # B notices the divergence and requests the delta.
    bus.partitioned.discard(a.station_id)
    await a.send_heartbeat()
    await converge(a, b)

    assert len(b.log) == 2
    assert_converged(a, b)


async def test_edit_wins_by_lamport_across_stations():
    bus = LoopbackBus()
    a = await make_engine(bus, "W1AAA")
    b = await make_engine(bus, "K2BBB")

    qso = await a.log_qso(
        call="DX9", freq_hz=_FREQ, mode=Mode.CW, exchange_rcvd={"class": "1B", "section": "OR"}
    )
    await converge(a, b)
    assert b.log.get(qso.uuid).exchange_rcvd["section"] == "OR"

    # A corrects the section; the higher lamport must win everywhere.
    qso.exchange_rcvd = {"class": "1B", "section": "WA"}
    qso.lamport = a.clock.tick()
    a.log.apply(qso)
    await a.transport.send(QsoMessage(qso=qso))
    await converge(a, b)
    assert b.log.get(qso.uuid).exchange_rcvd["section"] == "WA"
    assert_converged(a, b)


async def test_separate_networks_do_not_cross_talk():
    bus = LoopbackBus()
    a = await make_engine(bus, "W1AAA", network="field-day")
    other = await make_engine(bus, "K9ZZZ", network="some-other-event")

    await log_some(a, 3, "FD")
    await converge(a, other)
    assert len(other.log) == 0  # different network name => ignored


async def test_concurrent_logging_converges():
    bus = LoopbackBus()
    engines = [await make_engine(bus, c) for c in ("W1A", "W2B", "W3C", "W4D")]

    # Interleave logging across all stations.
    for round_no, engine in zip(range(3), itertools.cycle(engines)):
        await log_some(engine, 2, f"R{round_no}")
    await converge(*engines)

    assert_converged(*engines)
