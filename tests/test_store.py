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


def test_upsert_lww():
    log = SqliteLog()
    log.upsert(make_qso("K1A", uuid="u1", station_id="s1", lamport=1))
    # Stale update is rejected.
    assert log.upsert(make_qso("K1A", uuid="u1", station_id="s1", lamport=1)) is False
    # Newer update wins.
    assert log.upsert(
        make_qso("K1A", uuid="u1", station_id="s1", lamport=2, exchange={"class": "9A", "section": "DX"})
    ) is True
    assert log.all()[0].exchange_rcvd == {"class": "9A", "section": "DX"}


def test_deleted_excluded_by_default():
    log = SqliteLog()
    log.upsert(make_qso("K1A", uuid="u1", lamport=1))
    log.upsert(make_qso("K1A", uuid="u1", lamport=2, deleted=True))
    assert log.all() == []
    assert len(log.all(include_deleted=True)) == 1
