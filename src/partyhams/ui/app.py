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

from partyhams.app.radio import RadioPoller
from partyhams.app.session import LogSession, build_session
from partyhams.radio.hamlib import HamlibRadio
from partyhams.ui.main_window import MainWindow
from partyhams.ui.start_dialog import StartDialog
from partyhams.ui.style import apply_theme


def _db_path_for(call: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", call) or "station"
    return str(Path.cwd() / f"partyhams-{safe}.sqlite")


def _session_from_dialog(cfg: dict) -> LogSession:
    return build_session(
        contest_id="arrl-field-day",
        my_call=cfg["my_call"],
        operator=cfg["operator"],
        sent_exchange={"class": cfg["fd_class"], "section": cfg["section"]},
        power=cfg["power"],
        network=cfg["network"] or None,
        db_path=_db_path_for(cfg["my_call"]),
    )


def run() -> int:
    """Launch the application. Returns the process exit code."""
    import qasync

    app = QApplication(sys.argv)
    apply_theme(app)
    # Don't let the brief gap between the dialog closing and the main window
    # showing trigger a quit; we drive shutdown explicitly from the window's
    # close event so async cleanup runs while the loop is still alive.
    app.setQuitOnLastWindowClosed(False)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    dialog = StartDialog()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return 0
    cfg = dialog.settings()
    session = _session_from_dialog(cfg)

    close_event = asyncio.Event()

    poller: RadioPoller | None = None
    if cfg.get("radio") == "hamlib":
        poller = RadioPoller(HamlibRadio(cfg["rig_host"], cfg["rig_port"]))

    async def amain() -> None:
        await session.start()
        active_poller = poller
        if active_poller is not None:
            try:
                await active_poller.start()
            except Exception as exc:  # noqa: BLE001 - fall back to manual entry
                print(f"Radio (rigctld) not reachable, continuing in manual mode: {exc}")
                active_poller = None
        window = MainWindow(session, on_close=close_event.set, radio_poller=active_poller)
        window.show()
        await close_event.wait()  # set when the user closes the window
        if active_poller is not None:
            await active_poller.stop()
        await session.stop()  # loop still alive here -> clean cancellation
        app.quit()

    # A single run_until_complete owns the whole session lifetime.
    with loop:
        loop.run_until_complete(amain())
    return 0
