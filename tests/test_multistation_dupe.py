"""Dupe checking spans the whole networked station, not just the local op.

In a multi-op contest the dupe rule applies to the combined log: once *anyone*
on the network has worked a station (in the slot the contest's dupe_key defines),
it's a dupe for everyone. This is a consequence of the shared CRDT log — every
op's QSOs merge into one log that the dupe index is built from.
"""

from __future__ import annotations

from partyhams.app.session import LogSession
from partyhams.contest import get as get_contest
from partyhams.contest.base import ContestConfig
from partyhams.core.clock import new_station_id
from partyhams.core.models import Mode
from partyhams.db.store import SqliteLog
from partyhams.net.engine import SyncEngine
from partyhams.net.loopback import LoopbackBus, LoopbackTransport

NETWORK = "fd-net"
FREQ_20M = 14_040_000
FREQ_40M = 7_040_000


def _make_session(bus: LoopbackBus, call: str) -> LogSession:
    transport = LoopbackTransport(bus, NETWORK, station_id=new_station_id())
    config = ContestConfig(
        my_call=call,
        sent_exchange={"class": "2A", "section": "OR"},
        extra={"power": "low_150w", "bonus_points": 0},
    )
    engine = SyncEngine(transport, operator=call, call=call)
    return LogSession(
        contest=get_contest("arrl-field-day"),
        config=config,
        engine=engine,
        store=SqliteLog(":memory:"),
    )


async def _converge(*sessions: LogSession, max_rounds: int = 200) -> None:
    for _ in range(max_rounds):
        progressed = False
        for s in sessions:
            if await s.engine.pump_once():
                progressed = True
        if not progressed:
            return
    raise AssertionError("sessions did not reach a quiescent state")


async def test_peer_qso_makes_call_a_dupe_for_everyone():
    bus = LoopbackBus()
    a = _make_session(bus, "W0CPH")
    b = _make_session(bus, "N0AW")
    await a.engine.join()
    await b.engine.join()
    await _converge(a, b)

    # B has not worked K1ABC yet.
    assert not b.is_dupe("K1ABC", FREQ_20M, Mode.CW)

    # A works K1ABC on 20m CW; once it syncs, it's a dupe for B too.
    await a.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    await _converge(a, b)
    assert b.is_dupe("K1ABC", FREQ_20M, Mode.CW)
    assert b.dupe_label("K1ABC", FREQ_20M, Mode.CW) == "DUPE"


async def test_peer_qso_respects_contest_dupe_rule_band_and_mode():
    """Field Day's dupe key is per band AND per mode group — a peer's 20m-CW QSO
    leaves the same call workable on another band or in another mode category."""
    bus = LoopbackBus()
    a = _make_session(bus, "W0CPH")
    b = _make_session(bus, "N0AW")
    await a.engine.join()
    await b.engine.join()

    await a.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1D", "section": "WY"}
    )
    await _converge(a, b)

    assert b.is_dupe("K1ABC", FREQ_20M, Mode.CW)  # same slot -> dupe
    assert not b.is_dupe("K1ABC", FREQ_40M, Mode.CW)  # different band -> workable
    assert not b.is_dupe("K1ABC", FREQ_20M, Mode.USB)  # different mode group -> workable
