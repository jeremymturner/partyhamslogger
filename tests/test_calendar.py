"""Pure tests for the contest calendar (no network, no wall clock)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from partyhams.contest.calendar import (
    CalendarEvent,
    events_for_year,
    fetch_calendar,
    nearest_contest_id,
    upcoming_events,
)

# A registration predicate matching only ids we actually implement, so these
# tests don't depend on which other contests exist in the registry.
_REGISTERED = {"arrl-field-day"}.__contains__


def test_field_day_is_fourth_saturday_of_june() -> None:
    # 2026: June Saturdays are 6, 13, 20, 27 -> 4th = the 27th.
    events = {e.name: e for e in events_for_year(2026)}
    fd = events["ARRL Field Day"]
    assert fd.contest_id == "arrl-field-day"
    assert fd.start == date(2026, 6, 27)
    assert fd.end == date(2026, 6, 28)


def test_nearest_contest_id_late_june_is_field_day() -> None:
    today = date(2026, 6, 26)  # day before Field Day weekend
    assert nearest_contest_id(today, is_registered=_REGISTERED) == "arrl-field-day"


def test_nearest_contest_id_in_progress_wins() -> None:
    # Mid Field Day weekend: distance 0, still the answer.
    today = date(2026, 6, 28)
    assert nearest_contest_id(today, is_registered=_REGISTERED) == "arrl-field-day"


def test_nearest_contest_id_accepts_aware_datetime() -> None:
    today = datetime(2026, 6, 26, 18, 0, tzinfo=UTC)
    assert nearest_contest_id(today, is_registered=_REGISTERED) == "arrl-field-day"


def test_nearest_contest_id_none_when_nothing_registered() -> None:
    assert nearest_contest_id(date(2026, 6, 26), is_registered=lambda _id: False) is None


def test_upcoming_events_sorted_by_proximity() -> None:
    today = date(2026, 6, 26)
    ordered = upcoming_events(today)
    # Field Day (next day) must come before CQ WW (October).
    names = [e.name for e in ordered]
    assert names.index("ARRL Field Day") < names.index("CQ WW DX")
    # Distances are non-decreasing.
    def dist(e: CalendarEvent) -> int:
        if e.start <= today <= e.end:
            return 0
        return (e.start - today).days if today < e.start else (today - e.end).days

    dists = [dist(e) for e in ordered]
    assert dists == sorted(dists)


def test_upcoming_events_uses_neighbouring_years() -> None:
    # Early January should see last year's CQ WW (late Oct) as a recent event
    # and this year's Winter Field Day as upcoming.
    today = date(2026, 1, 2)
    names = {e.name for e in upcoming_events(today)}
    assert "Winter Field Day" in names
    assert "CQ WW DX" in names


def test_fetch_calendar_uses_injected_source() -> None:
    sentinel = [CalendarEvent("Live", "x", date(2026, 1, 1), date(2026, 1, 2))]
    assert fetch_calendar(fetch=lambda: sentinel, today=date(2026, 1, 1)) == sentinel


def test_fetch_calendar_falls_back_when_fetch_fails() -> None:
    def boom() -> list[CalendarEvent]:
        raise OSError("offline")

    result = fetch_calendar(fetch=boom, today=date(2026, 6, 1))
    assert result == events_for_year(2026)


def test_fetch_calendar_falls_back_on_empty() -> None:
    result = fetch_calendar(fetch=lambda: [], today=date(2026, 6, 1))
    assert result == events_for_year(2026)


def test_fetch_calendar_default_is_bundled() -> None:
    result = fetch_calendar(today=date(2025, 3, 3))
    assert result == events_for_year(2025)


@pytest.mark.parametrize("year", [2024, 2025, 2026, 2027])
def test_field_day_always_in_june(year: int) -> None:
    fd = {e.name: e for e in events_for_year(year)}["ARRL Field Day"]
    assert fd.start.month == 6 and fd.start.weekday() == 5
