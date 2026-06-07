"""Peer-to-peer merge: convergence regardless of arrival order, LWW, catch-up."""

from __future__ import annotations

import random

from factories import make_qso

from partyhams.net.sync import LogMerge


def test_lww_higher_lamport_wins_either_order():
    v1 = make_qso("K1A", uuid="same", station_id="s1", lamport=1)
    v2 = make_qso(
        "K1A", uuid="same", station_id="s1", lamport=2, exchange={"class": "3A", "section": "OR"}
    )

    a = LogMerge()
    a.apply(v1)
    a.apply(v2)

    b = LogMerge()
    b.apply(v2)  # reverse arrival order
    b.apply(v1)

    assert a.get("same").lamport == 2
    assert b.get("same").lamport == 2
    assert a.get("same").exchange_rcvd == {"class": "3A", "section": "OR"}
    assert a.log_hash() == b.log_hash()


def test_equal_lamport_breaks_by_station_id():
    low = make_qso("K1A", uuid="same", station_id="s1", lamport=5)
    high = make_qso("K1A", uuid="same", station_id="s9", lamport=5)
    m = LogMerge()
    m.apply(low)
    m.apply(high)
    assert m.get("same").station_id == "s9"  # larger station_id wins the tie


def test_convergence_under_shuffled_delivery():
    # A batch of records (including edits of the same uuid) converges to the same
    # log_hash no matter what order each station receives them in.
    base = [make_qso(f"K{i}", uuid=f"u{i}", station_id="s1", lamport=1) for i in range(10)]
    edits = [make_qso(f"K{i}", uuid=f"u{i}", station_id="s2", lamport=2) for i in range(0, 10, 2)]
    events = base + edits

    hashes = set()
    rng = random.Random(12345)
    for _ in range(20):
        order = events[:]
        rng.shuffle(order)
        m = LogMerge()
        for e in order:
            m.apply(e)
        hashes.add(m.log_hash())
    assert len(hashes) == 1  # all orderings converge


def test_deleted_tombstone_hides_but_persists():
    m = LogMerge()
    m.apply(make_qso("K1A", uuid="u1", lamport=1))
    assert len(m) == 1
    m.apply(make_qso("K1A", uuid="u1", lamport=2, deleted=True))
    assert len(m) == 0  # hidden from active count
    assert m.get("u1") is not None  # tombstone retained for convergence


def test_diff_since_returns_only_missing():
    m = LogMerge()
    m.apply(make_qso("K1A", uuid="u1", station_id="s1", lamport=1))
    m.apply(make_qso("K2B", uuid="u2", station_id="s1", lamport=3))
    m.apply(make_qso("K3C", uuid="u3", station_id="s2", lamport=2))

    # A peer that has seen s1 up to lamport 1 and nothing from s2.
    missing = m.diff_since({"s1": 1})
    uuids = {q.uuid for q in missing}
    assert uuids == {"u2", "u3"}  # u1 already known, u2/u3 are new


def test_high_water_marks():
    m = LogMerge()
    m.apply(make_qso("K1A", uuid="u1", station_id="s1", lamport=4))
    m.apply(make_qso("K2B", uuid="u2", station_id="s1", lamport=7))
    m.apply(make_qso("K3C", uuid="u3", station_id="s2", lamport=2))
    assert m.high_water() == {"s1": 7, "s2": 2}
