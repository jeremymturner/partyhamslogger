"""ARRL/RAC contest section abbreviations (used by Field Day, Sweepstakes, etc.).

Sources (verified 2026-06-06), in agreement:
* ARRL/RAC contest section list — https://contests.arrl.org/contestmultipliers.php?a=wve
* ADIF 3.1.7 ARRL_Section enumeration — https://www.adif.org/317/ADIF_317.htm

Both list the same 85 current sections (71 US + 14 Canadian). ``DX`` is added here
as the Field Day designator for stations outside the US and Canada (it is not an
ARRL section, so ADIF does not enumerate it).

Retired abbreviations (per the ADIF enumeration's deleted dates) are intentionally
excluded, since this set validates *current* entries:
    GTA -> GH (2023) · MAR -> NB/NS (2023) · NT -> TER (2023) ·
    ON  -> ONE/ONN/ONS (2012) · NWT -> NT (2003)
If we later import historical ADIF logs, accept these as aliases at import time.

Note: this *contest* list also matches ADIF; it differs from the ARES/organizational
list at arrl.org/section-abbreviations only in presentation.
"""

from __future__ import annotations

ARRL_SECTIONS: frozenset[str] = frozenset(
    {
        # New England Division
        "CT",
        "EMA",
        "ME",
        "NH",
        "RI",
        "VT",
        "WMA",
        # Hudson Division
        "ENY",
        "NLI",
        "NNJ",
        # Atlantic Division
        "DE",
        "EPA",
        "MDC",
        "NNY",
        "SNJ",
        "WNY",
        "WPA",
        # Central Division
        "IL",
        "IN",
        "WI",
        # Dakota Division
        "MN",
        "ND",
        "SD",
        # Delta Division
        "AR",
        "LA",
        "MS",
        "TN",
        # Great Lakes Division
        "KY",
        "MI",
        "OH",
        # Midwest Division
        "IA",
        "KS",
        "MO",
        "NE",
        # New England covered above; Northwestern Division
        "AK",
        "EWA",
        "ID",
        "MT",
        "OR",
        "WWA",
        # Pacific Division
        "EB",
        "NV",
        "PAC",
        "SCV",
        "SF",
        "SJV",
        "SV",
        # Roanoke Division
        "NC",
        "SC",
        "VA",
        "WV",
        # Rocky Mountain Division
        "CO",
        "NM",
        "UT",
        "WY",
        # Southeastern Division
        "AL",
        "GA",
        "NFL",
        "SFL",
        "WCF",
        "PR",
        "VI",
        # Southwestern Division
        "AZ",
        "LAX",
        "ORG",
        "SB",
        "SDG",
        # West Gulf Division
        "NTX",
        "OK",
        "STX",
        "WTX",
        # Canada (RAC)
        "AB",
        "BC",
        "GH",
        "MB",
        "NB",
        "NL",
        "NS",
        "ONE",
        "ONN",
        "ONS",
        "PE",
        "QC",
        "SK",
        "TER",
        # Outside US/Canada
        "DX",
    }
)


def is_valid_section(value: str) -> bool:
    return value.upper() in ARRL_SECTIONS


def nearest_section(value: str) -> str | None:
    """The closest valid section to a (presumably mistyped) abbreviation, or None
    if nothing is similar enough. Used to suggest a fix for an invalid entry."""
    import difflib

    matches = difflib.get_close_matches(value.upper(), ARRL_SECTIONS, n=1, cutoff=0.6)
    return matches[0] if matches else None


# Sections grouped by US call district (0–9), VE for Canada, DX for the rest.
# This is the conventional call-area grouping used by section maps (PR/VI sit with
# the Southeastern "4" group; AK/PAC with their nearest mainland district).
SECTION_GROUPS: dict[str, tuple[str, ...]] = {
    "0": ("CO", "IA", "KS", "MN", "MO", "ND", "NE", "SD"),
    "1": ("CT", "EMA", "ME", "NH", "RI", "VT", "WMA"),
    "2": ("ENY", "NLI", "NNJ", "NNY", "SNJ", "WNY"),
    "3": ("DE", "EPA", "MDC", "WPA"),
    "4": ("AL", "GA", "KY", "NC", "NFL", "PR", "SC", "SFL", "TN", "VA", "VI", "WCF"),
    "5": ("AR", "LA", "MS", "NM", "NTX", "OK", "STX", "WTX"),
    "6": ("EB", "LAX", "ORG", "PAC", "SB", "SCV", "SDG", "SF", "SJV", "SV"),
    "7": ("AK", "AZ", "EWA", "ID", "MT", "NV", "OR", "UT", "WWA", "WY"),
    "8": ("MI", "OH", "WV"),
    "9": ("IL", "IN", "WI"),
    "VE": ("AB", "BC", "GH", "MB", "NB", "NL", "NS", "ONE", "ONN", "ONS", "PE", "QC", "SK", "TER"),
    "DX": ("DX",),
}

