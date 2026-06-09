"""SQLite-backed QSO log.

Mirrors the peer-to-peer merge rule at the persistence layer: :meth:`upsert`
applies last-writer-wins by ``(lamport, station_id)``, so feeding it a stream of
local edits and remote sync messages converges to the same log on every station.
Exchange dicts are stored as JSON text; everything else gets its own column for
queryability.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from partyhams.core.models import QSO, Mode

_SCHEMA = """
CREATE TABLE IF NOT EXISTS qso (
    uuid           TEXT PRIMARY KEY,
    station_id     TEXT NOT NULL,
    operator       TEXT NOT NULL,
    lamport        INTEGER NOT NULL,
    deleted        INTEGER NOT NULL DEFAULT 0,
    call           TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    freq_hz        INTEGER NOT NULL,
    mode           TEXT NOT NULL,
    rst_sent       TEXT NOT NULL DEFAULT '',
    rst_rcvd       TEXT NOT NULL DEFAULT '',
    serial_sent    INTEGER,
    exchange_rcvd  TEXT NOT NULL DEFAULT '{}',
    exchange_sent  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_qso_call ON qso(call);
CREATE INDEX IF NOT EXISTS idx_qso_station ON qso(station_id);

-- Log metadata (contest id, station config, etc.) so a log file is self-describing.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SqliteLog:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)  # ":memory:" for transient logs (e.g. tests)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- log metadata (key/value) ---
    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row is not None else default

    def all_meta(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._conn.execute("SELECT key, value FROM meta")}

    def upsert(self, qso: QSO) -> bool:
        """Insert or update under last-writer-wins. Returns True if state changed."""
        cur = self._conn.execute("SELECT lamport, station_id FROM qso WHERE uuid = ?", (qso.uuid,))
        row = cur.fetchone()
        if row is not None:
            existing = (row["lamport"], row["station_id"])
            incoming = (qso.lamport, qso.station_id)
            if incoming <= existing:  # tuple compare == LWW with station_id tiebreak
                return False
        self._conn.execute(
            """
            INSERT INTO qso (uuid, station_id, operator, lamport, deleted, call,
                             timestamp, freq_hz, mode, rst_sent, rst_rcvd,
                             serial_sent, exchange_rcvd, exchange_sent)
            VALUES (:uuid, :station_id, :operator, :lamport, :deleted, :call,
                    :timestamp, :freq_hz, :mode, :rst_sent, :rst_rcvd,
                    :serial_sent, :exchange_rcvd, :exchange_sent)
            ON CONFLICT(uuid) DO UPDATE SET
                station_id=excluded.station_id, operator=excluded.operator,
                lamport=excluded.lamport, deleted=excluded.deleted,
                call=excluded.call, timestamp=excluded.timestamp,
                freq_hz=excluded.freq_hz, mode=excluded.mode,
                rst_sent=excluded.rst_sent, rst_rcvd=excluded.rst_rcvd,
                serial_sent=excluded.serial_sent,
                exchange_rcvd=excluded.exchange_rcvd,
                exchange_sent=excluded.exchange_sent
            """,
            self._to_row(qso),
        )
        self._conn.commit()
        return True

    def all(self, include_deleted: bool = False) -> list[QSO]:
        sql = "SELECT * FROM qso"
        if not include_deleted:
            sql += " WHERE deleted = 0"
        sql += " ORDER BY timestamp, uuid"
        return [self._from_row(r) for r in self._conn.execute(sql)]

    # --- mapping ---
    @staticmethod
    def _to_row(q: QSO) -> dict:
        return {
            "uuid": q.uuid,
            "station_id": q.station_id,
            "operator": q.operator,
            "lamport": q.lamport,
            "deleted": int(q.deleted),
            "call": q.call,
            "timestamp": q.timestamp.isoformat(),
            "freq_hz": q.freq_hz,
            "mode": q.mode.value,
            "rst_sent": q.rst_sent,
            "rst_rcvd": q.rst_rcvd,
            "serial_sent": q.serial_sent,
            "exchange_rcvd": json.dumps(q.exchange_rcvd),
            "exchange_sent": json.dumps(q.exchange_sent),
        }

    @staticmethod
    def _from_row(r: sqlite3.Row) -> QSO:
        return QSO(
            uuid=r["uuid"],
            station_id=r["station_id"],
            operator=r["operator"],
            lamport=r["lamport"],
            deleted=bool(r["deleted"]),
            call=r["call"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
            freq_hz=r["freq_hz"],
            mode=Mode(r["mode"]),
            rst_sent=r["rst_sent"],
            rst_rcvd=r["rst_rcvd"],
            serial_sent=r["serial_sent"],
            exchange_rcvd=json.loads(r["exchange_rcvd"]),
            exchange_sent=json.loads(r["exchange_sent"]),
        )
