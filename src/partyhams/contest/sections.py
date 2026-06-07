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