_SECTION_TO_GROUP = {sec: grp for grp, secs in SECTION_GROUPS.items() for sec in secs}


def section_group(section: str) -> str:
    """The call-district group ("0"–"9", "VE", "DX") for a section, or "?"."""
    return _SECTION_TO_GROUP.get(section.upper(), "?")


# ---------------------------------------------------------------------------- #
# Schematic map layout
# ---------------------------------------------------------------------------- #
# (row, col) for each section on a SCHEMATIC grid map — NOT a geographically
# exact projection. A pixel-accurate vector map of all ~85 ARRL/RAC sections is
# too much to hand-digitize; instead cells are arranged to roughly mirror US/
# Canada geography (west coast left, east coast right, Canada along the top).
# Refine cells freely — the renderer is purely data-driven from this table.
# Row 0 = top (Canada). Columns grow left (west) -> right (east).
SECTION_MAP_LAYOUT: dict[str, tuple[int, int]] = {
    # --- Canada (RAC), row 0–1 across the top, west -> east --------------- #
    "BC": (0, 1),
    "AB": (0, 3),
    "SK": (0, 4),
    "MB": (0, 5),
    "ONN": (0, 7),
    "QC": (0, 9),
    "NL": (0, 12),
    "TER": (0, 0),
    "ONE": (1, 8),
    "ONS": (1, 7),
    "GH": (1, 9),
    "NB": (1, 11),
    "PE": (1, 13),
    "NS": (1, 12),  # placed below/beside NB on the east coast
    # --- US: Pacific Northwest / Mountain (rows 2–3, west) ---------------- #
    "AK": (2, 0),
    "WWA": (2, 2),
    "EWA": (2, 3),
    "MT": (2, 4),
    "ND": (2, 5),
    "MN": (2, 6),
    "WI": (2, 7),
    "MI": (2, 8),
    "WNY": (2, 9),
    "NNY": (2, 10),
    "VT": (2, 11),
    "NH": (2, 12),
    "ME": (2, 13),
    "OR": (3, 2),
    "ID": (3, 3),
    "WY": (3, 4),
    "SD": (3, 5),
    "IA": (3, 6),
    "IL": (3, 7),
    "IN": (3, 8),
    "OH": (3, 9),
    "WPA": (3, 10),
    "ENY": (3, 11),
    "WMA": (3, 12),
    "EMA": (3, 13),
    # --- US: California / Central plains (row 4) -------------------------- #
    "SF": (4, 0),
    "SCV": (4, 1),
    "NV": (4, 2),
    "UT": (4, 3),
    "CO": (4, 4),
    "NE": (4, 5),
    "MO": (4, 6),
    "KY": (4, 7),
    "WV": (4, 8),
    "VA": (4, 9),
    "MDC": (4, 10),
    "NLI": (4, 11),
    "CT": (4, 12),
    "RI": (4, 13),
    # --- US: lower-California / South-central (row 5) --------------------- #
    "EB": (5, 0),
    "SV": (5, 1),
    "SJV": (5, 2),
    "PAC": (6, 0),  # Pacific (HI etc.) — placed bottom-left
    "AZ": (5, 3),
    "NM": (5, 4),
    "KS": (5, 5),
    "AR": (5, 6),
    "TN": (5, 7),
    "NC": (5, 8),
    "EPA": (5, 9),
    "NNJ": (5, 10),
    "SNJ": (5, 11),
    "DE": (5, 12),
    # --- US: Southern tier (row 6) --------------------------------------- #
    "LAX": (6, 1),
    "ORG": (6, 2),
    "SB": (6, 3),
    "OK": (6, 4),
    "NTX": (6, 5),
    "LA": (6, 6),
    "MS": (6, 7),
    "AL": (6, 8),
    "GA": (6, 9),
    "SC": (6, 10),
    # --- US: deep south / Gulf (row 7) ----------------------------------- #
    "SDG": (7, 2),
    "WTX": (7, 4),
    "STX": (7, 5),
    "WCF": (7, 9),
    "NFL": (7, 10),
    "SFL": (7, 11),
    "PR": (7, 13),
    "VI": (7, 14),
    # --- Outside US/Canada ----------------------------------------------- #
    "DX": (8, 0),
}
