"""Contest calendar: when well-known events happen, mapped to local contest ids.

This drives the *default* contest selection in the New Log dialog: when an
operator starts a fresh log we guess the event nearest to today.

The bundled list (:data:`RULES`) is the source of truth and is what the tests
exercise. It is a small, static set of recurring rules computed for any given
year — deterministic and pure (every public function takes ``today`` as a
parameter and never reads the wall clock itself).

An optional :func:`fetch_calendar` can pull a live public calendar (the WA7BNM
contest calendar publishes JSON), but the exact endpoint/shape cannot be
verified in this environment, so the function is injectable and falls back to
the bundled list on any failure or when offline. It adds no dependencies
(stdlib ``urllib`` only).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class CalendarEvent:
    """A concrete occurrence of an event in a given year.

    ``contest_id`` is the matching local contest id (may be unregistered, e.g.
    an event we list for context but don't yet implement). ``start``/``end`` are
    dates (inclusive) for the event window.
    """

    name: str
    contest_id: str
    start: date
    end: date
    always_on: bool = False  # POTA et al.: never shadow a dated, in-progress contest

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class _Rule:
    """A recurring rule that can compute its :class:`CalendarEvent` for a year.

    ``always_on`` events (e.g. POTA) match every day and are represented as a
    full-year window so they never "win" proximity against a real contest unless
    nothing else is near.
    """

    name: str
    contest_id: str
    month: int | None  # None => always-on (full year)
    weekday: int = 5  # 0=Mon .. 6=Sun; default Saturday
    nth: int = 1  # nth occurrence of weekday in the month (1-based)
    duration_days: int = 1  # length of the window including the start day
    always_on: bool = False

    def event_for_year(self, year: int) -> CalendarEvent:
        if self.always_on or self.month is None:
            return CalendarEvent(
                self.name, self.contest_id, date(year, 1, 1), date(year, 12, 31),
                always_on=True,
            )
        start = _nth_weekday(year, self.month, self.weekday, self.nth)
        end = start + timedelta(days=self.duration_days - 1)
        return CalendarEvent(self.name, self.contest_id, start, end)


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    """Date of the ``nth`` (1-based) ``weekday`` in ``month``.

    ``nth`` may be negative to count from the end (-1 = last). "4th full
    weekend" rules use the 4th Saturday, which this computes directly.
    """
    if nth > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + (nth - 1) * 7)
    # Count from the end of the month.
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset + (-nth - 1) * 7)


# Bundled, static set of recurring events. Dates are computed per year.
# Sources are common knowledge of contest scheduling; treat as approximate.
RULES: tuple[_Rule, ...] = (
    # Winter Field Day: last full weekend of January.
    _Rule("Winter Field Day", "winter-field-day", 1, weekday=5, nth=-1,
          duration_days=2),
    # ARRL DX (CW): third weekend of February.
    _Rule("ARRL International DX", "arrl-dx", 2, weekday=5, nth=3,
          duration_days=2),
    # ARRL Field Day: 4th full weekend of June (4th Saturday).
    _Rule("ARRL Field Day", "arrl-field-day", 6, weekday=5, nth=4,
          duration_days=2),
    # CQ WW DX (SSB): last full weekend of October.
    _Rule("CQ WW DX", "cq-ww", 10, weekday=5, nth=-1, duration_days=2),
    # POTA: an always-on activity rather than a dated contest.
    _Rule("Parks on the Air (POTA)", "pota", None, always_on=True),
)


def events_for_year(year: int) -> list[CalendarEvent]:
    """All bundled events realised for ``year`` (insertion order of RULES)."""
    return [r.event_for_year(year) for r in RULES]


def _candidate_events(today: date) -> list[CalendarEvent]:
    """Events to consider: this year plus the prior/next year's occurrences.

    Including the neighbouring years means a date in early January correctly
    sees last December's CQ WW and this year's Winter Field Day.
    """
    out: list[CalendarEvent] = []
    for year in (today.year - 1, today.year, today.year + 1):
        out.extend(events_for_year(year))
    return out


def _distance(event: CalendarEvent, today: date) -> int:
    """Days from ``today`` to the nearest edge of the event window (0 if inside)."""
    if event.contains(today):
        return 0
    if today < event.start:
        return (event.start - today).days
    return (today - event.end).days


def _as_date(today: date | datetime) -> date:
    return today.date() if isinstance(today, datetime) else today


def upcoming_events(today: date | datetime) -> list[CalendarEvent]:
    """Bundled events sorted by proximity to ``today`` (closest first).

    "Closest" measures distance to the event window's nearest edge; an event in
    progress (distance 0) sorts first. Ties break by start date then name for
    determinism. Always-on events (full-year windows) always have distance 0, so
    they trail dated, in-progress events via the start-date tie-break.
    """
    day = _as_date(today)
    events = _candidate_events(day)
    # At equal distance, dated events beat always-on ones (POTA shouldn't shadow
    # an in-progress contest); then nearer start, then name, for determinism.
    events.sort(key=lambda e: (_distance(e, day), e.always_on, e.start, e.name))
    return events


def nearest_contest_id(
    today: date | datetime, is_registered: Callable[[str], bool] | None = None
) -> str | None:
    """Contest id of the event nearest ``today``, restricted to registered ids.

    Prefers an event currently in progress, else the nearest upcoming/recent.
    Returns ``None`` if no nearby event maps to a registered contest. By default
    registration is checked against the live contest registry; tests inject
    ``is_registered`` to stay independent of which contests exist.
    """
    if is_registered is None:
        from partyhams.contest import available

        registered = {cid for cid, _ in available()}
        is_registered = registered.__contains__
    for event in upcoming_events(today):
        if is_registered(event.contest_id):
            return event.contest_id
    return None


def fetch_calendar(
    fetch: Callable[[], list[CalendarEvent]] | None = None,
    today: date | datetime | None = None,
) -> list[CalendarEvent]:
    """Return calendar events, optionally from a live source, else bundled.

    ``fetch`` is an injectable callable returning a list of
    :class:`CalendarEvent`; if it is ``None`` or raises (offline, bad data, …)
    we fall back to the bundled list for the relevant year. The live WA7BNM
    endpoint/format cannot be verified here, so production callers should treat
    the bundled list as authoritative.
    """
    if fetch is not None:
        try:
            result = fetch()
            if result:
                return list(result)
        except Exception:
            pass
    year = _as_date(today).year if today is not None else date.today().year
    return events_for_year(year)
