"""Pure clock-sync helpers for the network roster.

Contest logging needs every operator's UTC timestamps aligned, so each station
advertises its current UTC time in its periodic :class:`~partyhams.net.protocol.Heartbeat`.
A receiver compares that advertised time to its own ``utcnow()`` and flags a peer
whose *apparent* offset exceeds :data:`CLOCK_OFF_THRESHOLD_S`.

LATENCY CAVEAT: over UDP multicast you cannot measure absolute clock skew — the
one-way network transit time (typically a few ms on a LAN, but unbounded in the
general case) is folded into the apparent offset, and we never see the round-trip
so we cannot subtract it out. The numbers here are therefore a *best-effort*
indicator, not a precise measurement: a small apparent offset is far more likely
transit latency than a real misconfigured clock. The threshold is deliberately
set at the spec's 0.2s alignment target; anything under that is treated as fine.

These functions are deliberately pure (no Qt, no implicit wall-clock reads — the
caller passes ``local_now``) so they are trivially unit-testable.
"""

from __future__ import annotations

from datetime import datetime

#: Apparent-offset threshold, in seconds. Matches the spec's 0.2s alignment
#: target. Apparent offsets below this are treated as in-sync (and are in any
#: case within the noise of network transit latency — see the module docstring).
CLOCK_OFF_THRESHOLD_S = 0.2


def clock_offset_seconds(sender_iso: str, local_now: datetime) -> float | None:
    """Apparent clock offset of a peer, in seconds (peer-ahead is positive).

    ``sender_iso`` is the UTC time the peer advertised (ISO-8601), ``local_now``
    is our own ``utcnow()`` at receipt. Returns ``sender - local`` in seconds, so
    a peer whose clock is 1.5s ahead of ours yields ``+1.5``; one 1.5s behind
    yields ``-1.5``. Returns ``None`` if the peer sent no/blank/unparseable time
    (e.g. an older build that predates this field).

    NOTE: this is an *apparent* offset that includes one-way network transit
    latency; see the module docstring. Do not treat it as exact.
    """
    if not sender_iso:
        return None
    try:
        sender = datetime.fromisoformat(sender_iso)
    except (ValueError, TypeError):
        return None
    return (sender - local_now).total_seconds()


def is_clock_off(offset: float | None, threshold: float = CLOCK_OFF_THRESHOLD_S) -> bool:
    """True iff a peer's apparent ``offset`` (seconds) exceeds ``threshold``.

    ``None`` (offset unknown) is treated as not-off. The comparison is on the
    magnitude, so a clock that is off in either direction is flagged.
    """
    if offset is None:
        return False
    return abs(offset) > threshold
