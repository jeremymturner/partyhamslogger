"""Section map: the who-worked-it aggregation and the schematic layout table.

Pure logic only — no Qt. ``section_detail`` is exercised across multiple bands,
modes, and operators; the layout table is checked for full coverage of the real
section enumeration (every section has a cell, no orphans, no two on one cell).
"""

from __future__ import annotations

from partyhams.app.session import build_session
from partyhams.contest.sections import ARRL_SECTIONS, SECTION_MAP_LAYOUT
from partyhams.core.models import Mode

FREQ_20M = 14_040_000
FREQ_40M = 7_030_000


def make_session():
    return build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        sent_exchange={"class": "1E", "section": "OR"},
        network=None,
        db_path=":memory:",
    )


async def _log(s, *, call, freq, mode, section, operator):
    s.engine.operator = operator
    await s.log_qso(
        call=call, freq_hz=freq, mode=mode, exchange={"class": "2A", "section": section}
    )


async def test_section_detail_groups_by_operator_with_bands_and_modes():
    s = make_session()
    await _log(s, call="K1ABC", freq=FREQ_20M, mode=Mode.CW, section="EPA", operator="ALICE")
    await _log(s, call="K1ABC", freq=FREQ_40M, mode=Mode.USB, section="EPA", operator="ALICE")
    await _log(s, call="W2XYZ", freq=FREQ_20M, mode=Mode.CW, section="EPA", operator="BOB")

    detail = s.section_detail("EPA")
    assert [r["operator"] for r in detail] == ["ALICE", "BOB"]  # sorted by operator

    alice = detail[0]
    assert alice["calls"] == ["K1ABC"]
    assert alice["bands"] == ["20m", "40m"]
    assert alice["modes"] == ["CW", "PHONE"]
    assert alice["count"] == 2

    bob = detail[1]
    assert bob["calls"] == ["W2XYZ"]
    assert bob["bands"] == ["20m"]
    assert bob["modes"] == ["CW"]
    assert bob["count"] == 1


async def test_section_detail_is_case_insensitive_and_empty_for_unworked():
    s = make_session()
    await _log(s, call="K1ABC", freq=FREQ_20M, mode=Mode.CW, section="EPA", operator="ALICE")
    assert s.section_detail("epa") == s.section_detail("EPA")
    assert s.section_detail("WY") == []


async def test_section_detail_dedupes_calls_and_modes():
    s = make_session()
    # Same op works the same call twice on different bands, same phone group.
    await _log(s, call="N0CALL", freq=FREQ_20M, mode=Mode.USB, section="CO", operator="ALICE")
    await _log(s, call="N0CALL", freq=FREQ_40M, mode=Mode.LSB, section="CO", operator="ALICE")
    detail = s.section_detail("CO")
    assert len(detail) == 1
    assert detail[0]["calls"] == ["N0CALL"]
    assert detail[0]["modes"] == ["PHONE"]  # USB + LSB collapse to one group
    assert detail[0]["bands"] == ["20m", "40m"]
    assert detail[0]["count"] == 2


def test_layout_covers_every_section_with_no_orphans():
    sections = set(ARRL_SECTIONS) | {"DX"}
    placed = set(SECTION_MAP_LAYOUT)
    assert sections - placed == set(), "sections missing a map cell"
    assert placed - sections == set(), "map cells with no matching section"


def test_layout_has_no_two_sections_on_one_cell():
    cells = list(SECTION_MAP_LAYOUT.values())
    assert len(cells) == len(set(cells)), "two sections share a map cell"
