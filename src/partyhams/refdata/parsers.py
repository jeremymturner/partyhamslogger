"""Pure parsers for standard ham reference files.

All parsers are network-free and operate on text, so they're trivially testable.
They're deliberately defensive: these community-maintained formats vary between
sources and versions, so we parse what's reasonable and silently skip junk.
"""

from __future__ import annotations

import re

#: A callsign is alphanumeric with optional ``/`` portable/secondary markers,
#: and always contains at least one digit — which conveniently rejects CSV
#: headers ("Call", "Date") and prose tokens that aren't real callsigns.
_CALL_RE = re.compile(r"^(?=[A-Z0-9/]*[0-9])[A-Z0-9]+(?:/[A-Z0-9]+)*$")


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
