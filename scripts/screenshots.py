#!/usr/bin/env python
"""Generate documentation screenshots for every PartyHams Logger screen.

Runs fully headless using Qt's *offscreen* platform so it works in CI and over
SSH (no display needed). Each builder constructs one screen, populates it with a
small representative SAMPLE session (a handful of QSOs, a few roster peers, some
chat, some worked sections), sizes it, and saves a PNG under
``docs/screenshots/``.

Because the offscreen platform substitutes fonts/metrics, the captures are
*representative* rather than pixel-identical to a real desktop. Run with::

    python scripts/screenshots.py

It is idempotent: re-running just overwrites the PNGs.
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

# Must be set before importing any Qt module.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SHOTS_DIR = REPO_ROOT / "docs" / "screenshots"

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from partyhams.app.macros import load_macros  # noqa: E402
from partyhams.app.session import LogSession, build_session  # noqa: E402
from partyhams.core.models import Mode, utcnow  # noqa: E402
from partyhams.ui import style  # noqa: E402
from partyhams.ui.about_dialog import AboutDialog  # noqa: E402
from partyhams.ui.autoexport_dialog import AutoExportDialog  # noqa: E402
from partyhams.ui.cluster_window import ClusterWindow  # noqa: E402
from partyhams.ui.log_dialog import LogDialog  # noqa: E402
from partyhams.ui.macros_dialog import MacrosDialog  # noqa: E402
from partyhams.ui.main_window import MainWindow  # noqa: E402
from partyhams.ui.network_panel import NetworkPanel  # noqa: E402
from partyhams.ui.open_log_dialog import OpenLogDialog  # noqa: E402
from partyhams.ui.qrz_dialog import QrzDialog  # noqa: E402
from partyhams.ui.radio_dialog import RadioDialog  # noqa: E402
from partyhams.ui.sections_window import SectionsWindow  # noqa: E402
from partyhams.ui.shortcuts import ShortcutsDialog  # noqa: E402
from partyhams.ui.wsjtx_panel import WsjtxPanel  # noqa: E402

# --- sample data ----------------------------------------------------------- #

_SAMPLE_QSOS = [
    ("K1ABC", 14_040_000, Mode.CW, {"class": "2A", "section": "EMA"}),
    ("W2XYZ", 14_250_000, Mode.USB, {"class": "1D", "section": "NLI"}),
    ("N5DEF", 7_030_000, Mode.CW, {"class": "3A", "section": "STX"}),
    ("VE3GHI", 21_300_000, Mode.USB, {"class": "2A", "section": "ONE"}),
    ("KH6JKL", 3_540_000, Mode.CW, {"class": "1B", "section": "PAC"}),
    ("W7MNO", 14_060_000, Mode.CW, {"class": "4A", "section": "WWA"}),
    ("K9PQR", 21_350_000, Mode.USB, {"class": "2A", "section": "IL"}),
    ("N0STU", 7_200_000, Mode.LSB, {"class": "1E", "section": "MN"}),
]


def make_sample_session() -> LogSession:
    """An in-memory Field Day session with a spread of worked sections/bands."""
    session = build_session(
        contest_id="arrl-field-day",
        my_call="W7PH",
        operator="W7PH",
        sent_exchange={"class": "3A", "section": "OR"},
        power="low_150w",
        network=None,
    )
    session.set_local_status(14_040_000, Mode.CW)
    now = utcnow()
    for i, (call, freq, mode, exch) in enumerate(_SAMPLE_QSOS):
        qso = session.record_qso(call=call, freq_hz=freq, mode=mode, exchange=exch)
        qso.timestamp = now - timedelta(minutes=5 * (len(_SAMPLE_QSOS) - i))
    # A little chat traffic for the network panel.
    session.post_chat("*", "CQ Field Day from the W7PH multi-op!")
    session.post_chat("*", "20m CW is hopping — switch when you can")
    return session


def _save(widget: QWidget, name: str, width: int, height: int) -> Path:
    """Resize, render, and write ``widget`` to ``docs/screenshots/<name>.png``."""
    widget.resize(width, height)
    widget.show()
    QApplication.processEvents()
    out = SHOTS_DIR / f"{name}.png"
    widget.grab().save(str(out))
    widget.hide()
    return out


# --- per-screen builders --------------------------------------------------- #
# Each returns the widget so tests can construct them headlessly and assert
# a non-null QWidget without needing to write a file.


def build_main_window(session: LogSession) -> MainWindow:
    return MainWindow(session)


def build_network_panel(session: LogSession) -> NetworkPanel:
    panel = NetworkPanel(session)
    panel.refresh_roster()
    for entry in session.chat_messages():
        panel.append_chat(entry)
    return panel


def build_sections_window(session: LogSession) -> SectionsWindow:
    return SectionsWindow(session)


def build_cluster_window() -> ClusterWindow:
    return ClusterWindow(login_call="W7PH")


def build_wsjtx_panel() -> WsjtxPanel:
    panel = WsjtxPanel()
    panel.set_status(
        mode="FT8",
        dial_freq=14_074_000,
        tx_enabled=True,
        transmitting=False,
        tx_period_odd=False,
        sending="W7PH K1ABC -07",
    )
    for line in (
        "0001  -7  0.2 1623 ~  CQ K1ABC FN42",
        "0001 -12  0.1 1840 ~  W7PH N5DEF EM10",
        "0002  -3  0.3 1124 ~  CQ DX VE3GHI FN03",
    ):
        panel.add_decode(line)
    return panel


def build_macros_dialog(session: LogSession) -> MacrosDialog:
    return MacrosDialog(load_macros(session.contest), session.contest)


def build_log_dialog() -> LogDialog:
    return LogDialog()


def build_open_log_dialog() -> OpenLogDialog:
    return OpenLogDialog()


def build_radio_dialog() -> RadioDialog:
    return RadioDialog()


def build_qrz_dialog() -> QrzDialog:
    return QrzDialog(username="W7PH", password="")


def build_autoexport_dialog() -> AutoExportDialog:
    return AutoExportDialog(enabled=True, minutes=5, only_if_new=True)


def build_about_dialog() -> AboutDialog:
    return AboutDialog()


def build_shortcuts_dialog() -> ShortcutsDialog:
    return ShortcutsDialog()


# --- driver ---------------------------------------------------------------- #


def generate_all() -> list[Path]:
    """Build and save every screenshot. Returns the list of written paths."""
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    written: list[Path] = []

    # Default dark theme for all shots.
    style.apply_theme(app, style.DEFAULT_DARK)
    session = make_sample_session()

    win = build_main_window(session)
    written.append(_save(win, "main-window", 1060, 580))

    written.append(_save(build_network_panel(session), "network-panel", 360, 560))
    written.append(_save(build_sections_window(session), "sections", 960, 560))
    written.append(_save(build_cluster_window(), "dx-cluster", 720, 460))
    written.append(_save(build_wsjtx_panel(), "wsjtx", 640, 180))
    written.append(_save(build_macros_dialog(session), "macros", 600, 460))
    written.append(_save(build_log_dialog(), "new-log", 560, 460))
    written.append(_save(build_open_log_dialog(), "open-log", 560, 380))
    written.append(_save(build_radio_dialog(), "radio", 460, 320))
    written.append(_save(build_qrz_dialog(), "qrz", 420, 260))
    written.append(_save(build_autoexport_dialog(), "auto-export", 420, 240))
    written.append(_save(build_about_dialog(), "about", 420, 320))
    written.append(_save(build_shortcuts_dialog(), "shortcuts", 480, 460))

    # One light-theme capture of the main window for the themes page.
    style.apply_theme(app, style.DEFAULT_LIGHT)
    win.restyle()
    written.append(_save(win, "main-window-light", 1060, 580))
    style.apply_theme(app, style.DEFAULT_DARK)

    return written


def main() -> int:
    written = generate_all()
    for path in written:
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    print(f"{len(written)} screenshots written to {SHOTS_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
