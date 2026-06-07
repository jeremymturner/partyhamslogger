"""F-key macros: variable substitution and per-contest persistence.

A macro's CW/digital ``content`` is text with ``{VAR}`` substitutions and inline
``{ACTION}`` markers; phone content is a ``.wav`` path. Substitution is N1MM-style
but uses our ``{NAME}`` syntax (e.g. ``{MYCALL}``, ``{CALL}``, ``{EXCH}``).

Each *event* (contest) keeps its own macro set, persisted under
``~/.partyhams/macros/<contest_id>.json``; missing files fall back to the
contest's :meth:`~partyhams.contest.base.ContestDefinition.default_macros`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from partyhams.app.state import APP_DIR
from partyhams.contest.base import ContestDefinition, Macro

MACROS_DIR = APP_DIR / "macros"
DEFAULT_WPM = 28

# Inline markers that trigger an action instead of being sent as text.
_ACTIONS = {"LOG", "WIPE"}
_TOKEN_RE = re.compile(r"\{([A-Za-z0-9_&?]+)\}")


def expand(template: str, context: dict[str, str]) -> tuple[str, list[str]]:
    """Expand ``{VAR}`` tokens and pull out ``{ACTION}`` markers.

    Returns ``(text_to_send, actions)`` where actions is a lowercase list like
    ``["log"]``. Unknown ``{tokens}`` expand to empty. Whitespace is collapsed.
    """
    actions: list[str] = []

    def replace(match: re.Match) -> str:
        name = match.group(1).upper()
        if name in _ACTIONS:
            actions.append(name.lower())
            return ""
        return str(context.get(name, ""))

    text = _TOKEN_RE.sub(replace, template)
    text = re.sub(r"\s+", " ", text).strip()
    return text, actions


@dataclass
class MacroSet:
    cw_wpm: int = DEFAULT_WPM
    groups: dict[str, list[Macro]] = field(default_factory=dict)

    def get(self, group: str, key: int) -> Macro | None:
        for macro in self.groups.get(group, []):
            if macro.key == key:
                return macro
        return None

    @classmethod
    def from_defaults(cls, contest: ContestDefinition) -> MacroSet:
        return cls(cw_wpm=DEFAULT_WPM, groups=contest.default_macros())


def _macros_path(contest_id: str, macros_dir: Path = MACROS_DIR) -> Path:
    return macros_dir / f"{contest_id}.json"


def load_macros(contest: ContestDefinition, macros_dir: Path = MACROS_DIR) -> MacroSet:
    """Load this event's macros, or the contest defaults if none are saved."""
    path = _macros_path(contest.id, macros_dir)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return MacroSet.from_defaults(contest)
    groups = {
        group: [Macro(m["key"], m["label"], m["content"]) for m in macros]
        for group, macros in data.get("groups", {}).items()
    }
    if not groups:
        groups = contest.default_macros()
    return MacroSet(cw_wpm=int(data.get("cw_wpm", DEFAULT_WPM)), groups=groups)


def save_macros(contest_id: str, macro_set: MacroSet, macros_dir: Path = MACROS_DIR) -> None:
    macros_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "cw_wpm": macro_set.cw_wpm,
        "groups": {
            group: [{"key": m.key, "label": m.label, "content": m.content} for m in macros]
            for group, macros in macro_set.groups.items()
        },
    }
    _macros_path(contest_id, macros_dir).write_text(json.dumps(payload, indent=2))
