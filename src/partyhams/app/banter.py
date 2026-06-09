"""ContestBot: a pure, deterministic "banter" engine for the network chat.

Given a snapshot of per-station activity (plus the previous snapshot), it decides
whether to post a fun, ham-radio-flavoured automated message — cheering a station
whose rate is climbing, gently ribbing one that's gone quiet, or just dropping the
occasional terrible pun. It is intentionally Qt-free, randomness-free, and
wall-clock-free: every decision is a pure function of its inputs (the caller passes
a monotonically increasing ``counter`` to drive deterministic selection), so the
whole thing is trivially unit-testable.

The UI layer (main window) is responsible for building the snapshots on a timer,
throttling, and posting whatever string this returns to the chat.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Name we sign automated messages with, so everyone can tell it's the bot.
BOT_NAME = "ContestBot"

#: A 15-minute rate must climb by at least this many QSOs to count as "heating up".
HEATING_UP_DELTA = 3

#: No new QSO for at least this many minutes => a station is "slacking".
SLACKING_AGE_MIN = 20.0

#: A station must have logged something already before we rib it for going quiet
#: (so we don't pick on someone who simply hasn't started yet).
SLACKING_MIN_TOTAL = 1

#: Drop a generic pun every Nth check when nothing else is noteworthy.
PUN_EVERY = 5


@dataclass(frozen=True)
class StationSnapshot:
    """A plain, immutable view of one station's activity at a moment in time."""

    operator: str
    rate_15: int = 0
    total: int = 0
    last_qso_age_min: float | None = None  # None => never worked anyone


# Cheers for a station whose 15-minute rate just jumped. ``{op}`` => operator.
HEATING_UP = (
    "{op} is really making waves — that rate is positively frequency-ent!",
    "Whoa, {op} is heating up the bands faster than a hot tube amp. CQ indeed!",
    "{op} is on a roll — someone check their dits, they're running away!",
    "Look at {op} go! That pile-up is no QRP operation. 73 to the competition.",
    "{op} just kicked the rate into overdrive. Resistance is fertile!",
    "Ohm my! {op} is conducting a masterclass in working 'em fast.",
    "{op} is cooking with RF now — watt a performance!",
    "Somebody hand {op} a QSL card factory, they can't stop running 'em.",
    "{op} is climbing the rate ladder — clearly nobody told them the bands are 'dead'.",
    "{op} is putting out so much signal the SWR meter filed a complaint. Brilliant!",
)

# Gentle ribbing for a station that's gone quiet. ``{op}`` => operator.
SLACKING = (
    "Earth to {op}… your antenna asleep? No QSOs in a while — don't get it in a twist!",
    "{op}, the bands miss you. Did you wander off for a coffee and a long ragchew?",
    "Hello {op}? Long path? Your rate flatlined — even the band noise is bored.",
    "{op} has gone QRT-ish. Wouldn't you know it — the bands go dead the second you nap.",
    "Psst, {op}: CQ is a verb. Twist that dial and make some contacts!",
    "{op}, your logbook is gathering QRM dust. Time to key up and elmer the airwaves!",
    "We've lost {op} to the great void of zero QSOs. Did the feedline eat you?",
    "{op}, if you wanted a rest you should've picked a slower hobby. Get on the air!",
    "Anyone seen {op}? Last heard chasing a phantom 6m opening. Come back, the run is hot!",
    "{op}, your rate dropped to QRP-zero. Crank the wick and work somebody!",
)

# Generic puns dropped occasionally when nothing else is going on.
PUNS = (
    "Two antennas got married. The wedding was meh, but the reception was excellent. 73!",
    "I'd tell you a UDP joke, but you might not get it. So here's a ham one instead.",
    "Why did the contester bring a ladder? To reach the high bands, of course!",
    "Remember: a balun a day keeps the common-mode away. Stay grounded out there.",
    "QSL? More like QS-yes! Keep those cards coming, folks.",
    "Don't get your antenna in a twist — the gain will come back around.",
    "Some say the bands are dead. We say: just resonant at a different frequency!",
    "Be an elmer today: work a newbie, share a 73, and pass the good vibes down the line.",
    "Frequency-ently asked question: are we having fun yet? The answer is affirmative.",
    "Watt's up, everyone? Just here to ohm-it-up and keep the current conversation going.",
    "My favourite mode? Whichever one's working. Resistance to fun is futile!",
    "Keep calm and CQ on. The pile-ups won't call themselves.",
    "Propagation tip: a positive attitude has excellent gain in every direction. 73!",
    "If at first you don't succeed, QSY and try again. The bands are forgiving.",
    "Stay tuned, stay matched, and may your SWR be ever in your favour.",
)


def _pick(pool: tuple[str, ...], counter: int) -> str:
    """Deterministically pick one item from ``pool`` using ``counter``."""
    return pool[counter % len(pool)]


def choose_message(
    snapshot: list[StationSnapshot],
    previous: list[StationSnapshot] | None,
    counter: int,
) -> str | None:
    """Decide whether ContestBot should say something, and return it (or ``None``).

    Pure and deterministic. Priority: cheer a station heating up, then rib a quiet
    one, then (every :data:`PUN_EVERY` checks) drop a generic pun. ``counter`` is a
    caller-supplied, monotonically increasing integer used both as the periodic
    trigger and to rotate deterministically through each message pool.

    The returned string is already prefixed with the bot name, e.g.
    ``"ContestBot: …"`` so the existing chat format is untouched.
    """
    prev_by_op = {s.operator: s for s in (previous or [])}

    # (a) Heating up — biggest 15-minute rate jump since last check wins.
    best_op, best_delta = None, 0
    for s in snapshot:
        if not s.operator:
            continue
        before = prev_by_op.get(s.operator)
        if before is None:
            continue
        delta = s.rate_15 - before.rate_15
        if delta >= HEATING_UP_DELTA and delta > best_delta:
            best_op, best_delta = s.operator, delta
    if best_op is not None:
        return _say(_pick(HEATING_UP, counter).format(op=best_op))

    # (b) Slacking — the station idle the longest (past the threshold) wins.
    idle_op, idle_age = None, SLACKING_AGE_MIN
    for s in snapshot:
        if not s.operator or s.total < SLACKING_MIN_TOTAL:
            continue
        age = s.last_qso_age_min
        if age is not None and age >= idle_age:
            idle_op, idle_age = s.operator, age
    if idle_op is not None:
        return _say(_pick(SLACKING, counter).format(op=idle_op))

    # (c) Occasional generic pun — only every PUN_EVERY checks, to stay un-spammy,
    # and only when at least one real (named) station is around to enjoy it.
    if counter % PUN_EVERY == 0 and any(s.operator for s in snapshot):
        return _say(_pick(PUNS, counter))

    return None


def _say(text: str) -> str:
    """Stamp a message with the bot name so it reads as automated in chat."""
    return f"{BOT_NAME}: {text}"
