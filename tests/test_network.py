"""Network panel backend: station roster, per-station QSO rates, and chat routing."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from factories import make_qso

from partyhams.app.session import build_session
from partyhams.core.models import Mode, utcnow
from partyhams.net.engine import SyncEngine
from partyhams.net.loopback import LoopbackBus, LoopbackTransport


def make_session():
    return build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        operator="N0AW",
        sent_exchange={"class": "2A", "section": "OR"},
        power="low_150w",
        network=None,
    )


# --- roster + rates ------------------------------------------------------- #
def test_roster_includes_self():
    s = make_session()
    s.set_local_status(14_040_000, Mode.CW)
    roster = s.roster()
    assert len(roster) == 1
    me = roster[0]
    assert me["is_self"] is True
    assert me["operator"] == "N0AW"
    assert me["freq_hz"] == 14_040_000
    assert me["mode"] == "CW"


def test_station_rates_windows():
    s = make_session()
    now = utcnow()
    sid = s.engine.station_id
    # QSOs at 2, 10, 20, and 45 minutes ago, all from this station.
    for minutes in (2, 10, 20, 45):
        q = make_qso("K1ABC", station_id=sid)
        q.timestamp = now - timedelta(minutes=minutes)
        s.engine.log.apply(q)
    rates = s.station_rates(sid, now=now)
    assert 5 not in rates
    assert rates[15] == 2  # 2 + 10
    assert rates[30] == 3  # 2 + 10 + 20
    assert rates[60] == 4  # all four


def test_station_total_counts_whole_log():
    s = make_session()
    now = utcnow()
    sid = s.engine.station_id
    # Four QSOs, one of them well outside every rate window.
    for minutes in (2, 10, 20, 600):
        q = make_qso("K1ABC", station_id=sid)
        q.timestamp = now - timedelta(minutes=minutes)
        s.engine.log.apply(q)
    assert s.station_total(sid) == 4  # ignores time windows
    assert s.station_total("someone-else") == 0


def test_station_stats_hour_and_mode_breakdown():
    s = make_session()
    sid = s.engine.station_id
    exch = {"class": "1A", "section": "EPA"}
    s.record_qso(call="K1A", freq_hz=14_040_000, mode=Mode.CW, exchange=exch)
    s.record_qso(call="K2B", freq_hz=14_040_000, mode=Mode.CW, exchange=exch)
    s.record_qso(call="K3C", freq_hz=14_200_000, mode=Mode.USB, exchange=exch)
    stats = s.station_stats(sid)
    assert stats["total"] == 3
    assert stats["by_mode"] == {"CW": 2, "USB": 1}
    assert sum(stats["by_hour"]) == 3
    assert len(stats["by_hour"]) == 24
    assert stats["first"] is not None and stats["last"] is not None
    # An unknown station has an empty, well-formed result.
    empty = s.station_stats("nobody")
    assert empty["total"] == 0 and empty["first"] is None and sum(empty["by_hour"]) == 0


def test_remote_status_appears_in_roster():
    bus = LoopbackBus()
    local = make_session()  # uses NullTransport; swap in a loopback transport
    local.engine.transport = LoopbackTransport(bus, "evt", local.engine.station_id)

    # A peer station announces its status onto the bus.
    peer_t = LoopbackTransport(bus, "evt", "peer123")
    peer = SyncEngine(peer_t, operator="W7XYZ", call="W7XYZ")
    peer.update_status(freq_hz=7_030_000, mode="USB")

    async def run():
        await local.engine.transport.start()
        await peer_t.start()
        await peer.send_status()
        await local.engine.pump_once()

    asyncio.run(run())

    ops = {r["operator"] for r in local.roster()}
    assert ops == {"N0AW", "W7XYZ"}
    peer_row = next(r for r in local.roster() if r["operator"] == "W7XYZ")
    assert peer_row["freq_hz"] == 7_030_000
    assert peer_row["mode"] == "USB"
    assert peer_row["is_self"] is False


def test_peer_marked_silent_after_two_minutes():
    s = make_session()
    now = utcnow()
    sid = "peer123"
    s.engine.stations[sid] = {
        "operator": "W7XYZ",
        "call": "W7XYZ",
        "freq_hz": 7_030_000,
        "mode": "USB",
        "power_w": 0.0,
        "swr": 0.0,
        "ft_tx_even": -1,
        "last_heard": now - timedelta(seconds=10),
    }
    # Just heard from — not silent (and not yet stale).
    row = next(r for r in s.roster() if r["station_id"] == sid)
    assert row["silent"] is False
    assert row["stale"] is False

    # No presence beat for over two minutes — flagged silent (but not yet gone).
    s.engine.stations[sid]["last_heard"] = now - timedelta(seconds=130)
    row = next(r for r in s.roster() if r["station_id"] == sid)
    assert row["silent"] is True
    assert row["gone"] is False
    assert row["stale"] is True
    assert row["silent_secs"] >= 120

    # No presence beat for over five minutes — flagged gone (struck through).
    s.engine.stations[sid]["last_heard"] = now - timedelta(seconds=310)
    row = next(r for r in s.roster() if r["station_id"] == sid)
    assert row["gone"] is True
    assert row["silent"] is True


def test_self_is_never_silent_or_gone():
    s = make_session()
    me = next(r for r in s.roster() if r["is_self"])
    assert me["silent"] is False
    assert me["gone"] is False
    assert me["silent_secs"] is None


# --- chat ----------------------------------------------------------------- #
def test_post_chat_records_and_notifies():
    s = make_session()
    seen = []
    s.add_chat_listener(seen.append)
    entry = s.post_chat("*", "CQ from N0AW")
    assert entry["from_op"] == "N0AW"
    assert entry["incoming"] is False
    assert seen == [entry]
    assert s.chat_messages()[-1]["text"] == "CQ from N0AW"


def test_incoming_chat_filtering():
    from partyhams.net.protocol import Chat

    s = make_session()  # our operator is N0AW
    got = []
    s.add_chat_listener(got.append)

    s.engine.on_chat(Chat(from_op="W7XYZ", to_op="*", text="hi all", ts="t"), "peer")
    s.engine.on_chat(Chat(from_op="W7XYZ", to_op="N0AW", text="hi N0AW", ts="t"), "peer")
    s.engine.on_chat(Chat(from_op="W7XYZ", to_op="K9ZZZ", text="not for us", ts="t"), "peer")

    texts = [e["text"] for e in got]
    assert texts == ["hi all", "hi N0AW"]  # the DM to K9ZZZ is filtered out
    assert all(e["incoming"] for e in got)
