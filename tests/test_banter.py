"""ContestBot banter engine: pure, deterministic message selection.

No Qt, no randomness, no wall-clock — every decision is a function of the inputs.
"""

from __future__ import annotations

from partyhams.app.banter import (
    BOT_NAME,
    HEATING_UP_DELTA,
    PUN_EVERY,
    PUNS,
    SLACKING_AGE_MIN,
    StationSnapshot,
    choose_message,
)


def snap(operator, rate_15=0, total=0, age=None):
    return StationSnapshot(
        operator=operator, rate_15=rate_15, total=total, last_qso_age_min=age
    )


def test_heating_up_names_the_op():
    prev = [snap("W7ABC", rate_15=2, total=2, age=1.0)]
    now = [snap("W7ABC", rate_15=2 + HEATING_UP_DELTA, total=8, age=0.5)]
    msg = choose_message(now, prev, counter=0)
    assert msg is not None
    assert msg.startswith(f"{BOT_NAME}: ")
    assert "W7ABC" in msg


def test_no_heating_up_below_threshold():
    prev = [snap("W7ABC", rate_15=2, total=2, age=1.0)]
    now = [snap("W7ABC", rate_15=2 + HEATING_UP_DELTA - 1, total=4, age=1.0)]
    # Counter chosen so the periodic pun does not fire either.
    assert choose_message(now, prev, counter=1) is None


def test_slacking_ribs_idle_station():
    now = [snap("K1XYZ", rate_15=0, total=12, age=SLACKING_AGE_MIN + 5)]
    msg = choose_message(now, previous=now, counter=3)
    assert msg is not None
    assert msg.startswith(f"{BOT_NAME}: ")
    assert "K1XYZ" in msg


def test_slacking_ignores_never_worked_station():
    # total below the floor => not ribbed (they simply haven't started).
    now = [snap("N0OB", rate_15=0, total=0, age=None)]
    assert choose_message(now, previous=now, counter=1) is None


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


def test_longest_idle_wins_when_several_slack():
    now = [
        snap("AAA", total=3, age=SLACKING_AGE_MIN + 2),
        snap("BBB", total=3, age=SLACKING_AGE_MIN + 40),
    ]
    msg = choose_message(now, previous=now, counter=2)
    assert msg is not None and "BBB" in msg


def test_periodic_pun_when_nothing_noteworthy():
    now = [snap("W7ABC", rate_15=1, total=5, age=1.0)]
    msg = choose_message(now, previous=now, counter=PUN_EVERY)  # PUN_EVERY % PUN_EVERY == 0
    assert msg is not None
    assert any(msg.endswith(p) for p in PUNS)
    assert msg.startswith(f"{BOT_NAME}: ")


def test_no_pun_off_cadence():
    now = [snap("W7ABC", rate_15=1, total=5, age=1.0)]
    assert choose_message(now, previous=now, counter=PUN_EVERY + 1) is None


def test_pun_selection_is_deterministic_by_counter():
    now = [snap("W7ABC", rate_15=1, total=5, age=1.0)]
    a = choose_message(now, previous=now, counter=0)
    b = choose_message(now, previous=now, counter=0)
    assert a == b == f"{BOT_NAME}: {PUNS[0]}"
    # A different (still on-cadence) counter rotates to a different pun.
    other = choose_message(now, previous=now, counter=PUN_EVERY * 3)
    assert other == f"{BOT_NAME}: {PUNS[(PUN_EVERY * 3) % len(PUNS)]}"


def test_none_when_nothing_noteworthy_and_off_cadence():
    prev = [snap("W7ABC", rate_15=4, total=10, age=2.0)]
    now = [snap("W7ABC", rate_15=4, total=10, age=2.0)]
    assert choose_message(now, prev, counter=1) is None


def test_empty_roster_never_crashes():
    assert choose_message([], None, counter=0) is None
    assert choose_message([], [], counter=PUN_EVERY) is None
    assert choose_message([snap("")], None, counter=PUN_EVERY) is None


def test_missing_previous_treats_all_as_new():
    # With no previous snapshot, nobody can be "heating up"; a fresh idle station
    # past the threshold is still eligible for ribbing.
    now = [snap("K1XYZ", rate_15=0, total=4, age=SLACKING_AGE_MIN + 1)]
    msg = choose_message(now, previous=None, counter=3)
    assert msg is not None and "K1XYZ" in msg
