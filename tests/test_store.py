"""SQLite log store: persistence and last-writer-wins on upsert."""

from __future__ import annotations

from factories import make_qso

from partyhams.core.models import Mode
from partyhams.db import SqliteLog


def test_insert_and_read_back():
    log = SqliteLog()
    q = make_qso("K1ABC", mode=Mode.USB, exchange={"class": "3A", "section": "OR"})
    assert log.upsert(q) is True
    rows = log.all()
    assert len(rows) == 1
    got = rows[0]
    assert got.call == "K1ABC"
    assert got.mode is Mode.USB
    assert got.exchange_rcvd == {"class": "3A", "section": "OR"}
    assert got.timestamp == q.timestamp
    assert got.operator == "OP1"
    assert got.station_callsign == "W0CPH"  # ADIF STATION_CALLSIGN persists


def test_migrates_log_without_station_callsign_column():
    """An older log file (no station_callsign column) opens and reads cleanly."""
    import sqlite3
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp()) / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE qso (
            uuid TEXT PRIMARY KEY, station_id TEXT NOT NULL, operator TEXT NOT NULL,
            lamport INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, call TEXT NOT NULL,
            timestamp TEXT NOT NULL, freq_hz INTEGER NOT NULL, mode TEXT NOT NULL,
            rst_sent TEXT NOT NULL DEFAULT '', rst_rcvd TEXT NOT NULL DEFAULT '',
            serial_sent INTEGER, exchange_rcvd TEXT NOT NULL DEFAULT '{}',
            exchange_sent TEXT NOT NULL DEFAULT '{}');
        INSERT INTO qso (uuid, station_id, operator, lamport, deleted, call, timestamp,
                         freq_hz, mode)
        VALUES ('u1', 's1', 'N0AW', 1, 0, 'K1ABC', '2026-06-07T18:00:00+00:00', 14040000, 'CW');
        """
    )
    conn.commit()
    conn.close()

    log = SqliteLog(path)
    got = log.all()[0]
    assert got.operator == "N0AW"
    assert got.station_callsign == ""  # back-filled empty for legacy rows


def test_upsert_lww():
    log = SqliteLog()
    log.upsert(make_qso("K1A", uuid="u1", station_id="s1", lamport=1))
    # Stale update is rejected.
    assert log.upsert(make_qso("K1A", uuid="u1", station_id="s1", lamport=1)) is False
    # Newer update wins.
    assert (
        log.upsert(
            make_qso(
                "K1A",
                uuid="u1",
                station_id="s1",
                lamport=2,
                exchange={"class": "9A", "section": "DX"},
            )
        )
        is True
    )
    assert log.all()[0].exchange_rcvd == {"class": "9A", "section": "DX"}


def test_deleted_excluded_by_default():
    log = SqliteLog()
    log.upsert(make_qso("K1A", uuid="u1", lamport=1))
    log.upsert(make_qso("K1A", uuid="u1", lamport=2, deleted=True))
    assert log.all() == []
    assert len(log.all(include_deleted=True)) == 1
