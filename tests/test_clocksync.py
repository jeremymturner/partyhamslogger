"""Clock-sync monitoring: the pure offset helpers + the engine heartbeat path.

The pure functions are tested with an injected ``local_now`` and a constructed
sender time, so there is no dependence on real wall-clock drift. The engine test
feeds a heartbeat with a deliberately skewed ``sender_utc`` over the loopback bus
and asserts the receiver records the offset / off-flag for that station.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from partyhams.core.clock import new_station_id
from partyhams.core.models import utcnow
from partyhams.net.clocksync import (
    CLOCK_OFF_THRESHOLD_S,
    clock_offset_seconds,
    is_clock_off,
)
from partyhams.net.engine import SyncEngine
from partyhams.net.loopback import LoopbackBus, LoopbackTransport
from partyhams.net.protocol import Heartbeat, StationStatus

NETWORK = "test-net"
_NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def test_offset_sender_ahead_is_positive():
    sender = (_NOW + timedelta(seconds=1.5)).isoformat()
    offset = clock_offset_seconds(sender, _NOW)
    assert offset is not None
    assert abs(offset - 1.5) < 1e-6


def test_offset_sender_behind_is_negative():
    sender = (_NOW - timedelta(seconds=1.5)).isoformat()
    offset = clock_offset_seconds(sender, _NOW)
    assert offset is not None
    assert abs(offset + 1.5) < 1e-6


def test_offset_none_for_blank_or_unparseable():
    assert clock_offset_seconds("", _NOW) is None
    assert clock_offset_seconds("not-a-time", _NOW) is None


def test_is_clock_off_beyond_threshold():
    assert is_clock_off(1.5) is True
    assert is_clock_off(-1.5) is True
    assert is_clock_off(0.9) is True


def test_is_clock_off_within_threshold():
    assert is_clock_off(0.0) is False
    assert is_clock_off(0.3) is False  # well within the 0.8s threshold now
    assert is_clock_off(-0.79) is False
    assert is_clock_off(CLOCK_OFF_THRESHOLD_S) is False  # boundary: not "exceeds"
    assert is_clock_off(None) is False


# --------------------------------------------------------------------------- #
# engine path (injected skew, deterministic)
# --------------------------------------------------------------------------- #
async def _make_engine(bus: LoopbackBus, call: str, **kw) -> SyncEngine:
    transport = LoopbackTransport(bus, NETWORK, station_id=new_station_id())
    engine = SyncEngine(transport, operator=call, call=call, **kw)
    await engine.join()
    return engine


async def test_engine_records_offset_and_flag_for_skewed_peer():
    bus = LoopbackBus()
    a = await _make_engine(bus, "W1AAA")
    b = await _make_engine(bus, "K2BBB")

    # A learns about B first (so B has a station row to annotate).
    await b.transport.send(StationStatus(operator="K2BBB", call="K2BBB", freq_hz=0, mode="CW"))
    await a.pump_once()

    skewed = (utcnow() + timedelta(seconds=5)).isoformat()
    await b.transport.send(
        Heartbeat(count=0, log_hash=a.log.log_hash(), lamport_max=0, sender_utc=skewed)
    )
    await a.pump_once()

    row = a.stations[b.station_id]
    assert row["clock_off"] is True
    assert row["clock_offset"] > CLOCK_OFF_THRESHOLD_S


async def test_engine_in_sync_peer_not_flagged():
    bus = LoopbackBus()
    a = await _make_engine(bus, "W1AAA")
    b = await _make_engine(bus, "K2BBB")

    await b.transport.send(StationStatus(operator="K2BBB", call="K2BBB", freq_hz=0, mode="CW"))
    await a.pump_once()

    in_sync = utcnow().isoformat()
    await b.transport.send(
        Heartbeat(count=0, log_hash=a.log.log_hash(), lamport_max=0, sender_utc=in_sync)
    )
    await a.pump_once()

    assert a.stations[b.station_id]["clock_off"] is False


async def test_engine_announces_once_via_callback_debounced():
    bus = LoopbackBus()
    fired: list[tuple[str, float]] = []
    a = await _make_engine(bus, "W1AAA", on_clock_off=lambda op, off: fired.append((op, off)))
    b = await _make_engine(bus, "K2BBB")

    await b.transport.send(StationStatus(operator="K2BBB", call="K2BBB", freq_hz=0, mode="CW"))
    await a.pump_once()

    skewed = (utcnow() + timedelta(seconds=5)).isoformat()
    for _ in range(3):  # three heartbeats at the same skew
        await b.transport.send(
            Heartbeat(count=0, log_hash=a.log.log_hash(), lamport_max=0, sender_utc=skewed)
        )
        await a.pump_once()

    # Debounced: a steady offset only announces once, not on every heartbeat.
    assert len(fired) == 1
    op, off = fired[0]
    assert op == "K2BBB"
    assert off > CLOCK_OFF_THRESHOLD_S
