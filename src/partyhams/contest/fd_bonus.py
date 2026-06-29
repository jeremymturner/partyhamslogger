"""ARRL Field Day bonus-point catalog.

Field Day bonus points (rules §7, *Bonus Points*) are itemized — each claimed
item adds a flat or per-unit amount, some of them capped. This module is the
data-driven catalog plus the helper that turns an operator's selections into a
point total. It is Qt-free and unit-tested; the entry dialog
(``ui/fd_summary_dialog.py``) renders it, ``FieldDay.score`` reads the aggregate
it produces, and the summary sheet itemises it.

Point values follow the published ARRL Field Day rules. They are intentionally
data here (not hard-coded in the scorer) so a rules tweak is a one-line edit.
"""

from __future__ import annotations

from dataclasses import dataclass

#: ``config.extra`` key holding the ``{item_key: bool | int}`` selection dict.
BONUS_SELECTIONS_KEY = "fd_bonus"


@dataclass(frozen=True)
class BonusItem:
    """One claimable Field Day bonus.

    ``counted`` items take a quantity (e.g. number of transmitters on emergency
    power, or NTS messages handled); their contribution is ``points × quantity``
    capped at ``max_points``. Flat items contribute ``points`` when claimed.
    """

    key: str
    label: str
    points: int
    counted: bool = False
    max_points: int | None = None
    note: str = ""

    def value(self, raw: object) -> int:
        """Points this item contributes given its stored selection value."""
        if self.counted:
            total = _as_int(raw) * self.points
            if self.max_points is not None:
                total = min(total, self.max_points)
            return total
        return self.points if raw else 0


# The standard Field Day bonus items. Order here is the order shown in the dialog
# and on the summary sheet.
FD_BONUS_ITEMS: tuple[BonusItem, ...] = (
    BonusItem(
        "emergency_power",
        "100% emergency power",
        100,
        counted=True,
        max_points=2000,
        note="100 points per transmitter (max 20 transmitters)",
    ),
    BonusItem("media_publicity", "Media publicity", 100),
    BonusItem("public_location", "Public location", 100),
    BonusItem("public_info_table", "Public information table", 100),
    BonusItem("message_to_sm_sec", "Message to ARRL SM/SEC", 100),
    BonusItem(
        "nts_messages",
        "Formal NTS messages handled",
        10,
        counted=True,
        max_points=100,
        note="10 points each (max 100)",
    ),
    BonusItem("satellite_qso", "Satellite QSO", 100),
    BonusItem("alternate_power", "Alternate power (natural source)", 100),
    BonusItem("w1aw_message", "W1AW Field Day bulletin copied", 100),
    BonusItem("educational_activity", "Educational activity", 100),
    BonusItem("elected_official_visit", "Site visit by an elected official", 100),
    BonusItem("agency_official_visit", "Site visit by a served-agency official", 100),
    BonusItem("safety_officer", "Safety officer", 100),
    BonusItem("social_media", "Social media", 100),
    BonusItem(
        "youth_participation",
        "Youth participation",
        20,
        counted=True,
        max_points=100,
        note="20 points each (max 100)",
    ),
    BonusItem("web_submission", "Entry submitted via the Field Day web app", 50),
)

FD_BONUS_BY_KEY: dict[str, BonusItem] = {item.key: item for item in FD_BONUS_ITEMS}


def _as_int(raw: object) -> int:
    try:
        return max(0, int(raw))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def bonus_total(selections: dict) -> int:
    """Total claimed bonus points from a ``{key: bool | int}`` selection dict."""
    return sum(item.value(selections.get(item.key)) for item in FD_BONUS_ITEMS)


def bonus_breakdown(selections: dict) -> list[tuple[BonusItem, int]]:
    """Each *claimed* bonus item paired with the points it contributes."""
    out: list[tuple[BonusItem, int]] = []
    for item in FD_BONUS_ITEMS:
        pts = item.value(selections.get(item.key))
        if pts:
            out.append((item, pts))
    return out
