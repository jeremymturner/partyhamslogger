"""ARRL Field Day rules: exchange, dupes, points, power multiplier, Cabrillo."""

from __future__ import annotations

import pytest
from factories import FREQ, make_qso

from partyhams.contest import get
from partyhams.contest.base import ContestConfig
from partyhams.contest.fieldday import PowerCategory, is_valid_class
from partyhams.contest.sections import ARRL_SECTIONS, is_valid_section
from partyhams.core.models import Mode


@pytest.fixture
def fd():
    return get("arrl-field-day")


def test_registered():
    assert get("arrl-field-day").name == "ARRL Field Day"


def test_class_and_section_validation():
    assert is_valid_class("3A")
    assert is_valid_class("1E")
    assert is_valid_class("10A")
    assert not is_valid_class("0A")
    assert not is_valid_class("3Z")
    assert not is_valid_class("AA")
    assert is_valid_section("OR")
    assert is_valid_section("epa")  # case-insensitive
    assert is_valid_section("DX")
    assert not is_valid_section("ZZ")


def test_section_list_matches_official_contest_list():
    # 85 ARRL/RAC contest sections + DX (contests.arrl.org, verified 2026-06-06).
    assert len(ARRL_SECTIONS) == 86
    # Sections that were missing/outdated before verification:
    for added in ("SNJ", "NNJ", "WNY", "GH", "NB", "NS", "PE"):
        assert added in ARRL_SECTIONS
    # The pre-2024 RAC abbreviations are no longer used by ARRL contests:
    for retired in ("GTA", "MAR"):
        assert retired not in ARRL_SECTIONS


def test_parse_exchange(fd):
    assert fd.parse_exchange("3a or") == {"class": "3A", "section": "OR"}
    with pytest.raises(ValueError):
        fd.parse_exchange("3A")  # missing section


def test_warc_bands_excluded(fd):
    allowed = fd.allowed_bands()
    assert "20m" in allowed
    assert "6m" in allowed
    for warc in ("30m", "17m", "12m", "60m"):
        assert warc not in allowed


def test_dupe_per_band_and_mode_group(fd):
    cw1 = make_qso("K1ABC", FREQ["20m"], Mode.CW)
    cw2 = make_qso("K1ABC", FREQ["20m"], Mode.CW)  # same slot -> dupe
    phone = make_qso("K1ABC", FREQ["20m"], Mode.USB)  # different mode group
    other_band = make_qso("K1ABC", FREQ["40m"], Mode.CW)  # different band

    assert fd.dupe_key(cw1) == fd.dupe_key(cw2)
    assert fd.dupe_key(cw1) != fd.dupe_key(phone)
    assert fd.dupe_key(cw1) != fd.dupe_key(other_band)


def test_qso_points_by_mode(fd):
    assert fd.qso_points(make_qso("K1A", mode=Mode.USB)) == 1  # phone
    assert fd.qso_points(make_qso("K1A", mode=Mode.CW)) == 2  # cw
    assert fd.qso_points(make_qso("K1A", mode=Mode.FT8)) == 2  # digital


def test_sections_tracked_as_mults(fd):
    # Sections are tracked (for the "work all sections" goal + new-mult highlight),
    # keyed by the "section" exchange field name.
    assert fd.multipliers(make_qso("K1A", exchange={"class": "2A", "section": "EPA"})) == {
        ("section", "EPA")
    }


def test_sections_do_not_multiply_score(fd):
    # Two QSOs in different sections, both CW (2 pts each), high power (x1).
    qsos = [
        make_qso("K1A", FREQ["20m"], Mode.CW, exchange={"class": "1A", "section": "EPA"}),
        make_qso("K2B", FREQ["40m"], Mode.CW, exchange={"class": "1A", "section": "OR"}),
    ]
    config = ContestConfig(extra={"power": PowerCategory.HIGH.key})
    summary = fd.score(qsos, config)
    assert summary.mult_count == 2  # two sections tracked
    assert summary.total == 4  # but score is just 4 points x1 — sections don't multiply


def test_score_with_power_multiplier_and_bonus(fd):
    qsos = [
        make_qso("K1A", FREQ["20m"], Mode.CW),  # 2
        make_qso("K1A", FREQ["20m"], Mode.CW),  # dupe -> ignored
        make_qso("K1A", FREQ["20m"], Mode.USB),  # 1 (phone, different slot)
        make_qso("K2B", FREQ["40m"], Mode.CW),  # 2
    ]
    config = ContestConfig(
        my_call="W7AAA",
        sent_exchange={"class": "3A", "section": "OR"},
        extra={"power": PowerCategory.LOW_150W.key, "bonus_points": 100},
    )
    summary = fd.score(qsos, config)
    assert summary.qso_count == 3
    assert summary.qso_points == 5
    assert summary.breakdown["power_multiplier"] == 2
    assert summary.total == 5 * 2 + 100  # 110


def test_qrp_multiplier_is_five(fd):
    qsos = [make_qso("K1A", FREQ["20m"], Mode.CW)]  # 2 points
    config = ContestConfig(extra={"power": PowerCategory.QRP_5W_ALT.key})
    assert fd.score(qsos, config).total == 2 * 5


def test_deleted_qsos_excluded_from_score(fd):
    qsos = [
        make_qso("K1A", FREQ["20m"], Mode.CW),
        make_qso("K2B", FREQ["20m"], Mode.CW, deleted=True),
    ]
    config = ContestConfig(extra={"power": PowerCategory.HIGH.key})
    summary = fd.score(qsos, config)
    assert summary.qso_count == 1
    assert summary.total == 2  # one CW QSO, x1, no bonus


def test_cabrillo_line(fd):
    q = make_qso("K2XYZ", FREQ["20m"], Mode.CW, exchange={"class": "2A", "section": "EPA"})
    config = ContestConfig(my_call="W7AAA", sent_exchange={"class": "3A", "section": "OR"})
    line = fd.cabrillo_qso_line(q, config)
    assert line.startswith("QSO:")
    assert "W7AAA" in line
    assert "K2XYZ" in line
    assert "3A" in line and "OR" in line  # sent
    assert "2A" in line and "EPA" in line  # received
    assert "CW" in line
