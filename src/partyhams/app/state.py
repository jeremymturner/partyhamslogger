"""Persistent application state — which log is current, and the radio choice.

Stored as a small JSON file under ``~/.partyhams/``. This is what lets the app
reopen the last log on launch and skip the radio prompt once it's been answered.
Logs themselves live in ``~/.partyhams/logs/`` and are self-describing (their
config is stored inside the SQLite file's ``meta`` table — see ``db/store.py``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path.home() / ".partyhams"
LOGS_DIR = APP_DIR / "logs"
STATE_FILE = APP_DIR / "state.json"


@dataclass
class AppState:
    #: Absolute path to the log to reopen on launch (None => show log creation).
    current_log: str | None = None
    #: Saved radio choice, e.g. {"kind": "hamlib"|"flex"|"none", "conn": "..."}.
    #: None means the radio prompt hasn't been answered yet.
    radio: dict | None = None


def load_state(path: Path = STATE_FILE) -> AppState:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return AppState()
    return AppState(current_log=data.get("current_log"), radio=data.get("radio"))


def save_state(state: AppState, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"current_log": state.current_log, "radio": state.radio}
    path.write_text(json.dumps(payload, indent=2))


def new_log_path(contest_id: str, call: str, logs_dir: Path = LOGS_DIR) -> str:
    """A default log-file path for a new event: ``<contest>-<call>.sqlite``."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", call).strip("_") or "station"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return str(logs_dir / f"{contest_id}-{safe}.sqlite")
