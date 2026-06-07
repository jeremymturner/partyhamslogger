"""Qt application bootstrap.

Shows the first-run dialog, builds a :class:`~partyhams.app.session.LogSession`
from the answers, and runs the main window on an asyncio event loop bridged to Qt
via :mod:`qasync` (so the entry window can ``await`` the sync engine directly).
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog

from partyhams.app.session import build_session
from partyhams.ui.main_window import MainWindow
from partyhams.ui.start_dialog import StartDialog


def _db_path_for(call: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", call) or "station"
    return str(Path.cwd() / f"partyhams-{safe}.sqlite")


def run() -> int:
    """Launch the application. Returns the process exit code."""
    import qasync

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    dialog = StartDialog()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return 0
    cfg = dialog.settings()

    session = build_session(
        contest_id="arrl-field-day",
        my_call=cfg["my_call"],
        operator=cfg["operator"],
        sent_exchange={"class": cfg["fd_class"], "section": cfg["section"]},
        power=cfg["power"],
        network=cfg["network"] or None,
        db_path=_db_path_for(cfg["my_call"]),
    )

    quit_event = asyncio.Event()
    app.aboutToQuit.connect(quit_event.set)

    with loop:
        loop.run_until_complete(session.start())
        window = MainWindow(session)
        window.show()
        loop.run_until_complete(quit_event.wait())
        loop.run_until_complete(session.stop())
    return 0
