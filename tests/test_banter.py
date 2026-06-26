"""ContestBot banter engine: pure, deterministic message selection.

No Qt, no randomness, no wall-clock — every decision is a function of the inputs.
"""

from __future__ import annotations

from partyhams.app.banter import (
    BOT_NAME,
    HEATING_UP_DELTA,
    PUNS,
    SLACKING_AGE_MIN,
    WWV_MINUTE,
    WWV_POWER_HOUR,
    StationSnapshot,
    choose_message,
)


def snap(operator, rate_15=0, total=0, age=None):
    return StationSnapshot(
        operator=operator, rate_15=rate_15, total=total, last_qso_age_min=age
    )


def test_one_hundred_puns():
    # The user asked for ~100 different funny things to draw from.
    assert len(PUNS) == 100
    assert len(set(PUNS)) == 100  # all distinct


def test_heating_up_names_the_op():
    prev = [snap("W7ABC", rate_15=2, total=2, age=1.0)]
    now = [snap("W7ABC", rate_15=2 + HEATING_UP_DELTA, total=8, age=0.5)]
    msg = choose_message(now, prev, counter=0)
    assert msg is not None
    assert msg.startswith(f"{BOT_NAME}: ")
    assert "W7ABC" in msg


def test_heating_up_wins_over_slacking():
    prev = [snap("W7ABC", rate_15=1, total=1, age=0.0), snap("K1XYZ", total=9, age=99.0)]
    now = [
        snap("W7ABC", rate_15=1 + HEATING_UP_DELTA, total=7, age=0.1),
        snap("K1XYZ", total=9, age=99.0),
    ]
    msg = choose_message(now, prev, counter=0)
    assert msg is not None and "W7ABC" in msg


def test_biggest_jump_wins_when_several_heat_up():
    prev = [snap("AAA", rate_15=0, total=1, age=0.0), snap("BBB", rate_15=0, total=1, age=0.0)]
    now = [
        snap("AAA", rate_15=HEATING_UP_DELTA, total=5, age=0.0),
        snap("BBB", rate_15=HEATING_UP_DELTA + 4, total=9, age=0.0),
    ]
    msg = choose_message(now, prev, counter=0)
    assert msg is not None and "BBB" in msg


def test_slacking_ribs_idle_station():
    now = [snap("K1XYZ", rate_15=0, total=12, age=SLACKING_AGE_MIN + 5)]
    msg = choose_message(now, previous=now, counter=3)
    assert msg is not None and "K1XYZ" in msg


def test_slacking_ignores_never_worked_station_falls_back_to_pun():
    # A station that hasn't started isn't ribbed; with nothing else noteworthy the
    # bot falls back to a generic pun (the un-spammy throttle lives in the UI).
    now = [snap("N0OB", rate_15=0, total=0, age=None)]
    msg = choose_message(now, previous=now, counter=1)
    assert msg == f"{BOT_NAME}: {PUNS[1 % len(PUNS)]}"


def test_longest_idle_wins_when_several_slack():
    now = [
        snap("AAA", total=3, age=SLACKING_AGE_MIN + 2),
        snap("BBB", total=3, age=SLACKING_AGE_MIN + 40),
    ]
    msg = choose_message(now, previous=now, counter=2)
    assert msg is not None and "BBB" in msg


def test_pun_is_the_fallback():
    now = [snap("W7ABC", rate_15=1, total=5, age=1.0)]
    msg = choose_message(now, previous=now, counter=0)
    assert msg == f"{BOT_NAME}: {PUNS[0]}"


def test_pun_selection_is_deterministic_by_counter():
    now = [snap("W7ABC", rate_15=1, total=5, age=1.0)]
    a = choose_message(now, previous=now, counter=7)
    b = choose_message(now, previous=now, counter=7)
    assert a == b == f"{BOT_NAME}: {PUNS[7]}"
    other = choose_message(now, previous=now, counter=42)
    assert other == f"{BOT_NAME}: {PUNS[42 % len(PUNS)]}"


def test_empty_or_anonymous_roster_is_silent():
    assert choose_message([], None, counter=0) is None
    assert choose_message([], [], counter=5) is None
    assert choose_message([snap("")], None, counter=5) is None


def test_missing_previous_treats_all_as_new():
    # No previous => nobody is "heating up"; a fresh idle station past the threshold
    # is still ribbed.
    now = [snap("K1XYZ", rate_15=0, total=4, age=SLACKING_AGE_MIN + 1)]
    msg = choose_message(now, previous=None, counter=3)
    assert msg is not None and "K1XYZ" in msg


# --- Field Day WWV "power hour" -------------------------------------------- #
def test_wwv_power_hour_nudges_a_station_at_fifty_past():
    now = [snap("W7ABC", rate_15=5, total=20, age=0.5)]
    msg = choose_message(now, now, counter=0, minute_of_hour=WWV_MINUTE, field_day=True)
    assert msg is not None
    assert "W7ABC" in msg
    assert msg == f"{BOT_NAME}: {WWV_POWER_HOUR[0].format(op='W7ABC')}"


def test_wwv_only_in_field_day():
    now = [snap("W7ABC", rate_15=5, total=20, age=0.5)]
    # Same minute, but not Field Day -> falls back to a pun, no WWV nudge.
    msg = choose_message(now, now, counter=0, minute_of_hour=WWV_MINUTE, field_day=False)
    assert "power hour" not in msg


def test_wwv_only_at_fifty_past():
    now = [snap("W7ABC", rate_15=5, total=20, age=0.5)]
    msg = choose_message(now, now, counter=0, minute_of_hour=10, field_day=True)
    assert "power hour" not in (msg or "")


def test_wwv_picks_among_stations_by_counter():
    roster = [snap("AAA", total=5, age=1.0), snap("BBB", total=5, age=1.0)]
    a = choose_message(roster, roster, counter=0, minute_of_hour=WWV_MINUTE, field_day=True)
    b = choose_message(roster, roster, counter=1, minute_of_hour=WWV_MINUTE, field_day=True)
    assert "AAA" in a and "BBB" in b  # counter rotates which station is asked
