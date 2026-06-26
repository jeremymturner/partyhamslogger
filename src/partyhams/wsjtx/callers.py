"""Track stations calling *us* in FT8/FT4, for the live "callers" button panel.

WSJT-X decode messages are short space-separated tokens, e.g.::

    W7PH K1ABC FN42      # K1ABC is calling us (W7PH) with a grid
    W7PH K1ABC 2A EMA    # ... with a Field Day class + section
    CQ POTA K1ABC FN42   # K1ABC is activating a park

:class:`CallerTracker` ingests decodes and keeps a per-callsign record of who is
calling us, when we last heard them (so the UI can expire them after a few
minutes), the ARRL section they sent (Field Day), and whether they've been heard
calling "CQ POTA" (a park activator — worth a park-to-park). It's Qt-free and
deterministic: the caller passes the current ``now`` (epoch seconds), so expiry
is testable without the wall clock.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

#: Drop a caller this many seconds after we last heard them (5 minutes).
CALLER_TTL_S = 300

# A 4-char Maidenhead grid (e.g. FN42) — so we don't mistake it for a callsign.
_GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}$")
# A loose callsign: alphanumerics (and "/"), at least one letter and one digit.
_CALL_RE = re.compile(r"^[A-Z0-9/]{3,}$")


def looks_like_call(token: str) -> bool:
    """True if ``token`` could be a callsign (and isn't a bare grid square)."""
    t = token.upper()
    if _GRID_RE.match(t) or not _CALL_RE.match(t):
        return False
    return any(c.isdigit() for c in t) and any(c.isalpha() for c in t)


def directed_caller(message: str, my_call: str) -> str:
    """The station calling ``my_call`` in ``"MYCALL CALLER …"``, else ``""``."""
    toks = message.upper().split()
    if len(toks) >= 2 and toks[0] == my_call.upper() and looks_like_call(toks[1]):
        return toks[1]
    return ""


def cq_caller(message: str) -> str:
    """The station calling CQ (skipping qualifiers like DX / POTA / TEST), else ``""``."""
    toks = message.upper().split()
    if not toks or toks[0] != "CQ":
        return ""
    for tok in toks[1:]:
        if looks_like_call(tok):
            return tok
    return ""


def is_pota_cq(message: str) -> bool:
    """True for a ``"CQ POTA …"`` decode (a park activation call)."""
    toks = message.upper().split()
    return len(toks) >= 2 and toks[0] == "CQ" and toks[1] == "POTA"


def pota_activator(message: str) -> str:
    """The activator's callsign from a ``"CQ POTA CALL …"`` decode, else ``""``."""
    return cq_caller(message) if is_pota_cq(message) else ""


def section_sent(message: str, my_call: str, is_section: Callable[[str], bool]) -> str:
    """The ARRL section a caller sent us in a Field Day exchange, else ``""``.

    For ``"MYCALL CALLER [R] CLASS SECTION"`` it scans the exchange tokens (after
    the caller) for the first valid section.
    """
    toks = message.upper().split()
    if len(toks) < 3 or toks[0] != my_call.upper():
        return ""
    for tok in toks[2:]:
        if is_section(tok):
            return tok
    return ""


@dataclass
class Caller:
    """One station heard calling us (newest state wins)."""

    call: str
    last_heard: float  # epoch seconds
    snr: int = 0
    section: str = ""  # ARRL section they sent (Field Day)
    pota: bool = False  # they've been heard calling "CQ POTA" (park activator)
    decode: object = None  # the latest Decode directed at us, for a WSJT-X reply


class CallerTracker:
    """Accumulates who's calling us, with section/POTA context and TTL expiry."""

    def __init__(
        self,
        *,
        ttl_s: int = CALLER_TTL_S,
        is_section: Callable[[str], bool] | None = None,
    ) -> None:
        self.ttl_s = ttl_s
        self._is_section = is_section  # set for Field Day, else None
        self._callers: dict[str, Caller] = {}
        self._pota: set[str] = set()  # calls heard activating a park

    def ingest(self, decode, *, my_call: str, now: float) -> Caller | None:  # noqa: ANN001
        """Fold one decode in. Returns the updated :class:`Caller` if the decode was
        directed at us, else ``None``."""
        message = getattr(decode, "message", "") or ""
        activator = pota_activator(message)
        if activator:
            self._pota.add(activator)
            if activator in self._callers:
                self._callers[activator].pota = True

        call = directed_caller(message, my_call)
        if not call:
            return None
        caller = self._callers.get(call)
        if caller is None:
            caller = Caller(call=call, last_heard=now)
            self._callers[call] = caller
        caller.last_heard = now
        caller.snr = getattr(decode, "snr", 0)
        caller.decode = decode
        caller.pota = caller.pota or (call in self._pota)
        if self._is_section is not None:
            sec = section_sent(message, my_call, self._is_section)
            if sec:
                caller.section = sec
        return caller

    def active(self, now: float) -> list[Caller]:
        """Callers heard within the TTL, newest first."""
        live = [c for c in self._callers.values() if now - c.last_heard <= self.ttl_s]
        return sorted(live, key=lambda c: c.last_heard, reverse=True)

    def prune(self, now: float) -> None:
        """Forget callers past the TTL."""
        stale = [k for k, c in self._callers.items() if now - c.last_heard > self.ttl_s]
        for k in stale:
            del self._callers[k]

    def decode_for(self, call: str):  # noqa: ANN201 - protocol.Decode | None
        caller = self._callers.get(call.upper())
        return caller.decode if caller is not None else None

    def remove(self, call: str) -> bool:
        """Drop a caller (e.g. once we've worked them). Returns True if removed."""
        return self._callers.pop((call or "").upper(), None) is not None

    def clear(self) -> None:
        self._callers.clear()
        self._pota.clear()
