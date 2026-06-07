"""ARRL/RAC contest section abbreviations (used by Field Day, Sweepstakes, etc.).

Source: the official ARRL/RAC *contest* section list,
https://contests.arrl.org/contestmultipliers.php?a=wve (verified 2026-06-06) —
85 sections (71 US + 14 Canadian). ``DX`` is added as the designator for stations
outside the US and Canada.

Note: this is the *contest* list, which differs from the ARES/organizational list
at arrl.org/section-abbreviations. Per RAC's restructuring, the Canadian sections
are AB, BC, GH (Golden Horseshoe), MB, NB, NL, NS, ONE, ONN, ONS, PE, QC, SK, TER
— i.e. GH replaced the former GTA, and the Maritimes (formerly MAR) are split into
NB/NS/PE.
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
