"""Test helpers for building QSOs deterministically."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

from partyhams.core.models import QSO, Mode

_counter = itertools.count(1)

# Convenient band-center frequencies.
FREQ = {
    "20m": 14_040_000,
    "40m": 7_030_000,
    "15m": 21_300_000,
    "80m": 3_540_000,
}


def make_qso(
    call: str,
    freq_hz: int = FREQ["20m"],
    mode: Mode = Mode.CW,
    *,
    uuid: str | None = None,
    station_id: str = "s1",
    operator: str = "OP1",
    station_callsign: str = "W0CPH",
    lamport: int = 1,
    deleted: bool = False,
    exchange: dict[str, str] | None = None,
) -> QSO:
    return QSO(
        uuid=uuid or f"u{next(_counter)}",
        station_id=station_id,
        operator=operator,
        station_callsign=station_callsign,
        lamport=lamport,
        deleted=deleted,
        call=call,
        timestamp=datetime(2026, 6, 27, 18, 0, 0, tzinfo=UTC),
        freq_hz=freq_hz,
        mode=mode,
        rst_sent="599",
        rst_rcvd="599",
        exchange_rcvd=exchange or {"class": "2A", "section": "EPA"},
    )
