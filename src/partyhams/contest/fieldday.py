"""ARRL Field Day — the MVP contest module.

Implements the real rules (decision #5):

* **Exchange:** ``Class + Section`` (e.g. ``3A OR``).
* **Dupes:** per band *and* per mode-group (CW / Phone / Digital are separate).
* **QSO points:** Phone = 1, CW = 2, Digital = 2.
* **Power multiplier (on QSO points):** ≤5 W alt-power = ×5, ≤150 W = ×2, >150 W = ×1.
* **Score:** ``(QSO points × power multiplier) + bonus points``.
* **No QSO-count multipliers** — sections are exchange data, not mults.

Note the multiplier subsystem is intentionally exercised by a *later* module
(CQ WW / WPX); see IDEAS.md §4.1.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Iterable

from partyhams.contest.base import (
    ConfigField,
    ContestConfig,
    ContestDefinition,
    ExchangeField,
    Macro,
    ScoreSummary,
    _macros,
)
from partyhams.contest.registry import register
from partyhams.contest.sections import ARRL_SECTIONS, is_valid_section
from partyhams.core.models import QSO, ModeGroup

# Class = number of transmitters (1+) followed by a category letter A–F.
_CLASS_RE = re.compile(r"^[1-9][0-9]?[A-F]$")

# Field Day legal bands: all contest HF bands plus VHF/UHF, EXCLUDING the WARC
# bands (30/17/12 m) and the channelized 60 m band.
_ALLOWED_BANDS: frozenset[str] = frozenset(
    {"160m", "80m", "40m", "20m", "15m", "10m", "6m", "2m", "1.25m", "70cm"}
)

# QSO points by mode group.
_POINTS: dict[ModeGroup, int] = {
    ModeGroup.PHONE: 1,
    ModeGroup.CW: 2,
    ModeGroup.DIGITAL: 2,
}

# Cabrillo mode token by mode group.
_CABRILLO_MODE: dict[ModeGroup, str] = {
    ModeGroup.CW: "CW",
    ModeGroup.PHONE: "PH",
    ModeGroup.DIGITAL: "DG",
}


class PowerCategory(enum.Enum):
    """Field Day power multiplier categories. Stored in ``config.extra['power']``."""

    QRP_5W_ALT = ("qrp_5w_alt", 5)  # ≤5 W, non-commercial power (battery/solar/etc.)
    LOW_150W = ("low_150w", 2)  # ≤150 W output
    HIGH = ("high", 1)  # >150 W output

    def __init__(self, key: str, multiplier: int) -> None:
        self.key = key
        self.multiplier = multiplier

    @classmethod
    def from_key(cls, key: str) -> PowerCategory:
        for member in cls:
            if member.key == key:
                return member
        raise ValueError(f"unknown power category: {key!r}")


def is_valid_class(value: str) -> bool:
    """True for a well-formed Field Day class like ``3A`` or ``1E``."""
    return bool(_CLASS_RE.match(value.upper()))


@register
class FieldDay(ContestDefinition):
    id = "arrl-field-day"
    name = "ARRL Field Day"
    cabrillo_name = "ARRL-FD"
    exchanges_rst = False  # Field Day exchange is class + section only — no RST
    mult_label = "Sections"
    mult_total = len(ARRL_SECTIONS - {"DX"})  # the 85 ARRL/RAC sections (DX excluded)

    def default_macros(self) -> dict[str, list[Macro]]:
        # Modeled on N1MM's Field Day messages (FD exchange = class + section, no
        # RST). Separate Run and S&P CW banks; F3 (Run) / F2 (S&P) log the QSO.
        cw_run = [
            ("CQ", "CQ FD {MYCALL} {MYCALL} FD"),
            ("Exch", "{EXCH}"),
            ("TU", "TU {MYCALL} FD {LOG}"),
            ("MyCall", "{MYCALL}"),
            ("HisCall", "{CALL}"),
            ("Repeat", "{EXCH} {EXCH}"),
            ("Sec?", "SEC?"),
            ("Agn?", "AGN?"),
            ("Cls?", "CL?"),
            ("Call?", "CALL?"),
            ("", ""),
            ("Wipe", "{WIPE}"),
        ]
        cw_sp = list(cw_run)
        cw_sp[2] = ("TU", "TU {LOG}")  # S&P: brief TU (the exchange key logs)
        phone = [("CQ FD", ""), ("Exch", ""), ("TU", ""), ("QRZ", ""), *[("", "")] * 8]
        return {
            "CW.RUN": _macros(cw_run),
            "CW.SP": _macros(cw_sp),
            "PHONE.RUN": _macros(phone),
            "PHONE.SP": _macros(phone),
        }

    def config_fields(self) -> list[ConfigField]:
        return [
            ConfigField(
                "power",
                "Power",
                choices=(
                    ("Low — ≤150 W (×2)", PowerCategory.LOW_150W.key),
                    ("QRP — ≤5 W, alt power (×5)", PowerCategory.QRP_5W_ALT.key),
                    ("High — >150 W (×1)", PowerCategory.HIGH.key),
                ),
                default=PowerCategory.LOW_150W.key,
            ),
        ]

    def exchange_fields(self) -> list[ExchangeField]:
        return [
            ExchangeField("class", "Class", required=True, validator=is_valid_class),
            ExchangeField("section", "Section", required=True, validator=is_valid_section),
        ]

    def allowed_bands(self) -> set[str]:
        return set(_ALLOWED_BANDS)

    def dupe_key(self, qso: QSO) -> tuple:
        # Per band AND per mode-group: 20m CW and 20m Phone to the same call are
        # both countable, but a second 20m CW QSO with that call is a dupe.
        return (qso.band_label, qso.mode_group.value, qso.call.upper())

    def qso_points(self, qso: QSO) -> int:
        return _POINTS[qso.mode_group]

    def multipliers(self, qso: QSO) -> set[tuple[str, str]]:
        # Sections do NOT multiply the Field Day score (see ``score`` below), but
        # working all ARRL/RAC sections is the event's secondary goal, so we track
        # them here to drive the "Sections" counter and the new-mult highlight.
        section = qso.exchange_rcvd.get("section", "").upper()
        return {("section", section)} if section else set()

    def power_category(self, config: ContestConfig) -> PowerCategory:
        raw = config.extra.get("power", PowerCategory.LOW_150W.key)
        if isinstance(raw, PowerCategory):
            return raw
        return PowerCategory.from_key(str(raw))

    def score(self, qsos: Iterable[QSO], config: ContestConfig) -> ScoreSummary:
        qsos = list(qsos)
        base = super().score(qsos, config)  # qso_count + qso_points (no mults)

        power = self.power_category(config)
        bonus = int(config.extra.get("bonus_points", 0))
        total = base.qso_points * power.multiplier + bonus

        # Per band+mode breakdown for the score window.
        by_band_mode: dict[str, int] = {}
        seen: set[tuple] = set()
        for q in qsos:
            if q.deleted:
                continue
            key = self.dupe_key(q)
            if key in seen:
                continue
            seen.add(key)
            slot = f"{q.band_label} {q.mode_group.value}"
            by_band_mode[slot] = by_band_mode.get(slot, 0) + 1

        base.bonus_points = bonus
        base.total = total
        base.breakdown = {
            "power_category": power.key,
            "power_multiplier": power.multiplier,
            "by_band_mode": by_band_mode,
        }
        return base

    def cabrillo_qso_line(self, qso: QSO, config: ContestConfig) -> str:
        freq_khz = qso.freq_hz // 1000
        mode = _CABRILLO_MODE[qso.mode_group]
        date = qso.timestamp.strftime("%Y-%m-%d")
        time = qso.timestamp.strftime("%H%M")
        my_call = config.my_call.upper()
        sent = config.sent_exchange
        sent_exch = f"{sent.get('class', '')} {sent.get('section', '')}".strip()
        rcvd = qso.exchange_rcvd
        rcvd_exch = f"{rcvd.get('class', '')} {rcvd.get('section', '')}".strip()
        # QSO: freq mode date time mycall  <sent>  call  <rcvd>
        return (
            f"QSO: {freq_khz:>7} {mode:>2} {date} {time} "
            f"{my_call:<10} {sent_exch:<8} {qso.call.upper():<10} {rcvd_exch:<8}"
        ).rstrip()
