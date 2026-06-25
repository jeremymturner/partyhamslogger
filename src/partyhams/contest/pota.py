"""POTA (Parks on the Air) — modeled as a selectable "contest"/activity.

POTA is an activity, not a scored contest, but the logging core's
:class:`~partyhams.contest.base.ContestDefinition` framework is a clean fit for
it, so we model it as one:

* **Setup:** the activator's park reference (e.g. ``US-1234``) is a config field,
  optionally verified against the live POTA API (see :mod:`partyhams.contest.pota_api`).
* **Exchange:** signal report (RST) plus the contacted station's optional park
  reference for park-to-park (P2P) contacts. Their location/state isn't required.
* **Dupes:** POTA lets you re-work the same station on a different band, mode, or
  *day*, so the dupe key is ``(call, band, mode_group, UTC-date)``.
* **Scoring:** there is no contest score; ``score`` reports the plain QSO count.
* **Bands:** HF plus 6 m and 2 m (typical POTA activity).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from partyhams.contest.base import (
    ConfigField,
    ContestConfig,
    ContestDefinition,
    ExchangeField,
    ScoreSummary,
)
from partyhams.contest.registry import register
from partyhams.core.models import QSO, ModeGroup

# A POTA park reference: 1–4 alphanumerics, a hyphen, then 4–5 digits (US-1234).
_PARK_RE = re.compile(r"^[A-Z0-9]{1,4}-\d{4,5}$")

# POTA bands: the contest HF bands plus the WARC bands, plus 6 m and 2 m. POTA
# activity spans essentially all amateur HF allocations, unlike Field Day.
_ALLOWED_BANDS: frozenset[str] = frozenset(
    {
        "160m", "80m", "60m", "40m", "30m", "20m",
        "17m", "15m", "12m", "10m", "6m", "2m",
    }
)

# Cabrillo mode token by mode group (POTA has no real Cabrillo, but the export
# layer still asks for a QSO line).
_CABRILLO_MODE: dict[ModeGroup, str] = {
    ModeGroup.CW: "CW",
    ModeGroup.PHONE: "PH",
    ModeGroup.DIGITAL: "DG",
}


def is_valid_park(value: str) -> bool:
    """True for a well-formed POTA park reference like ``US-1234`` or ``K-0001``."""
    return bool(_PARK_RE.match(value.strip().upper()))


@register
class Pota(ContestDefinition):
    id = "pota"
    name = "Parks on the Air"
    cabrillo_name = "POTA"
    exchanges_rst = True  # POTA exchanges a signal report
    mult_label = "Parks"

    def config_fields(self) -> list[ConfigField]:
        return [
            ConfigField(
                "park",
                "My park (e.g. US-1234)",
                default="",
            ),
        ]

    def exchange_fields(self) -> list[ExchangeField]:
        # The contacted station's park is optional and only present for
        # park-to-park (P2P) contacts; everything else is RST, handled by the core.
        return [
            # Received-only (the other station's park on a P2P contact), never part
            # of our sent exchange — so it's excluded from the log-setup screen.
            ExchangeField(
                "park", "P2P", required=False, validator=is_valid_park, sent=False
            ),
        ]

    def allowed_bands(self) -> set[str]:
        return set(_ALLOWED_BANDS)

    def dupe_key(self, qso: QSO) -> tuple:
        # POTA lets you re-work the same station on another band, mode, or day, so
        # the dupe key includes the UTC date in addition to band + mode-group.
        return (
            qso.call.upper(),
            qso.band_label,
            qso.mode_group.value,
            qso.timestamp.date().isoformat(),
        )

    def qso_points(self, qso: QSO) -> int:
        # POTA isn't scored like a contest; every valid QSO counts as one.
        return 1

    def multipliers(self, qso: QSO) -> set[tuple[str, str]]:
        # Track worked parks (park-to-park) so a new one lights up the counter.
        park = qso.exchange_rcvd.get("park", "").upper()
        return {("park", park)} if park else set()

    def score(self, qsos: Iterable[QSO], config: ContestConfig) -> ScoreSummary:
        # Plain QSO count — POTA has no multiplied score. ``super().score`` already
        # de-dupes and sums qso_points (==1 each); we just report that as the total.
        base = super().score(qsos, config)
        base.total = base.qso_count
        base.breakdown = {"parks_worked": base.mult_count}
        return base

    def cabrillo_qso_line(self, qso: QSO, config: ContestConfig) -> str:
        freq_khz = qso.freq_hz // 1000
        mode = _CABRILLO_MODE[qso.mode_group]
        date = qso.timestamp.strftime("%Y-%m-%d")
        time = qso.timestamp.strftime("%H%M")
        my_call = config.my_call.upper()
        my_park = str(config.extra.get("park", "")).upper()
        their_park = qso.exchange_rcvd.get("park", "").upper()
        rst_sent = qso.rst_sent or "599"
        rst_rcvd = qso.rst_rcvd or "599"
        # QSO: freq mode date time mycall rst mypark call rst theirpark
        return (
            f"QSO: {freq_khz:>7} {mode:>2} {date} {time} "
            f"{my_call:<10} {rst_sent:>3} {my_park:<8} "
            f"{qso.call.upper():<10} {rst_rcvd:>3} {their_park:<8}"
        ).rstrip()
