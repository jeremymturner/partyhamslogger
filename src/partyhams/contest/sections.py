"""ARRL/RAC section abbreviations used by Field Day (and ARRL/RAC contests).

Source: ARRL Field Day rules / ARRL section list. ``DX`` represents any station
outside the US and Canada.
"""

from __future__ import annotations

ARRL_SECTIONS: frozenset[str] = frozenset(
    {
        # Atlantic Division
        "DE",
        "EPA",
        "MDC",
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
        # Hudson Division
        "ENY",
        "NLI",
        "NNY",
        # Midwest Division
        "IA",
        "KS",
        "MO",
        "NE",
        # New England Division
        "CT",
        "EMA",
        "ME",
        "NH",
        "RI",
        "VT",
        "WMA",
        # Northwestern Division
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
        "GTA",
        "MAR",
        "MB",
        "NL",
        "ONE",
        "ONN",
        "ONS",
        "QC",
        "SK",
        "TER",
        # Outside US/Canada
        "DX",
    }
)


def is_valid_section(value: str) -> bool:
    return value.upper() in ARRL_SECTIONS
