"""Field Day bonus catalog, itemised scoring, and the summary-sheet writer."""

from __future__ import annotations

from partyhams.app.session import build_session
from partyhams.contest.fd_bonus import (
    BONUS_SELECTIONS_KEY,
    FD_BONUS_BY_KEY,
    bonus_breakdown,
    bonus_total,
)
from partyhams.core.models import Mode

FREQ_20M = 14_040_000
FREQ_40M = 7_040_000


def test_bonus_total_flat_and_counted():
    selections = {
        "media_publicity": True,  # flat 100
        "public_location": False,  # not claimed
        "emergency_power": 3,  # 3 × 100 = 300
        "nts_messages": 7,  # 7 × 10 = 70
        "web_submission": True,  # flat 50
    }
    assert bonus_total(selections) == 100 + 300 + 70 + 50


def test_bonus_counted_items_are_capped():
    # Emergency power caps at 2000 (20 transmitters); NTS messages cap at 100.
    assert bonus_total({"emergency_power": 50}) == 2000
    assert bonus_total({"nts_messages": 99}) == 100
    assert FD_BONUS_BY_KEY["nts_messages"].value(99) == 100


def test_bonus_breakdown_lists_only_claimed():
    selections = {"media_publicity": True, "emergency_power": 2, "satellite_qso": False}
    claimed = {item.key: pts for item, pts in bonus_breakdown(selections)}
    assert claimed == {"media_publicity": 100, "emergency_power": 200}


async def make_session(extra: dict | None = None):
    s = build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        sent_exchange={"class": "2A", "section": "OR"},
        power="low_150w",  # ×2
        network=None,
        extra=extra,
    )
    # 2 CW (2 pts each) + 1 phone (1 pt) = 5 QSO points.
    await s.log_qso(
        call="K1ABC", freq_hz=FREQ_20M, mode=Mode.CW, exchange={"class": "1A", "section": "EPA"}
    )
    await s.log_qso(
        call="W2XYZ", freq_hz=FREQ_40M, mode=Mode.CW, exchange={"class": "3A", "section": "STX"}
    )
    await s.log_qso(
        call="N3QRP", freq_hz=FREQ_20M, mode=Mode.USB, exchange={"class": "1E", "section": "WPA"}
    )
    return s


async def test_score_reads_itemised_bonus():
    selections = {"media_publicity": True, "emergency_power": 2}  # 100 + 200 = 300
    s = await make_session({BONUS_SELECTIONS_KEY: selections})
    score = s.score()
    assert score.qso_points == 5
    assert score.bonus_points == 300
    # (5 QSO points × 2 power) + 300 bonus = 310.
    assert score.total == 5 * 2 + 300


async def test_score_falls_back_to_aggregate_bonus_points():
    # A log without itemised selections still honours a plain bonus_points value.
    s = await make_session({"bonus_points": 150})
    assert s.score().bonus_points == 150
    assert s.fd_summary_info_entered() is False


async def test_summary_sheet_contents():
    selections = {"media_publicity": True, "emergency_power": 2, "web_submission": True}
    extra = {
        BONUS_SELECTIONS_KEY: selections,
        "participants": 12,
        "club_name": "Cascade ARC",
        "gota_call": "W7GOTA",
    }
    s = await make_session(extra)
    sheet = s.export_fieldday_summary()

    assert "ARRL FIELD DAY — SUMMARY SHEET" in sheet
    assert "W7ABC" in sheet
    assert "2A" in sheet  # class
    assert "OR" in sheet  # section
    assert "Low (≤150 W)" in sheet and "×2" in sheet
    assert "Cascade ARC" in sheet
    assert "W7GOTA" in sheet
    assert "12" in sheet  # participants
    # Claimed QSO totals: 2 CW/Data + 1 Phone.
    assert "CW + Data QSOs" in sheet
    assert "Phone QSOs" in sheet
    # Bonus itemisation + total score (5×2 + 350 = 360).
    assert "Media publicity" in sheet
    assert "100% emergency power" in sheet
    assert "TOTAL SCORE" in sheet
    assert "360" in sheet
    # The Cabrillo dupe-sheet note is present.
    assert "Cabrillo" in sheet


async def test_summary_band_mode_table_counts():
    s = await make_session({BONUS_SELECTIONS_KEY: {}})
    sheet = s.export_fieldday_summary()
    # Two CW bands worked (20m, 40m) and one phone band (20m).
    assert "20m" in sheet
    assert "40m" in sheet
    # Grand total row reflects all three QSOs.
    assert "Total" in sheet
