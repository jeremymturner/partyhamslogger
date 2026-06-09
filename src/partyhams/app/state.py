"""Persistent application state — which log is current, and the radio choice.

Stored as a small JSON file under ``~/.partyhams/``. This is what lets the app
reopen the last log on launch and skip the radio prompt once it's been answered.
Logs themselves live in ``~/.partyhams/logs/`` and are self-describing (their
config is stored inside the SQLite file's ``meta`` table — see ``db/store.py``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path.home() / ".partyhams"
LOGS_DIR = APP_DIR / "logs"
STATE_FILE = APP_DIR / "state.json"


#: How many recently-used logs to remember for the Recent Logs menu.
MAX_RECENT_LOGS = 8


@dataclass
class AppState:
    #: Absolute path to the log to reopen on launch (None => show log creation).
    current_log: str | None = None
    #: Saved radio choice, e.g. {"kind": "hamlib"|"flex"|"none", "conn": "..."}.
    #: Native-LAN Icom kinds also carry "user"/"password". None means the radio
    #: prompt hasn't been answered yet.
    radio: dict | None = None
    #: Recently-used log paths, most-recent first (for the Recent Logs menu).
    recent_logs: list[str] = field(default_factory=list)
    #: Selected UI theme name (None => follow the OS light/dark setting).
    theme: str | None = None
    #: Auto-CQ repeat interval in seconds (clamped to 5..30 when used).
    autocq_interval: int = 10
    #: Base UI font family (None => Qt default) and point size (clamped 8..28).
    font_family: str | None = None
    font_size: int = 13


def load_state(path: Path = STATE_FILE) -> AppState:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return AppState()
    return AppState(
        current_log=data.get("current_log"),
        radio=data.get("radio"),
        recent_logs=data.get("recent_logs") or [],
        theme=data.get("theme"),
        autocq_interval=data.get("autocq_interval", 10),
        font_family=data.get("font_family"),
        font_size=data.get("font_size", 13),
    )


def save_state(state: AppState, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "current_log": state.current_log,
        "radio": state.radio,
        "recent_logs": state.recent_logs,
        "theme": state.theme,
        "autocq_interval": state.autocq_interval,
        "font_family": state.font_family,
        "font_size": state.font_size,
    }
    path.write_text(json.dumps(payload, indent=2))


def push_recent(state: AppState, path: str) -> None:
    """Record ``path`` as the most-recently-used log (dedup, capped)."""
    recent = [p for p in state.recent_logs if p != path]
    recent.insert(0, path)
    state.recent_logs = recent[:MAX_RECENT_LOGS]


def new_log_path(contest_id: str, call: str, logs_dir: Path = LOGS_DIR) -> str:
    """A default log-file path for a new event: ``<contest>-<call>.sqlite``."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", call).strip("_") or "station"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return str(logs_dir / f"{contest_id}-{safe}.sqlite")
