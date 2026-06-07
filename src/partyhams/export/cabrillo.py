"""Cabrillo export — the standard contest-log submission format (v3.0).

Builds the header from the station's :class:`ContestConfig` and delegates each
``QSO:`` line to the active contest definition (so the per-contest column layout
lives with the contest, not here).
"""

from __future__ import annotations

from collections.abc import Iterable

from partyhams import __version__
from partyhams.contest.base import ContestConfig, ContestDefinition, ScoreSummary
from partyhams.core.models import QSO


def write_cabrillo(
    qsos: Iterable[QSO],
    config: ContestConfig,
    contest: ContestDefinition,
    score: ScoreSummary | None = None,
    operators: Iterable[str] | None = None,
) -> str:
    """Render a complete Cabrillo log as a string, ready to submit."""
    qsos = [q for q in qsos if not q.deleted]
    qsos.sort(key=lambda q: q.timestamp)

    lines = [
        "START-OF-LOG: 3.0",
        f"CREATED-BY: PartyHams Logger {__version__}",
        f"CONTEST: {contest.cabrillo_name or contest.id}",
        f"CALLSIGN: {config.my_call.upper()}",
    ]

    fd_class = config.sent_exchange.get("class")
    if fd_class:
        lines.append(f"LOCATION: {config.sent_exchange.get('section', '')}".rstrip())
        lines.append(f"CATEGORY: {fd_class}")

    if score is not None:
        lines.append(f"CLAIMED-SCORE: {score.total}")

    op_list = list(operators) if operators is not None else []
    if op_list:
        lines.append("OPERATORS: " + " ".join(sorted({o.upper() for o in op_list})))

    lines.extend(contest.cabrillo_qso_line(q, config) for q in qsos)
    lines.append("END-OF-LOG:")
    return "\n".join(lines) + "\n"
