"""Identity and ordering primitives for peer-to-peer log merge.

Every QSO carries a UUID (stable identity across stations) and a Lamport logical
clock value. When two stations edit the same QSO, the merge rule is
last-writer-wins ordered by ``(lamport, station_id)`` so the outcome is identical
on every node regardless of packet arrival order. See ``net/sync.py``.
"""

from __future__ import annotations

import uuid


def new_uuid() -> str:
    """A globally-unique QSO/record id (uuid4 hex)."""
    return uuid.uuid4().hex


def new_station_id() -> str:
    """A short, stable per-station identifier, generated once per install."""
    return uuid.uuid4().hex[:8]


class LamportClock:
    """A minimal Lamport logical clock.

    ``tick()`` is called on every local event; ``update(remote)`` is called when a
    message is received so this node's clock never lags a peer it has heard from.
    """

    __slots__ = ("_value",)

    def __init__(self, value: int = 0) -> None:
        self._value = value

    @property
    def value(self) -> int:
        return self._value

    def tick(self) -> int:
        self._value += 1
        return self._value

    def update(self, remote: int) -> int:
        self._value = max(self._value, remote) + 1
        return self._value
