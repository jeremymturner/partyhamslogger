"""Deterministic log-merge logic for peer-to-peer sync.

Pure and transport-free so it can be unit-tested without sockets. The transport
(``net/transport.py``) feeds decoded :class:`~partyhams.core.models.QSO` records
into a :class:`LogMerge`; the merge result is identical on every node regardless
of the order datagrams arrive.

**Merge rule (last-writer-wins):** for a given ``uuid``, the record with the
higher ``lamport`` wins; ties are broken by the larger ``station_id`` (a stable,
arbitrary-but-consistent tiebreak). This is associative and commutative, so all
peers converge.
"""

from __future__ import annotations

import hashlib

from partyhams.core.models import QSO


class LogMerge:
    """An in-memory CRDT-style register-per-QSO keyed by ``uuid``."""

    def __init__(self) -> None:
        self._by_uuid: dict[str, QSO] = {}

    # --- mutation ---
    def apply(self, qso: QSO) -> bool:
        """Upsert ``qso`` under last-writer-wins. Returns True if state changed."""
        existing = self._by_uuid.get(qso.uuid)
        if existing is None or self._wins(qso, existing):
            self._by_uuid[qso.uuid] = qso
            return True
        return False

    @staticmethod
    def _wins(incoming: QSO, existing: QSO) -> bool:
        if incoming.lamport != existing.lamport:
            return incoming.lamport > existing.lamport
        return incoming.station_id > existing.station_id

    # --- queries ---
    def qsos(self, include_deleted: bool = False) -> list[QSO]:
        out = [q for q in self._by_uuid.values() if include_deleted or not q.deleted]
        out.sort(key=lambda q: (q.timestamp, q.uuid))
        return out

    def get(self, uuid: str) -> QSO | None:
        return self._by_uuid.get(uuid)

    def __len__(self) -> int:
        return sum(1 for q in self._by_uuid.values() if not q.deleted)

    # --- anti-entropy / catch-up ---
    def high_water(self) -> dict[str, int]:
        """Max lamport seen per originating ``station_id`` (for delta requests)."""
        hw: dict[str, int] = {}
        for q in self._by_uuid.values():
            if q.lamport > hw.get(q.station_id, 0):
                hw[q.station_id] = q.lamport
        return hw

    def diff_since(self, remote_hw: dict[str, int]) -> list[QSO]:
        """Records a peer (at ``remote_hw``) is missing.

        Catches new records and origin-side edits. Cross-station edits are caught
        by the heartbeat ``log_hash`` divergence check, which triggers a full
        reconciliation sync as a backstop. (TODO: full version-vector anti-entropy.)
        """
        out: list[QSO] = []
        for q in self._by_uuid.values():
            if q.lamport > remote_hw.get(q.station_id, 0):
                out.append(q)
        return out

    def log_hash(self) -> str:
        """A stable digest of merge state, for divergence detection in heartbeats.

        Two converged logs produce the same hash. Because every edit bumps
        ``lamport``, this captures edits as well as adds/deletes.
        """
        h = hashlib.sha1()
        for uuid in sorted(self._by_uuid):
            q = self._by_uuid[uuid]
            h.update(f"{uuid}:{q.lamport}:{q.station_id}:{int(q.deleted)}\n".encode())
        return h.hexdigest()
