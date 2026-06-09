"""Reference-data subsystem: super-check-partial, city.dat, and user lists.

This consumes standard ham reference files the operator *already has* on disk
(via the Tools menu's file pickers) — downloading them from the internet is out
of scope. Files are parsed into normalized forms, persisted under
``APP_DIR/refdata/``, and surfaced as call suggestions plus LoTW/eQSL/QRZ
"known user" indicators in the entry window.
"""

from __future__ import annotations

from partyhams.refdata.parsers import parse_city_dat, parse_scp, parse_user_list
from partyhams.refdata.store import RefData

__all__ = ["RefData", "parse_city_dat", "parse_scp", "parse_user_list"]
