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
from partyhams.core.clock import new_uuid  # noqa: E402
from partyhams.core.models import QSO, Mode, utcnow  # noqa: E402
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
    ("W3GHI", 21_300_000, Mode.USB, {"class": "2A", "section": "EPA"}),
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


def _save_hero(win: MainWindow, name: str, width: int, height: int, dock_width: int) -> Path:
    """Like _save, but widens the docked network panel so the roster text isn't
    truncated in the hero capture."""
    from PySide6.QtCore import Qt

    win.resize(width, height)
    win.show()
    QApplication.processEvents()
    dock = getattr(win, "_network_dock", None)
    if dock is not None:
        win.resizeDocks([dock], [dock_width], Qt.Orientation.Horizontal)
        QApplication.processEvents()
    out = SHOTS_DIR / f"{name}.png"
    win.grab().save(str(out))
    win.hide()
    return out


# --- per-screen builders --------------------------------------------------- #
# Each returns the widget so tests can construct them headlessly and assert
# a non-null QWidget without needing to write a file.


def build_main_window(session: LogSession) -> MainWindow:
    return MainWindow(session)


# Networked peers for the hero shots: (station_id, operator, station_call, freq, mode).
_FD_PEERS = [
    ("peer-ab", "AB1QRP", "K2RDX", 7_028_000, Mode.CW),
    ("peer-n0", "N0AW", "W0CPH", 14_255_000, Mode.USB),
    ("peer-w3", "W3GHI", "W3GHI", 21_025_000, Mode.CW),
]
_POTA_PEERS = [
    ("peer-kd", "KD2ABC", "KD2ABC", 7_032_000, Mode.CW),
    ("peer-ko", "KO4XYZ", "KO4XYZ", 14_062_000, Mode.CW),
]


# Valid US callsign building blocks. One-letter prefixes are K/N/W; two-letter
# prefixes start with A/K/N/W (an "A" prefix only pairs with A-L).
_ONE_PREFIXES = ("K", "N", "W")
_TWO_PREFIXES = (
    "AB", "AC", "AD", "AE", "AG", "AK", "KC", "KD",
    "KE", "KG", "NA", "NB", "ND", "WA", "WB", "WX",
)
_CALL_FORMATS = ("1x3", "1x2", "2x1", "2x2", "2x3")


def _us_callsign(n: int) -> str:
    """A valid US amateur callsign for index ``n``, cycling the common formats —
    1x3, 1x2, 2x1, 2x2, 2x3 — i.e. a one- or two-letter prefix, a single
    call-district digit, and a 1-3 letter suffix. Deterministic and unique for
    the small counts used in these sample logs."""
    fmt = _CALL_FORMATS[n % len(_CALL_FORMATS)]
    pre_len, suf_len = int(fmt[0]), int(fmt[2])
    digit = (n // len(_CALL_FORMATS)) % 10
    if pre_len == 1:
        prefix = _ONE_PREFIXES[n % len(_ONE_PREFIXES)]
    else:
        prefix = _TWO_PREFIXES[n % len(_TWO_PREFIXES)]
    suffix = "".join(chr(65 + (n * (k + 3) + 7 * k) % 26) for k in range(suf_len))
    return f"{prefix}{digit}{suffix}"


def _add_network_peers(session: LogSession, peers, exchange: dict[str, str]) -> None:
    """Inject live peer presence plus a few of each peer's QSOs, so the roster shows
    several stations with real rates/totals and the log shows peer-colored rows."""
    eng = session.engine
    now = utcnow()
    worked_n = 0
    for i, (sid, op, call, freq, mode) in enumerate(peers):
        eng.stations[sid] = {
            "operator": op,
            "call": call,
            "freq_hz": freq,
            "mode": mode.value,
            "power_w": 100.0,
            "swr": 1.2,
            "ft_tx_even": -1,
            "last_heard": now,
        }
        for j in range(3 + i):
            worked = _us_callsign(worked_n)  # valid US call, format varies
            worked_n += 1
            eng.log.apply(
                QSO(
                    uuid=new_uuid(),
                    station_id=sid,
                    operator=op,
                    station_callsign=call,
                    lamport=eng.clock.tick(),
                    call=worked,
                    freq_hz=freq,
                    mode=mode,
                    timestamp=now - timedelta(minutes=2 * j + i),
                    rst_sent="599",
                    rst_rcvd="599",
                    exchange_rcvd=dict(exchange),
                )
            )


def build_hero() -> MainWindow:
    """Field Day hero: the main window with a populated log and a few networked
    peers, showing off the multi-station roster + chat alongside the log."""
    session = make_sample_session()
    _add_network_peers(session, _FD_PEERS, {"class": "2A", "section": "WWA"})
    session.post_chat("*", "Run rate is climbing on 20m — nice work everyone!")
    win = MainWindow(session)
    win._panel.refresh_roster()
    win.refresh()
    return win


_POTA_QSOS = [
    ("K1ABC", 14_062_000, Mode.CW, {}),
    ("W2XYZ", 14_285_000, Mode.USB, {}),
    ("N5DEF", 7_032_000, Mode.CW, {}),
    ("W3GHI", 14_061_000, Mode.CW, {"park": "US-1234"}),  # park-to-park
    ("KH6JKL", 21_030_000, Mode.CW, {}),
    ("W7MNO", 14_063_000, Mode.CW, {}),
    ("K9PQR", 14_286_000, Mode.USB, {}),
    ("AC2DEF", 10_110_000, Mode.CW, {"park": "US-5678"}),  # park-to-park
]


def build_pota_hero() -> MainWindow:
    """POTA hero: an activation with the park station line, a populated log
    (a couple of park-to-park contacts), and networked peers."""
    session = build_session(
        contest_id="pota",
        my_call="W7PH",
        operator="W7PH",
        sent_exchange={},
        power="low_150w",
        network="pota-us-4403",
        extra={
            "park": "US-4403",
            "entity": "United States Of America",
            "location": "US-WY",
            "park_names": {"US-4403": "Medicine Bow - Routt National Forest"},
        },
    )
    session.set_local_status(14_062_000, Mode.CW)
    now = utcnow()
    for i, (call, freq, mode, exch) in enumerate(_POTA_QSOS):
        qso = session.record_qso(call=call, freq_hz=freq, mode=mode, exchange=exch)
        qso.timestamp = now - timedelta(minutes=3 * (len(_POTA_QSOS) - i))
    _add_network_peers(session, _POTA_PEERS, {})
    session.post_chat("*", "US-4403 activated — 20m CW is wide open!")
    session.post_chat("*", "P2P with US-1234, thanks for the contact 73")
    win = MainWindow(session)
    win._panel.refresh_roster()
    win.refresh()
    return win


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

    # README heroes: main window + networked peers, with the network dock widened
    # so the roster text shows in full. One for Field Day, one for POTA.
    written.append(_save_hero(build_hero(), "hero", 1320, 680, dock_width=380))
    written.append(_save_hero(build_pota_hero(), "hero-pota", 1320, 680, dock_width=380))

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
