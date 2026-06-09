"""On-disk reference-data store and runtime lookups.

Each imported file is normalized and persisted as JSON under
``APP_DIR/refdata/`` so it survives restarts without re-importing. Lookups are
in-memory: SCP prefix matching for call suggestions, LoTW/eQSL/QRZ membership
for "known user" indicators, and a longest-prefix city.dat lookup.
"""

from __future__ import annotations

import json
from pathlib import Path

from partyhams.app.state import APP_DIR
from partyhams.refdata.parsers import parse_city_dat, parse_scp, parse_user_list

REFDATA_DIR = APP_DIR / "refdata"

_SCP_FILE = "scp.json"
_CITY_FILE = "city.json"
_LOTW_FILE = "lotw.json"
_EQSL_FILE = "eqsl.json"
_QRZ_FILE = "qrz.json"


class RefData:
    """Holds parsed reference data and persists a normalized copy to disk."""

    def __init__(self, dir_: Path = REFDATA_DIR) -> None:
        self.dir = Path(dir_)
        self.scp: set[str] = set()
        self.city: dict[str, dict[str, str]] = {}
        self.lotw: set[str] = set()
        self.eqsl: set[str] = set()
        self.qrz: set[str] = set()

    # --- persistence -------------------------------------------------- #
    def _path(self, name: str) -> Path:
        return self.dir / name

    def _write_set(self, name: str, values: set[str]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(name).write_text(json.dumps(sorted(values)))

    def _read_set(self, name: str) -> set[str]:
        try:
            data = json.loads(self._path(name).read_text())
        except (OSError, ValueError):
            return set()
        return {str(c).upper() for c in data} if isinstance(data, list) else set()

    def load(self) -> None:
        """Load any previously-persisted reference files (missing => empty)."""
        self.scp = self._read_set(_SCP_FILE)
        self.lotw = self._read_set(_LOTW_FILE)
        self.eqsl = self._read_set(_EQSL_FILE)
        self.qrz = self._read_set(_QRZ_FILE)
        try:
            city = json.loads(self._path(_CITY_FILE).read_text())
        except (OSError, ValueError):
            city = {}
        self.city = city if isinstance(city, dict) else {}

    # --- imports (parse + store + persist) ---------------------------- #
    def import_scp(self, text: str) -> int:
        self.scp = parse_scp(text)
        self._write_set(_SCP_FILE, self.scp)
        return len(self.scp)

    def import_city_dat(self, text: str) -> int:
        self.city = parse_city_dat(text)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(_CITY_FILE).write_text(json.dumps(self.city))
        return len(self.city)

    def import_lotw(self, text: str, column: int = 0) -> int:
        self.lotw = parse_user_list(text, column)
        self._write_set(_LOTW_FILE, self.lotw)
        return len(self.lotw)

    def import_eqsl(self, text: str, column: int = 0) -> int:
        self.eqsl = parse_user_list(text, column)
        self._write_set(_EQSL_FILE, self.eqsl)
        return len(self.eqsl)

    def import_qrz(self, text: str, column: int = 0) -> int:
        self.qrz = parse_user_list(text, column)
        self._write_set(_QRZ_FILE, self.qrz)
        return len(self.qrz)

    # --- lookups ------------------------------------------------------ #
    def is_scp_match(self, fragment: str, limit: int = 20) -> list[str]:
        """SCP calls starting with ``fragment`` (or containing it as a fallback).

        Prefix matches rank first (the common case while typing a call); if the
        fragment is mid-call we still surface substring hits. Empty => no match.
        """
        frag = fragment.strip().upper()
        if not frag:
            return []
        starts = sorted(c for c in self.scp if c.startswith(frag))
        if len(starts) >= limit:
            return starts[:limit]
        contains = sorted(c for c in self.scp if frag in c and not c.startswith(frag))
        return (starts + contains)[:limit]

    def uses_lotw(self, call: str) -> bool:
        return call.strip().upper() in self.lotw

    def uses_eqsl(self, call: str) -> bool:
        return call.strip().upper() in self.eqsl

    def qrz_known(self, call: str) -> bool:
        return call.strip().upper() in self.qrz

    def city_lookup(self, call: str) -> dict[str, str] | None:
        """Longest-prefix match of ``call`` against the city.dat table."""
        key = call.strip().upper()
        if not key:
            return None
        if key in self.city:
            return self.city[key]
        for n in range(len(key) - 1, 0, -1):
            prefix = key[:n]
            if prefix in self.city:
                return self.city[prefix]
        return None
