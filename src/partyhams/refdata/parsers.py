"""Pure parsers for standard ham reference files.

All parsers are network-free and operate on text, so they're trivially testable.
They're deliberately defensive: these community-maintained formats vary between
sources and versions, so we parse what's reasonable and silently skip junk.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: A callsign is alphanumeric with optional ``/`` portable/secondary markers,
#: and always contains at least one digit — which conveniently rejects CSV
#: headers ("Call", "Date") and prose tokens that aren't real callsigns.
_CALL_RE = re.compile(r"^(?=[A-Z0-9/]*[0-9])[A-Z0-9]+(?:/[A-Z0-9]+)*$")

#: Common N1MM call-history column names mapped to our exchange field keys.
_HISTORY_ALIASES = {"sect": "section"}


def _clean_lines(text: str) -> list[str]:
    """Yield stripped, non-blank, non-comment lines (``#`` starts a comment)."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def parse_scp(text: str) -> set[str]:
    """Parse a super-check-partial file (e.g. ``MASTER.SCP``).

    Format: one callsign per line; blank lines and ``#`` comments ignored.
    Returns an uppercased set of valid-looking callsigns.
    """
    calls: set[str] = set()
    for line in _clean_lines(text):
        # A real SCP line is a single bare callsign; lines with internal spaces
        # (prose, junk) are not callsigns and are skipped.
        if len(line.split()) != 1:
            continue
        token = line.upper()
        if _CALL_RE.match(token):
            calls.add(token)
    return calls


def parse_user_list(text: str, column: int = 0) -> set[str]:
    """Parse a LoTW / eQSL / QRZ user list (callsign per line, or CSV).

    ``column`` selects which comma-separated field holds the call (default the
    first). Whitespace-only and comment lines are skipped; calls are uppercased.
    """
    calls: set[str] = set()
    for line in _clean_lines(text):
        parts = [p.strip() for p in line.split(",")] if "," in line else [line]
        if column >= len(parts):
            continue
        token = parts[column].split()[0].upper() if parts[column] else ""
        if _CALL_RE.match(token):
            calls.add(token)
    return calls


def parse_city_dat(text: str) -> dict[str, dict[str, str]]:
    """Parse an AK1A/CT ``city.dat``-style prefix→QTH table.

    The canonical record is comma-separated: ``prefix,name,state,section`` (some
    sources append a county or other trailing fields, which we ignore). We also
    tolerate whitespace-delimited rows. The key is the uppercased prefix/call;
    the value is a dict with whichever of ``name``/``state``/``section`` exist.
    Junk lines (no usable prefix) are skipped.
    """
    table: dict[str, dict[str, str]] = {}
    for line in _clean_lines(text):
        parts = [p.strip() for p in line.split(",")] if "," in line else line.split()
        parts = [p for p in parts if p]
        if not parts:
            continue
        prefix = parts[0].upper()
        if not _CALL_RE.match(prefix):
            continue
        record: dict[str, str] = {}
        for key, idx in (("name", 1), ("state", 2), ("section", 3)):
            if idx < len(parts) and parts[idx]:
                record[key] = parts[idx]
        table[prefix] = record
    return table


def parse_call_history(
    text: str,
    fields: Iterable[str],
    aliases: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    """Parse a call-history file into a ``{CALL: {exchange_field: value}}`` map.

    Two layouts are auto-detected:

    * **N1MM Call History** — a header line ``!!Order!!,Call,Sect,…`` declares the
      column order; ``#`` comments and blank lines are ignored; data rows follow.
    * **Simple CSV** — the first non-comment line is a header naming the columns,
      the first of which must be ``Call``.

    Column names are matched case-insensitively against ``fields`` (the active
    contest's exchange field names, e.g. ``{"class", "section"}``), with
    ``aliases`` (default ``sect→section``) bridging common N1MM names. Columns
    that don't map to an exchange field are ignored. Calls are uppercased and
    entries carrying no recognized exchange values are dropped — so importing a
    file for the wrong contest simply yields nothing rather than bad data.
    """
    canon = {f.lower(): f for f in fields}  # lowercased column name -> our key
    alias_map = {**_HISTORY_ALIASES, **(aliases or {})}
    lines = _clean_lines(text)
    if not lines:
        return {}

    # Header: an explicit N1MM !!Order!! line wins; otherwise the first line.
    header, body = lines[0], lines[1:]
    for i, line in enumerate(lines):
        if line.lower().startswith("!!order!!"):
            header = line.split(",", 1)[1] if "," in line else ""
            body = lines[i + 1 :]
            break

    cols = [c.strip() for c in header.split(",")]
    call_idx = next((i for i, c in enumerate(cols) if c.lower() == "call"), None)
    if call_idx is None:
        return {}
    # Resolve each column to a canonical exchange-field key (None => ignore it).
    resolved = [canon.get(alias_map.get(c.lower(), c.lower())) for c in cols]

    out: dict[str, dict[str, str]] = {}
    for line in body:
        if line.lower().startswith("!!order!!"):
            continue  # stray repeated header
        parts = [p.strip() for p in line.split(",")]
        if call_idx >= len(parts) or not parts[call_idx]:
            continue
        call = parts[call_idx].split()[0].upper()
        if not _CALL_RE.match(call):
            continue
        record = {
            key: parts[i]
            for i, key in enumerate(resolved)
            if key and i != call_idx and i < len(parts) and parts[i]
        }
        if record:
            out[call] = record
    return out
