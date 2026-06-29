"""ARRL Field Day summary sheet — the human-readable report an operator reads
off into the Field Day web app (``field-day.arrl.org``).

ARRL Field Day is *not* submitted as a single machine-readable file: the operator
fills in a web form (call, class, section, power category, participants, claimed
QSO totals, itemised bonus points) and may upload a Cabrillo log as the dupe
sheet. This writer renders exactly those web-form numbers as a plain-text sheet,
plus a band/mode breakdown and the itemised bonus list, so transcribing the entry
is a copy job. It is Qt-free and unit-tested.

All the numbers come from the already-computed :class:`ScoreSummary` (so the sheet
can never disagree with the live score window) and the station ``config``.
"""

from __future__ import annotations

from collections.abc import Iterable

from partyhams import __version__
from partyhams.contest.base import ContestConfig, ContestDefinition, ScoreSummary
from partyhams.contest.fd_bonus import BONUS_SELECTIONS_KEY, bonus_breakdown
from partyhams.core.models import QSO, ModeGroup, utcnow

# Display column order for the band/mode table and the points each mode is worth.
_MODE_COLS: tuple[tuple[ModeGroup, str], ...] = (
    (ModeGroup.CW, "CW"),
    (ModeGroup.DIGITAL, "Data"),
    (ModeGroup.PHONE, "Phone"),
)
_MODE_POINTS = {ModeGroup.CW: 2, ModeGroup.DIGITAL: 2, ModeGroup.PHONE: 1}

# Bands in conventional high-to-low order for the table rows.
_BAND_ORDER = ["160m", "80m", "40m", "20m", "15m", "10m", "6m", "2m", "1.25m", "70cm"]


def _power_label(score: ScoreSummary) -> str:
    mult = score.breakdown.get("power_multiplier", 1)
    category = str(score.breakdown.get("power_category", ""))
    pretty = {
        "qrp_5w_alt": "QRP (≤5 W, alternate power)",
        "low_150w": "Low (≤150 W)",
        "high": "High (>150 W)",
    }.get(category, category or "Unknown")
    return f"{pretty}  (×{mult})"


def _band_mode_table(by_band_mode: dict[str, int]) -> tuple[list[str], dict[ModeGroup, int]]:
    """Render the band×mode QSO table, returning its lines and per-mode totals.

    ``by_band_mode`` is the dupe-free ``{"20m CW": 42, ...}`` map from the score
    breakdown (mode token = ``ModeGroup.value``).
    """
    # counts[band][mode_group] = qso count
    counts: dict[str, dict[ModeGroup, int]] = {}
    for slot, n in by_band_mode.items():
        band, _, mode_tok = slot.rpartition(" ")
        try:
            group = ModeGroup(mode_tok)
        except ValueError:
            continue
        band_row = counts.setdefault(band, {})
        band_row[group] = band_row.get(group, 0) + n

    # Stable band ordering: known bands first (high→low), then any stragglers.
    bands = [b for b in _BAND_ORDER if b in counts]
    bands += sorted(b for b in counts if b not in _BAND_ORDER)

    header = f"{'Band':<8}" + "".join(f"{label:>8}" for _, label in _MODE_COLS) + f"{'Total':>8}"
    lines = [header, "-" * len(header)]
    mode_totals: dict[ModeGroup, int] = {g: 0 for g, _ in _MODE_COLS}
    for band in bands:
        row = f"{band:<8}"
        band_total = 0
        for group, _ in _MODE_COLS:
            n = counts[band].get(group, 0)
            mode_totals[group] += n
            band_total += n
            row += f"{n:>8}"
        row += f"{band_total:>8}"
        lines.append(row)
    lines.append("-" * len(header))
    grand = sum(mode_totals.values())
    total_row = f"{'Total':<8}" + "".join(f"{mode_totals[g]:>8}" for g, _ in _MODE_COLS)
    total_row += f"{grand:>8}"
    lines.append(total_row)
    return lines, mode_totals


def write_fieldday_summary(
    qsos: Iterable[QSO],
    config: ContestConfig,
    contest: ContestDefinition,
    score: ScoreSummary,
    operators: Iterable[str] | None = None,
) -> str:
    """Render the Field Day summary sheet as a plain-text string."""
    extra = config.extra
    sent = config.sent_exchange
    op_list = sorted({o.upper() for o in (operators or []) if o})

    by_band_mode = score.breakdown.get("by_band_mode", {})  # type: ignore[assignment]
    table_lines, mode_totals = _band_mode_table(dict(by_band_mode))

    cw_data_q = mode_totals[ModeGroup.CW] + mode_totals[ModeGroup.DIGITAL]
    phone_q = mode_totals[ModeGroup.PHONE]
    mult = int(score.breakdown.get("power_multiplier", 1))

    out: list[str] = []
    w = out.append
    bar = "=" * 60

    w(bar)
    w("ARRL FIELD DAY — SUMMARY SHEET".center(60))
    w(f"PartyHams Logger {__version__}".center(60))
    w(bar)
    w(f"Generated: {utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    w("Enter these figures into the Field Day web app:")
    w("    https://field-day.arrl.org/fdentry.php")
    w("")

    # --- Entry identification (web-form fields) ---
    w("ENTRY")
    w(f"  Call sign .......... {config.my_call.upper() or '(not set)'}")
    w(f"  Class .............. {sent.get('class', '') or '(not set)'}")
    w(f"  ARRL/RAC Section ... {sent.get('section', '') or '(not set)'}")
    w(f"  Power category ..... {_power_label(score)}")
    club = str(extra.get("club_name", "") or "")
    if club:
        w(f"  Club / group ....... {club}")
    gota = str(extra.get("gota_call", "") or "").upper()
    if gota:
        w(f"  GOTA station ....... {gota}")
    participants = int(extra.get("participants", 0) or 0)
    w(f"  Participants ....... {participants if participants else '(not entered)'}")
    if op_list:
        w(f"  Operators .......... {', '.join(op_list)}")
    w("")

    # --- QSOs by band & mode ---
    w("QSOs BY BAND & MODE  (duplicates removed)")
    for line in table_lines:
        w("  " + line)
    w("")
    w("CLAIMED QSO TOTALS  (for the web form)")
    w(f"  CW + Data QSOs ..... {cw_data_q:>6}   (2 points each)")
    w(f"  Phone QSOs ......... {phone_q:>6}   (1 point each)")
    w(f"  Total QSOs ......... {score.qso_count:>6}")
    w("")

    # --- Score ---
    w("CLAIMED SCORE")
    w(f"  QSO points ......... {score.qso_points:>6}")
    w(f"  Power multiplier ... {mult:>6}  (×)")
    w(f"  QSO points × mult .. {score.qso_points * mult:>6}")
    w(f"  Bonus points ....... {score.bonus_points:>6}  (+)")
    w(f"  TOTAL SCORE ........ {score.total:>6}")
    w("")

    # --- Bonus itemisation ---
    selections = extra.get(BONUS_SELECTIONS_KEY)
    w("BONUS POINTS")
    if isinstance(selections, dict) and bonus_breakdown(selections):
        for item, pts in bonus_breakdown(selections):
            w(f"  [x] {item.label:<42} {pts:>5}")
        w(f"  {'Bonus subtotal':<46} {score.bonus_points:>5}")
    else:
        w("  (none claimed)")
    w("")

    w(bar)
    w("DUPE SHEET: upload the Cabrillo file (Logs > Export Cabrillo) as the")
    w("station-by-band/mode list. Full logs are not required.")
    w("Bonus items require documentation (photos, copies) sent with the entry.")
    w(bar)
    return "\n".join(out) + "\n"
