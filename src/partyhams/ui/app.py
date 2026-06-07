"""Qt application bootstrap and startup flow.

On launch:
  1. If a *current log* is remembered, reopen it straight into the logging window.
  2. Otherwise show the log-creation screen (activity type + station setup).
  3. Once a log exists, if no radio has been configured, show the radio screen.
The current-log pointer and radio choice persist (``app/state.py``), so a normal
restart resumes silently. The asyncio loop is bridged to Qt via qasync.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog

from partyhams.app.radio import RadioPoller
from partyhams.app.session import LogSession, build_session, open_session
from partyhams.app.state import AppState, load_state, new_log_path, save_state
from partyhams.radio.flex import FlexRadio
from partyhams.radio.hamlib import HamlibRadio
from partyhams.ui.log_dialog import LogDialog
from partyhams.ui.main_window import MainWindow
from partyhams.ui.radio_dialog import RadioDialog
from partyhams.ui.style import app_icon, apply_theme

APP_NAME = "PartyHams Logger"


def _set_macos_app_name(name: str) -> None:
    """Set the macOS application menu title (the bold first menu).

    Qt reads it from the running bundle's ``CFBundleName``; for an unbundled
    Python process that's "Python". We override it via the Objective-C runtime
    (no extra dependency) and it must happen *before* QApplication is created.
    Best-effort: silently does nothing off macOS or if the runtime call fails.
    """
    if sys.platform != "darwin":
        return
    try:
        from ctypes import c_char_p, c_void_p, cdll, util

        objc = cdll.LoadLibrary(util.find_library("objc"))
        objc.objc_getClass.restype = c_void_p
        objc.objc_getClass.argtypes = [c_char_p]
        objc.sel_registerName.restype = c_void_p
        objc.sel_registerName.argtypes = [c_char_p]

        def send(receiver, selector, *args, argtypes=()):
            objc.objc_msgSend.restype = c_void_p
            objc.objc_msgSend.argtypes = [c_void_p, c_void_p, *argtypes]
            return objc.objc_msgSend(receiver, objc.sel_registerName(selector), *args)

        ns_string = objc.objc_getClass(b"NSString")

        def nsstr(text: str):
            return send(
                ns_string, b"stringWithUTF8String:", text.encode("utf-8"), argtypes=[c_char_p]
            )

        bundle = send(objc.objc_getClass(b"NSBundle"), b"mainBundle")
        info = send(bundle, b"infoDictionary")
        send(
            info,
            b"setObject:forKey:",
            nsstr(name),
            nsstr("CFBundleName"),
            argtypes=[c_void_p, c_void_p],
        )
    except Exception:  # noqa: BLE001 - cosmetic; never block startup
        pass


def _poller_from_radio(radio: dict | None) -> RadioPoller | None:
    """Build a RadioPoller from a saved radio choice, or None for manual."""
    if not radio:
        return None
    kind = radio.get("kind", "none")
    host, _, port_str = radio.get("conn", "").partition(":")
    host = host.strip() or None
    port = int(port_str) if port_str.strip().isdigit() else None
    if kind == "hamlib":
        return RadioPoller(HamlibRadio(host or "127.0.0.1", port or 4532))
    if kind == "flex":
        return RadioPoller(FlexRadio(host, port or 4992))  # host=None -> discover
    return None


def _session_from_log_dialog(cfg: dict) -> tuple[LogSession, str]:
    db_path = new_log_path(cfg["contest_id"], cfg["my_call"])
    session = build_session(
        contest_id=cfg["contest_id"],
        my_call=cfg["my_call"],
        operator=cfg["operator"],
        sent_exchange=cfg["sent_exchange"],
        network=cfg["network"] or None,
        extra=cfg["extra"],
        db_path=db_path,
    )
    return session, db_path


def _open_or_create_log(state: AppState) -> LogSession | None:
    """Reopen the remembered log, or run the creation screen. None if cancelled."""
    if state.current_log and Path(state.current_log).exists():
        with contextlib.suppress(Exception):
            return open_session(state.current_log)  # fall through if corrupt/old

    dialog = LogDialog()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    session, db_path = _session_from_log_dialog(dialog.settings())
    state.current_log = db_path
    save_state(state)
    return session


async def _start_poller(poller: RadioPoller | None, window: MainWindow) -> RadioPoller | None:
    """Start a poller, falling back to manual entry if the radio isn't reachable."""
    if poller is None:
        return None
    try:
        await poller.start()
    except Exception as exc:  # noqa: BLE001
        window.statusBar().showMessage(f"Radio not reachable, manual mode: {exc}", 5000)
        return None
    return poller


def run() -> int:
    """Launch the application. Returns the process exit code."""
    import qasync

    _set_macos_app_name(APP_NAME)  # must precede QApplication construction
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())  # window/taskbar; also the macOS dock tile
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    state = load_state()
    session = _open_or_create_log(state)
    if session is None:
        return 0

    # Prompt for a radio only if the choice hasn't been made yet.
    if state.radio is None:
        rdlg = RadioDialog()
        if rdlg.exec() == QDialog.DialogCode.Accepted:
            state.radio = rdlg.settings()
            save_state(state)

    close_event = asyncio.Event()
    holder: dict[str, RadioPoller | None] = {"poller": _poller_from_radio(state.radio)}

    async def amain() -> None:
        await session.start()
        window = MainWindow(session, on_close=close_event.set)
        holder["poller"] = await _start_poller(holder["poller"], window)
        window.set_poller(holder["poller"])
        window.on_change_radio = lambda: _request_radio_change(window)
        window.show()
        await close_event.wait()
        if holder["poller"] is not None:
            await holder["poller"].stop()
        await session.stop()
        app.quit()

    def _request_radio_change(window: MainWindow) -> None:
        # Show the dialog NON-blocking (open(), not exec()) so we never spin a
        # nested event loop inside a running task — that re-enters the asyncio
        # scheduler and crashes qasync. The async swap is scheduled on `finished`.
        dialog = RadioDialog(current=state.radio, parent=window)
        window._radio_dialog = dialog  # keep a reference alive while open
        dialog.finished.connect(lambda result: _on_radio_dialog_done(window, dialog, result))
        dialog.open()

    def _on_radio_dialog_done(window: MainWindow, dialog: RadioDialog, result: int) -> None:
        window._radio_dialog = None
        if result == QDialog.DialogCode.Accepted.value:
            state.radio = dialog.settings()
            save_state(state)
            loop.create_task(_apply_radio(window))

    async def _apply_radio(window: MainWindow) -> None:
        if holder["poller"] is not None:
            await holder["poller"].stop()
        holder["poller"] = await _start_poller(_poller_from_radio(state.radio), window)
        window.set_poller(holder["poller"])

    with loop:
        loop.run_until_complete(amain())
    return 0
