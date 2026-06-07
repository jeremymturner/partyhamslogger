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
