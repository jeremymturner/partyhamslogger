"""The main logging window: score bar, keyboard-first entry row, and live log.

Binds to a :class:`~partyhams.app.session.LogSession`. The entry row is built
*from the contest's exchange schema*, so this same window serves any contest —
Field Day today, CQ WW tomorrow — with no UI changes.

Keyboard flow (N1MM-style): type the call, Enter advances to the next empty
field, Enter on the last field logs the QSO, clears, and refocuses the call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QActionGroup, QCloseEvent, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from partyhams.app.banter import StationSnapshot, choose_message
from partyhams.app.macros import bank_key, esm_step, expand, load_macros, save_macros
from partyhams.app.radio import RadioPoller
from partyhams.app.session import LogSession, default_rst
from partyhams.core.models import (
    Band,
    Mode,
    band_by_label,
    band_for_freq,
    mode_group_for,
    utcnow,
)
from partyhams.export import timestamped_adif_name
from partyhams.qrz import QrzClient, format_record
from partyhams.radio.base import Capability, RadioState
from partyhams.refdata import RefData
from partyhams.ui import shortcuts as sc
from partyhams.ui import style
from partyhams.ui.about_dialog import AboutDialog
from partyhams.ui.cluster_window import ClusterWindow
from partyhams.ui.help_window import HelpWindow
from partyhams.ui.macros_dialog import MacrosDialog
from partyhams.ui.network_panel import NetworkPanel
from partyhams.ui.sections_window import SectionsWindow
from partyhams.ui.shortcuts import ShortcutsDialog
from partyhams.ui.widgets import make_upper
from partyhams.ui.wsjtx_panel import WsjtxPanel
from partyhams.wsjtx.convert import (
    map_mode,
    parse_tx_power,
    qso_logged_to_record,
    tx_even_from_epoch,
)
from partyhams.wsjtx.listener import WsjtxListener
from partyhams.wsjtx.protocol import Decode, QSOLogged, Status

# Modes offered in the entry row.
_ENTRY_MODES = [Mode.CW, Mode.USB, Mode.LSB, Mode.FM, Mode.RTTY, Mode.FT8]

# Default hint shown on the empty call field (replaced by live match/QSL hints).
_CALL_TOOLTIP = (
    "Type the worked station's callsign, then press Enter to advance. "
    "Hints (dupe, super-check-partial, QRZ) appear here as you type."
)


def _format_tx_status(word: str, key: int, label: str, text: str) -> str:
    """Build the transmit indicator shown on the left of the status bar.

    ``word`` is ``TRANSMITTING`` while sending, then ``SENT`` once done.
    """
    label_part = f" — {label}" if label else ""
    return f"{word} — F{key}{label_part} — {text}"


#: Allowed Auto-CQ repeat intervals (seconds) and the clamp bounds.
AUTOCQ_INTERVALS = (5, 8, 10, 15, 20, 30)
AUTOCQ_MIN = 5
AUTOCQ_MAX = 30


def clamp_autocq_interval(seconds: int) -> int:
    """Clamp an Auto-CQ interval into the supported 5..30 second range."""
    return max(AUTOCQ_MIN, min(AUTOCQ_MAX, int(seconds)))


def should_autocq(run: bool, enabled: bool, call_text: str) -> bool:
    """Whether the Auto-CQ timer should fire F1 right now.

    Only in Run mode, only while enabled, and never while the operator has
    started entering a callsign (we don't keep CQ-ing while working someone).
    """
    return bool(run and enabled and not call_text.strip())


#: Allowed periodic ADIF auto-export interval bounds (minutes).
AUTOEXPORT_MIN = 5
AUTOEXPORT_MAX = 60


def clamp_export_minutes(minutes: int) -> int:
    """Clamp an auto-export interval into the supported 5..60 minute range."""
    return max(AUTOEXPORT_MIN, min(AUTOEXPORT_MAX, int(minutes)))


def should_autoexport(
    enabled: bool, only_if_new: bool, current_count: int, last_count: int
) -> bool:
    """Whether a periodic auto-export should write now (timer/log checks aside).

    Disabled never exports. When "only if new" is set, export only if the QSO
    count has increased since the last successful export; otherwise always.
    """
    if not enabled:
        return False
    if only_if_new and current_count <= last_count:
        return False
    return True


class MainWindow(QMainWindow):
    def __init__(
        self,
        session: LogSession,
        on_close: Callable[[], None] | None = None,
        radio_poller: RadioPoller | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self._on_close = on_close
        self._macros = load_macros(session.contest)  # this event's F-key macros
        self._macros_dialog = None
        self._sound = None  # keep a ref to the playing voice clip
        self._run = True  # Run vs Search & Pounce (picks the macro bank)
        self._esm = False  # ESM: Enter sends the next message
        self._esm_sent = False  # have we sent our exchange/call this QSO?
        self._autocq = False  # Auto-CQ: repeat F1 on a timer while in Run mode
        self._autocq_interval = 10  # seconds; set from app state via set_autocq_interval
        #: Set by the app: on_autocq_interval(secs) persists the chosen interval.
        self.on_autocq_interval: Callable[[int], None] | None = None
        # Periodic ADIF auto-export settings (driven from app state).
        self._autoexport_enabled = True
        self._autoexport_minutes = 5  # clamped to 5..60 when applied
        self._autoexport_only_if_new = True
        self._autoexport_last_count = 0  # QSO count at the last successful export
        #: Set by the app: on_change_autoexport(enabled, minutes, only_if_new).
        self.on_change_autoexport: Callable[[bool, int, bool], None] | None = None
        self._sections_window: SectionsWindow | None = None
        self._cluster_window: ClusterWindow | None = None
        # Reference data (super-check-partial, city.dat, LoTW/eQSL/QRZ user lists).
        # Imported via Tools menu; loaded from disk on launch (missing => empty).
        self._refdata = RefData()
        self._refdata.load()
        # QRZ.com lookup: credentials come from app state; lookups are debounced
        # and run in the background, surfacing results in the status bar.
        self._qrz = QrzClient()
        self._qrz_last_call = ""  # debounce: don't re-look-up the same call
        #: Set by the app: on_change_qrz(username, password) persists credentials.
        self.on_change_qrz: Callable[[str, str], None] | None = None
        self._qrz_dialog = None  # the QRZ login dialog while open
        #: Set by the app to no-arg callbacks that switch radio / log.
        self.on_change_radio: Callable[[], None] | None = None
        self.on_new_log: Callable[[], None] | None = None
        self.on_open_log: Callable[[], None] | None = None
        #: Open a specific log by path (a Recent Logs entry).
        self.on_open_log_path: Callable[[str], None] | None = None
        #: Returns recent logs as (path, label) pairs, most-recent first.
        self.recent_logs_provider: Callable[[], list[tuple[str, str]]] | None = None
        #: Set by the app: on_change_theme(name) applies + persists a theme.
        self.on_change_theme: Callable[[str], None] | None = None
        #: Set by the app: on_change_font(family, size) applies + persists a font.
        self.on_change_font: Callable[[str | None, int], None] | None = None
        self._radio_dialog = None  # app keeps the open radio dialog alive here
        self._log_dialog = None  # app keeps the open new/open-log dialog alive here
        self._shortcuts_dialog = None  # the Keyboard Shortcuts dialog while open
        self._about_dialog = None  # the About dialog while open
        self._help_window = None  # the User Guide window while open
        self._autoexport_dialog = None  # the Auto-export settings dialog while open
        # WSJT-X UDP integration (digital modes). The listener is created on
        # demand by set_wsjtx; _wsjtx_active flips the F-key bar -> info panel.
        self._wsjtx_listener: WsjtxListener | None = None
        self._wsjtx_enabled = False
        self._wsjtx_port = 2237
        self._wsjtx_active = False
        self._wsjtx_id = ""  # the reporting WSJT-X instance id (for replies)
        self._wsjtx_highlighted: set[str] = set()  # calls we've already colored
        #: Set by the app: on_change_wsjtx(enabled, port) persists the choice.
        self.on_change_wsjtx: Callable[[bool, int], None] | None = None
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = None  # no loop (e.g. tests) -> log locally, skip broadcast

        # CAT state (managed via set_poller). When a poller is present, band/mode/
        # frequency follow the rig and the manual combos become read-only mirrors.
        self._poller: RadioPoller | None = None
        self._cat = False
        self._radio_freq: int | None = None
        self._radio_mode: Mode | None = None
        self._radio_connected = False

        self.setWindowTitle(f"PartyHams Logger — {session.config.my_call} — {session.contest.name}")
        self.resize(1060, 580)

        # Log columns adapt to the contest (Field Day has no RST exchange).
        self._columns = ["UTC", "Call", "Band", "Mode"]
        if session.contest.exchanges_rst:
            self._columns += ["RST S", "RST R"]
        self._columns += ["Exchange", "Op"]

        # Frequency readout (live from CAT when a radio is connected). Lives in the
        # status bar; created here because building the entry row triggers an early
        # _update_freq_readout (the band combo's default-index change).
        self._freq = QLabel()
        self._freq.setStyleSheet(f"color: {style.ACCENT}; font-weight: 600;")

        self._build_menu()
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(self._build_score_bar())
        layout.addWidget(self._build_entry_row())
        layout.addWidget(self._build_log_table(), stretch=1)
        self._fkey_bar = self._build_fkey_bar()
        layout.addWidget(self._fkey_bar)
        self._wsjtx_panel = WsjtxPanel()
        self._wsjtx_panel.setVisible(False)
        layout.addWidget(self._wsjtx_panel)
        self.setCentralWidget(root)
        self._setup_fkey_shortcuts()

        session.add_listener(self.refresh)
        # Permanent radio indicator on the right of the status bar. Give it room and
        # center the text vertically so the rig description isn't cramped.
        self._radio_status_label = QLabel()
        self._radio_status_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        )
        self._radio_status_label.setMinimumWidth(240)
        # Frequency readout sits just left of the radio indicator (added first so it
        # lands to the left in the status bar's right-aligned permanent area).
        self.statusBar().addPermanentWidget(self._freq)
        self.statusBar().addPermanentWidget(self._radio_status_label)
        self.statusBar().setSizeGripEnabled(False)

        self._build_network_panel()
        self.set_poller(radio_poller)
        self._setup_auto_export()
        self._setup_autocq()
        self._setup_qrz()
        self._call.setFocus()
        self.refresh()

    def _setup_auto_export(self) -> None:
        """Periodically snapshot the log to a timestamped ADIF backup."""
        self._auto_export_timer = QTimer(self)
        self._auto_export_timer.timeout.connect(self._auto_export_adif)
        self._apply_autoexport_timer()

    def _apply_autoexport_timer(self) -> None:
        """(Re)arm or stop the timer from the current auto-export settings."""
        self._auto_export_timer.stop()
        if self._autoexport_enabled:
            minutes = clamp_export_minutes(self._autoexport_minutes)
            self._auto_export_timer.start(minutes * 60 * 1000)

    def set_autoexport(self, enabled: bool, minutes: int, only_if_new: bool) -> None:
        """Apply saved/edited auto-export settings and re-arm the timer."""
        self._autoexport_enabled = enabled
        self._autoexport_minutes = clamp_export_minutes(minutes)
        self._autoexport_only_if_new = only_if_new
        if hasattr(self, "_auto_export_timer"):
            self._apply_autoexport_timer()

    def _setup_autocq(self) -> None:
        """Create (stopped) the timer that repeats F1 while Auto-CQ is on."""
        self._autocq_timer = QTimer(self)
        self._autocq_timer.timeout.connect(self._autocq_tick)

    def set_autocq_interval(self, seconds: int) -> None:
        """Apply a saved/preset interval (clamped). Restarts the timer if live."""
        self._autocq_interval = clamp_autocq_interval(seconds)
        if self._autocq:
            self._start_autocq()  # re-arm at the new interval

    def _set_autocq(self, on: bool) -> None:
        if on:
            self._start_autocq()
        else:
            self._stop_autocq()

    def _start_autocq(self) -> None:
        self._autocq = True
        if hasattr(self, "_autocq_action"):
            self._autocq_action.setChecked(True)
        self._autocq_timer.start(self._autocq_interval * 1000)
        self.statusBar().showMessage(f"Auto-CQ on ({self._autocq_interval}s)", 2000)
        self._fire_macro(1)  # send the first CQ immediately

    def _stop_autocq(self) -> None:
        was_on = self._autocq
        self._autocq = False
        self._autocq_timer.stop()
        if hasattr(self, "_autocq_action"):
            self._autocq_action.setChecked(False)
        if was_on:
            self.statusBar().showMessage("Auto-CQ stopped", 2000)

    def _on_call_typed(self) -> None:
        """Pause Auto-CQ the moment a callsign is being entered."""
        if self._autocq and self._call.text().strip():
            self._stop_autocq()

    def _autocq_tick(self) -> None:
        """Fire F1 if conditions still hold; otherwise stop the repeat."""
        if should_autocq(self._run, self._autocq, self._call.text()):
            self._fire_macro(1)
        else:
            self._stop_autocq()

    # ------------------------------------------------------------------ #
    # QRZ.com callsign lookup (debounced, background)
    # ------------------------------------------------------------------ #
    def _setup_qrz(self) -> None:
        """Create the (stopped) debounce timer that fires a QRZ lookup."""
        self._qrz_timer = QTimer(self)
        self._qrz_timer.setSingleShot(True)
        self._qrz_timer.setInterval(600)  # ms pause before looking up
        self._qrz_timer.timeout.connect(self._qrz_lookup_now)

    def set_qrz_credentials(self, username: str, password: str) -> None:
        """Apply saved/edited QRZ credentials; clears any cached session key."""
        self._qrz.username = username
        self._qrz.password = password
        self._qrz.key = None
        self._qrz_last_call = ""

    def _qrz_enabled(self) -> bool:
        return bool(self._qrz.username and self._qrz.password)

    def _on_call_qrz(self) -> None:
        """Debounce a QRZ lookup on a short pause after the call changes."""
        if not self._qrz_enabled():
            return
        call = self._call.text().strip().upper()
        if not call or call == self._qrz_last_call:
            return
        self._qrz_timer.start()  # (re)start the debounce; fires after the pause

    def _qrz_lookup_now(self) -> None:
        """Kick off a background QRZ lookup for the current callsign."""
        call = self._call.text().strip().upper()
        if not call or not self._qrz_enabled() or call == self._qrz_last_call:
            return
        self._qrz_last_call = call
        if self._loop is None or not self._loop.is_running():
            return  # no loop (tests) -> skip the network call
        self._loop.create_task(self._do_qrz_lookup(call))

    async def _do_qrz_lookup(self, call: str) -> None:
        """Run the (blocking) QRZ lookup off the UI thread and show the result."""
        record = await asyncio.get_event_loop().run_in_executor(
            None, self._qrz.lookup, call
        )
        if call != self._call.text().strip().upper():
            return  # the operator moved on; don't clobber a newer entry
        if record is not None:
            self.statusBar().showMessage(format_record(record), 8000)
        elif self._qrz.last_error:
            self.statusBar().showMessage(self._qrz.last_error, 4000)

    def _auto_export_adif(self) -> None:
        path = getattr(self.session.store, "path", ":memory:")
        qsos = self.session.qsos()
        if path == ":memory:" or not qsos:
            return  # nothing worth backing up (transient or empty log)
        if not should_autoexport(
            self._autoexport_enabled,
            self._autoexport_only_if_new,
            len(qsos),
            self._autoexport_last_count,
        ):
            return  # disabled, or "only if new" and no QSOs added since last export
        try:
            out_dir = Path(path).resolve().parent / "adif-backups"
            out_dir.mkdir(parents=True, exist_ok=True)
            name = timestamped_adif_name(
                self.session.config.my_call, self.session.contest.id, utcnow()
            )
            target = out_dir / name
            target.write_text(self.session.export_adif())
            self._autoexport_last_count = len(qsos)
            self.statusBar().showMessage(f"Auto-exported ADIF → {target.name}", 3000)
        except OSError as exc:  # noqa: BLE001 - a backup failure must never disrupt logging
            self.statusBar().showMessage(f"Auto-export failed: {exc}", 4000)

    def _build_network_panel(self) -> None:
        """Dockable side panel: station roster + chat (toggle via the View menu)."""
        self._panel = NetworkPanel(self.session)
        self._panel.on_send_chat = self._send_chat
        self._panel.on_request_sync = self._request_full_log
        dock = QDockWidget("Network", self)
        dock.setObjectName("networkDock")
        dock.setWidget(self._panel)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        toggle = dock.toggleViewAction()
        toggle.setShortcut(QKeySequence(sc.TOGGLE_NETWORK))
        self._view_menu.addAction(toggle)

        # Backfill persisted/synced history (in send order) before live updates.
        for entry in self.session.chat_messages():
            self._panel.append_chat(entry)
        self.session.add_chat_listener(self._panel.append_chat)
        self.session.add_roster_listener(self._panel.refresh_roster)
        # Rates change with the clock, so refresh the roster on a timer too.
        self._roster_timer = QTimer(self)
        self._roster_timer.setInterval(2000)
        self._roster_timer.timeout.connect(self._panel.refresh_roster)
        self._roster_timer.start()

        # ContestBot: occasionally drop a fun automated message into the chat.
        self._banter_prev: list[StationSnapshot] | None = None
        self._banter_counter = 0
        self._banter_timer = QTimer(self)
        self._banter_timer.setInterval(60_000)  # once a minute
        self._banter_timer.timeout.connect(self._banter_tick)
        self._banter_timer.start()

    def _send_chat(self, to_op: str, text: str) -> None:
        self.session.post_chat(to_op, text)  # local echo via the chat listener
        if self._loop is not None and self._loop.is_running():
            self._loop.create_task(self.session.broadcast_chat(to_op, text))

    def _banter_snapshot(self) -> list[StationSnapshot]:
        """Build a plain-data activity snapshot for the banter engine."""
        now = utcnow()
        snaps = []
        for row in self.session.roster():
            stats = self.session.station_stats(row["station_id"])
            last = stats["last"]
            age = (now - last).total_seconds() / 60.0 if last else None
            snaps.append(
                StationSnapshot(
                    operator=row["operator"] or row["call"],
                    rate_15=row["rates"][15],
                    total=row["total"],
                    last_qso_age_min=age,
                )
            )
        return snaps

    def _banter_tick(self) -> None:
        """Once a minute: maybe post a ContestBot message visible to everyone."""
        snapshot = self._banter_snapshot()
        self._banter_counter += 1
        message = choose_message(snapshot, self._banter_prev, self._banter_counter)
        self._banter_prev = snapshot
        if message:
            self._send_chat("*", message)  # local echo + broadcast to all peers

    def _request_full_log(self) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.create_task(self.session.request_full_log())
            self.statusBar().showMessage("Requested full logs from all stations…", 4000)
        else:
            self.statusBar().showMessage("Not networked — no peers to sync with", 4000)

    # ------------------------------------------------------------------ #
    # F-key macros
    # ------------------------------------------------------------------ #
    def _build_fkey_bar(self) -> QWidget:
        bar = QWidget()
        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(2, 2, 2, 2)
        hbox.setSpacing(3)

        self._runsp_btn = QPushButton()
        self._runsp_btn.setObjectName("fkey")
        self._runsp_btn.setMinimumHeight(46)
        self._runsp_btn.setFixedWidth(64)
        self._runsp_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._runsp_btn.clicked.connect(lambda: self._set_run(not self._run))
        hbox.addWidget(self._runsp_btn)

        self._fkey_buttons: list[QPushButton] = []
        for key in range(1, 13):
            btn = QPushButton()
            btn.setObjectName("fkey")
            btn.setMinimumHeight(46)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keep focus in the call field
            btn.clicked.connect(lambda _checked=False, k=key: self._fire_macro(k))
            self._fkey_buttons.append(btn)
            hbox.addWidget(btn)
        return bar

    def _set_run(self, run: bool) -> None:
        if run == self._run:
            return
        self._run = run
        if not run:
            self._stop_autocq()  # Auto-CQ only makes sense in Run mode
        self._update_fkey_bar()

    def _set_esm(self, on: bool) -> None:
        self._esm = on
        self._esm_sent = False
        self._esm_badge.setVisible(on)
        self._update_fkey_bar()
        self.statusBar().showMessage(f"ESM {'on' if on else 'off'}", 2000)

    def _setup_fkey_shortcuts(self) -> None:
        for key in range(1, 13):
            seq = QKeySequence(getattr(Qt.Key, f"Key_F{key}"))
            shortcut = QShortcut(seq, self)
            shortcut.activated.connect(lambda k=key: self._fire_macro(k))
        # Escape = emergency stop transmitting.
        stop = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        stop.activated.connect(self._stop_tx)

    def _stop_tx(self) -> None:
        self._stop_autocq()  # ESC always halts the Auto-CQ repeat
        radio = self._poller.radio if self._poller is not None else None
        if radio is None or self._loop is None or not self._loop.is_running():
            return
        self._loop.create_task(self._do_stop_tx(radio))

    async def _do_stop_tx(self, radio) -> None:
        try:
            await radio.stop_tx()
            self.statusBar().showMessage("TX stopped", 1500)
        except Exception as exc:  # noqa: BLE001 - emergency stop must never crash
            self.statusBar().showMessage(f"Stop TX failed: {exc}", 3000)

    def _current_group(self) -> str:
        return mode_group_for(self._current_mode()).value

    def _current_bank(self) -> str:
        return bank_key(self._current_group(), self._run)

    def _update_fkey_bar(self) -> None:
        bank = self._current_bank()
        self._runsp_btn.setText("RUN" if self._run else "S&&P")
        # RUN stands out in amber; S&P uses the on-accent color for contrast.
        runsp_color = style.AMBER if self._run else style.ON_ACCENT
        self._runsp_btn.setStyleSheet(
            f"QPushButton#fkey {{ color: {runsp_color}; font-weight: 700; }}"
        )
        next_key = self._esm_next_key()
        for key, btn in enumerate(self._fkey_buttons, start=1):
            macro = self._macros.get(bank, key)
            label = macro.label if macro else ""
            btn.setText(f"F{key}\n{label}" if label else f"F{key}")
            btn.setEnabled(bool(macro and macro.content.strip()))
            # Highlight the key Enter would send next under ESM.
            if key == next_key:
                btn.setStyleSheet(f"QPushButton#fkey {{ border: 2px solid {style.MULT}; }}")
            else:
                btn.setStyleSheet("")

    def _macro_context(self) -> dict[str, str]:
        sent = self.session.config.sent_exchange
        ctx = {
            "MYCALL": self.session.config.my_call,
            "CALL": self._call.text().strip().upper(),
            "EXCH": " ".join(v for v in sent.values() if v),
            "OP": self.session.engine.operator,
            "RST": default_rst(self._current_mode()),
        }
        for name, value in sent.items():
            ctx[name.upper()] = value
        return ctx

    def _fire_macro(self, key: int) -> None:
        if key == 1:
            self._set_run(True)  # CQ implies Run mode
        group = self._current_group()
        macro = self._macros.get(self._current_bank(), key)
        if macro is None or not macro.content.strip():
            return
        if group == "DIGITAL":
            self.statusBar().showMessage("Digital macros not supported yet", 3000)
            return
        if group == "PHONE":
            self._play_wav(macro.content, tx_desc=(key, macro.label, Path(macro.content).name))
            return
        # CW / text
        text, actions = expand(macro.content, self._macro_context())
        if text:
            self._send_cw(text, tx_desc=(key, macro.label, text))
        for action in actions:
            if action == "log":
                self._try_log()
            elif action == "wipe":
                self._wipe_entry()

    # --- ESM (Enter sends messages) ---
    def _exchange_complete(self) -> bool:
        if not self._call.text().strip():
            return False
        parsed = {n: e.text().strip().upper() for n, e in self._exchange_edits.items()}
        return not self.session.validate_exchange(parsed)

    def _esm_next_key(self) -> int | None:
        if not self._esm:
            return None
        step = esm_step(
            self._run,
            bool(self._call.text().strip()),
            self._esm_sent,
            self._exchange_complete(),
        )
        return step.key

    def _on_enter(self) -> None:
        if self._esm:
            self._esm_advance()
        else:
            self._advance_or_log()

    def _esm_advance(self) -> None:
        step = esm_step(
            self._run,
            bool(self._call.text().strip()),
            self._esm_sent,
            self._exchange_complete(),
        )
        if step.key is None:
            self._call.setFocus()
            return
        if step.set_sent:
            self._esm_sent = True
        self._fire_macro(step.key)
        if step.log:
            self._try_log()
        if step.focus_exchange:
            self._focus_first_empty_exchange()
        if step.reset:
            self._esm_sent = False
        self._update_fkey_bar()

    def _focus_first_empty_exchange(self) -> None:
        for field in self.session.contest.exchange_fields():
            edit = self._exchange_edits[field.name]
            if not edit.text().strip():
                edit.setFocus()
                return
        self._call.setFocus()

    def _send_cw(self, text: str, tx_desc: tuple[int, str, str] | None = None) -> None:
        radio = self._poller.radio if self._poller is not None else None
        if radio is None or not radio.supports(Capability.SEND_CW):
            self.statusBar().showMessage("No CW keyer — configure a radio", 3000)
            return
        if tx_desc is not None:
            self._show_tx_status("TRANSMITTING", tx_desc, timeout=0)
        if self._loop is not None and self._loop.is_running():
            self._loop.create_task(self._do_send_cw(radio, text, tx_desc))

    async def _do_send_cw(
        self, radio, text: str, tx_desc: tuple[int, str, str] | None = None
    ) -> None:
        try:
            await radio.send_cw(text, wpm=self._macros.cw_wpm)
            if tx_desc is not None:
                self._show_tx_status("SENT", tx_desc, timeout=5000)
            else:
                self.statusBar().showMessage(f"CW: {text}", 2500)
        except Exception as exc:  # noqa: BLE001 - surface keyer errors, don't crash
            self.statusBar().showMessage(f"CW failed: {exc}", 4000)

    def _show_tx_status(self, word: str, tx_desc: tuple[int, str, str], timeout: int) -> None:
        """Left-of-status indicator: ``TRANSMITTING — F1 — CQ — CQ FD W7ABC``."""
        self.statusBar().showMessage(_format_tx_status(word, *tx_desc), timeout)

    def _play_wav(self, path: str, tx_desc: tuple[int, str, str] | None = None) -> None:
        if not path:
            self.statusBar().showMessage("No audio assigned to that key", 2500)
            return
        if not Path(path).exists():
            self.statusBar().showMessage(f"Audio file not found: {path}", 4000)
            return
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect
        except ImportError:
            self.statusBar().showMessage("Audio unavailable (QtMultimedia missing)", 4000)
            return
        self._sound = QSoundEffect(self)
        self._sound.setSource(QUrl.fromLocalFile(path))
        if tx_desc is not None:
            self._show_tx_status("TRANSMITTING", tx_desc, timeout=0)
            # Flip to SENT once playback stops.
            self._sound.playingChanged.connect(lambda: self._on_wav_playing_changed(tx_desc))
        self._sound.play()

    def _on_wav_playing_changed(self, tx_desc: tuple[int, str, str]) -> None:
        if self._sound is not None and not self._sound.isPlaying():
            self._show_tx_status("SENT", tx_desc, timeout=5000)

    def _wipe_entry(self) -> None:
        self._call.clear()
        for edit in self._exchange_edits.values():
            edit.clear()
        self._call.setFocus()

    def _edit_macros(self) -> None:
        dialog = MacrosDialog(self._macros, self.session.contest, parent=self)
        self._macros_dialog = dialog  # keep alive while open
        dialog.finished.connect(lambda result: self._on_macros_done(dialog, result))
        dialog.open()

    def _on_macros_done(self, dialog: MacrosDialog, result: int) -> None:
        self._macros_dialog = None
        if result == QDialog.DialogCode.Accepted.value:
            self._macros = dialog.result_macroset()
            save_macros(self.session.contest.id, self._macros)
            self._update_fkey_bar()

    def _build_menu(self) -> None:
        logs_menu = self.menuBar().addMenu("Logs")
        new = logs_menu.addAction("New Log…", lambda: self.on_new_log and self.on_new_log())
        new.setShortcut(QKeySequence(sc.NEW_LOG))
        open_log = logs_menu.addAction("Open Log…", lambda: self.on_open_log and self.on_open_log())
        open_log.setShortcut(QKeySequence(sc.OPEN_LOG))
        self._recent_menu = logs_menu.addMenu("Open Recent")
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        logs_menu.addSeparator()
        adif = logs_menu.addAction("Export ADIF…", self._export_adif)
        adif.setShortcut(QKeySequence(sc.EXPORT_ADIF))
        cabrillo = logs_menu.addAction("Export Cabrillo…", self._export_cabrillo)
        cabrillo.setShortcut(QKeySequence(sc.EXPORT_CABRILLO))
        logs_menu.addAction("Auto-export…", self._edit_autoexport)

        radio_menu = self.menuBar().addMenu("Radio")
        select_radio = radio_menu.addAction("Select Radio…", self._radio_menu_clicked)
        select_radio.setShortcut(QKeySequence(sc.SELECT_RADIO))
        select_radio.setStatusTip(
            "Choose how to read the rig (Hamlib, FlexRadio, Icom CI-V/LAN) or stay manual"
        )

        self._build_wsjtx_menu()

        macros_menu = self.menuBar().addMenu("Macros")
        edit_macros = macros_menu.addAction("Edit Macros…", self._edit_macros)
        edit_macros.setShortcut(QKeySequence(sc.EDIT_MACROS))
        esm_action = macros_menu.addAction("ESM — Enter sends messages")
        esm_action.setCheckable(True)
        esm_action.setShortcut(QKeySequence(sc.TOGGLE_ESM))
        esm_action.toggled.connect(self._set_esm)
        self._build_autocq_menu(macros_menu)

        # The dock toggle is added to this menu later by _build_network_panel.
        self._view_menu = self.menuBar().addMenu("View")
        sections = self._view_menu.addAction("Sections Worked…", self._open_sections)
        sections.setShortcut(QKeySequence(sc.SECTIONS))
        sections.setStatusTip("Live multiplier grid and schematic section map")
        cluster = self._view_menu.addAction("DX Cluster…", self._open_cluster)
        cluster.setStatusTip("Connect to a DX cluster and QSY the rig to spots")
        self._build_theme_menu(self._view_menu)
        font = self._view_menu.addAction("Font…", self._choose_font)
        font.setStatusTip("Set the app-wide base font family and size")

        tools_menu = self.menuBar().addMenu("Tools")
        tools_menu.addAction("QRZ Login…", self._edit_qrz)
        tools_menu.addSeparator()
        ref_menu = tools_menu.addMenu("Reference Data")
        ref_menu.addAction("Import Super Check Partial…", self._import_scp)
        ref_menu.addAction("Import city.dat…", self._import_city)
        ref_menu.addSeparator()
        ref_menu.addAction("Import LoTW users…", self._import_lotw)
        ref_menu.addAction("Import eQSL users…", self._import_eqsl)
        ref_menu.addAction("Import QRZ users…", self._import_qrz)

        help_menu = self.menuBar().addMenu("Help")
        guide = help_menu.addAction("User Guide…", self._show_help)
        guide.setStatusTip("Open the illustrated user guide for every screen")
        shortcuts = help_menu.addAction("Keyboard Shortcuts…", self._show_shortcuts)
        shortcuts.setShortcut(QKeySequence(sc.SHORTCUTS))
        shortcuts.setStatusTip("Show the full keyboard-shortcut reference")
        help_menu.addSeparator()
        about = help_menu.addAction("About PartyHams Logger…", self._show_about)
        about.setStatusTip("Version, credits, and the project link")

    def _build_autocq_menu(self, macros_menu) -> None:
        macros_menu.addSeparator()
        self._autocq_action = macros_menu.addAction("Auto-CQ (repeat F1)")
        self._autocq_action.setCheckable(True)
        self._autocq_action.toggled.connect(self._set_autocq)
        interval_menu = macros_menu.addMenu("Auto-CQ Interval")
        self._autocq_group = QActionGroup(self)
        self._autocq_group.setExclusive(True)
        for secs in AUTOCQ_INTERVALS:
            action = interval_menu.addAction(f"{secs}s")
            action.setCheckable(True)
            action.setChecked(secs == self._autocq_interval)
            self._autocq_group.addAction(action)
            action.triggered.connect(lambda _checked=False, s=secs: self._choose_autocq_interval(s))

    def _choose_autocq_interval(self, seconds: int) -> None:
        self.set_autocq_interval(seconds)
        if self.on_autocq_interval is not None:
            self.on_autocq_interval(self._autocq_interval)  # app persists it
        self.statusBar().showMessage(f"Auto-CQ interval {self._autocq_interval}s", 2000)

    def _build_wsjtx_menu(self) -> None:
        """The WSJT-X menu: toggle the UDP listener and set its port."""
        menu = self.menuBar().addMenu("WSJT-X")
        self._wsjtx_action = menu.addAction("Enable WSJT-X (UDP)")
        self._wsjtx_action.setCheckable(True)
        self._wsjtx_action.toggled.connect(self._toggle_wsjtx)
        menu.addAction("Set UDP Port…", self._choose_wsjtx_port)

    def _toggle_wsjtx(self, enabled: bool) -> None:
        """Enable/disable the listener (menu handler) and persist the choice."""
        self.set_wsjtx(enabled, self._wsjtx_port)
        if self.on_change_wsjtx is not None:
            self.on_change_wsjtx(self._wsjtx_enabled, self._wsjtx_port)

    def _choose_wsjtx_port(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        port, ok = QInputDialog.getInt(
            self, "WSJT-X UDP Port", "Port:", self._wsjtx_port, 1, 65535
        )
        if not ok:
            return
        self.set_wsjtx(self._wsjtx_enabled, port)
        if self.on_change_wsjtx is not None:
            self.on_change_wsjtx(self._wsjtx_enabled, self._wsjtx_port)

    def set_wsjtx(self, enabled: bool, port: int) -> None:
        """Apply WSJT-X settings: (re)start or stop the UDP listener.

        Idempotent and safe without a running loop (tests): when there's no
        asyncio loop the settings are stored but no socket is opened.
        """
        self._wsjtx_port = int(port)
        self._wsjtx_enabled = bool(enabled)
        if hasattr(self, "_wsjtx_action"):
            self._wsjtx_action.setChecked(self._wsjtx_enabled)
        if self._loop is None or not self._loop.is_running():
            return  # headless/tests — nothing to bind
        self._loop.create_task(self._restart_wsjtx())

    async def stop_wsjtx(self) -> None:
        """Stop the UDP listener (called during window teardown)."""
        if self._wsjtx_listener is not None:
            await self._wsjtx_listener.stop()
            self._wsjtx_listener = None

    async def _restart_wsjtx(self) -> None:
        """Tear down any existing listener and start a fresh one if enabled."""
        if self._wsjtx_listener is not None:
            await self._wsjtx_listener.stop()
            self._wsjtx_listener = None
        if not self._wsjtx_enabled:
            self._set_wsjtx_active(False)
            return
        listener = WsjtxListener(
            port=self._wsjtx_port,
            on_qso_logged=self._on_wsjtx_qso,
            on_status=self._on_wsjtx_status,
            on_decode=self._on_wsjtx_decode,
        )
        try:
            await listener.start()
        except OSError as exc:
            self.statusBar().showMessage(f"WSJT-X listen failed: {exc}", 5000)
            return
        self._wsjtx_listener = listener
        self.statusBar().showMessage(f"WSJT-X UDP listening on :{self._wsjtx_port}", 3000)

    # --- WSJT-X message handlers (called from the asyncio thread) ---
    def _on_wsjtx_qso(self, msg: QSOLogged) -> None:
        """Log a WSJT-X-reported QSO into our log (dedup handled by the engine)."""
        kwargs = qso_logged_to_record(msg)
        if not kwargs["call"]:
            return
        try:
            qso = self.session.record_qso(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - never let a peer packet crash us
            self.statusBar().showMessage(f"WSJT-X log error: {exc}", 4000)
            return
        self._broadcast(qso)
        # If WSJT-X reported the transmit power, share it so peers see our power.
        power_w = parse_tx_power(msg.tx_power)
        if power_w is not None:
            self.session.set_local_status(qso.freq_hz, qso.mode, power_w=power_w)
        self.statusBar().showMessage(f"WSJT-X logged {kwargs['call']}", 3000)

    def _on_wsjtx_status(self, status: Status) -> None:
        """Track WSJT-X transmit state; flip to the info panel for data modes."""
        self._wsjtx_id = status.id
        group = mode_group_for(self._map_status_mode(status.mode))
        active = group.value == "DIGITAL"
        self._set_wsjtx_active(active)
        if not active:
            return
        sending = status.tx_mode or status.mode
        if status.dx_call:
            sending = f"{status.dx_call} ({sending})"
        self._wsjtx_panel.set_status(
            mode=status.mode,
            dial_freq=status.dial_freq,
            tx_enabled=status.tx_enabled,
            transmitting=status.transmitting,
            tx_period_odd=status.tx_period_odd,
            sending=sending if status.transmitting else "",
        )
        # Broadcast which FT8/FT4 sequence we transmit on so peers see odd/even.
        # Prefer WSJT-X's explicit tx_period_odd; otherwise derive from the clock.
        if status.tx_period_odd is not None:
            ft_tx_even = 0 if status.tx_period_odd else 1
        else:
            ft_tx_even = tx_even_from_epoch(utcnow().timestamp(), status.mode)
        self.session.set_local_status(
            status.dial_freq, self._map_status_mode(status.mode), ft_tx_even=ft_tx_even
        )

    def _on_wsjtx_decode(self, decode: Decode) -> None:
        """Show a decode line and highlight calls whose section we still need."""
        if self._wsjtx_active:
            snr = f"{decode.snr:+d}" if isinstance(decode.snr, int) else str(decode.snr)
            self._wsjtx_panel.add_decode(f"{snr:>4} dB  {decode.message}")
        self._maybe_highlight(decode)

    @staticmethod
    def _map_status_mode(mode: str) -> Mode:
        return map_mode(mode)

    def _set_wsjtx_active(self, active: bool) -> None:
        """Swap the F-key bar for the WSJT-X panel (or back) when state changes."""
        if active == self._wsjtx_active:
            return
        self._wsjtx_active = active
        self._fkey_bar.setVisible(not active)
        self._wsjtx_panel.setVisible(active)
        if not active:
            self._wsjtx_panel.clear_decodes()

    def _maybe_highlight(self, decode: Decode) -> None:
        """Best-effort: tell WSJT-X to color CQ candidates whose section we need.

        Parses the calling station from a ``CQ ...`` decode and, if its section
        is still unworked on this band/mode, sends a HighlightCallsign reply.
        Sections aren't carried in FT8 decodes, so this colors *every* fresh CQ
        candidate while we still have unworked sections — a prompt to call them.
        """
        listener = self._wsjtx_listener
        if listener is None or not decode.message.upper().startswith("CQ"):
            return
        call = self._cq_call(decode.message)
        if not call or call in self._wsjtx_highlighted:
            return
        if not self._have_unworked_sections():
            return
        listener.send_highlight(
            self._wsjtx_id,
            call,
            background=(40, 90, 40, 255),  # green wash = "go work this one"
            foreground=(255, 255, 255, 255),
        )
        self._wsjtx_highlighted.add(call)

    @staticmethod
    def _cq_call(message: str) -> str:
        """Extract the calling station from a ``CQ [DX/dir] CALL [GRID]`` decode."""
        tokens = message.split()
        if not tokens or tokens[0].upper() != "CQ":
            return ""
        # Skip optional CQ qualifiers (e.g. "CQ DX", "CQ NA", "CQ TEST").
        idx = 1
        if idx < len(tokens) and len(tokens[idx]) <= 3 and tokens[idx].isalpha():
            idx += 1
        return tokens[idx].upper() if idx < len(tokens) else ""

    def _have_unworked_sections(self) -> bool:
        """True if at least one section's slot is still unworked (best-effort)."""
        worked = self.session.section_status()
        from partyhams.contest.sections import ARRL_SECTIONS

        return len(worked) < len(ARRL_SECTIONS)

    def _build_theme_menu(self, view_menu) -> None:
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("Theme")
        group = QActionGroup(self)
        group.setExclusive(True)
        last_dark = True
        for name, dark in style.theme_names():
            if dark != last_dark:
                theme_menu.addSeparator()  # divide dark from light themes
                last_dark = dark
            action = theme_menu.addAction(name)
            action.setCheckable(True)
            action.setStatusTip(f"Apply the {name} color theme (applies instantly)")
            action.setChecked(name == style.active_name())
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, n=name: self._change_theme(n))

    def _change_theme(self, name: str) -> None:
        if self.on_change_theme is not None:
            self.on_change_theme(name)  # app applies, persists, and restyles
        else:
            from PySide6.QtWidgets import QApplication

            style.apply_theme(QApplication.instance(), name)
            self.restyle()

    def _choose_font(self) -> None:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QFontDialog

        family, size = style.active_font()
        current = QFont(family, size) if family else QFont()
        current.setPointSize(size)
        font, ok = QFontDialog.getFont(current, self, "Choose Font")
        if not ok:
            return
        if self.on_change_font is not None:
            self.on_change_font(font.family(), font.pointSize())  # app applies + persists
        else:
            from PySide6.QtWidgets import QApplication

            style.apply_font(QApplication.instance(), font.family(), font.pointSize())
            self.restyle()

    def restyle(self) -> None:
        """Re-apply palette-derived inline styles after a live theme change."""
        # The shared dupe/mult badge is re-styled (palette-aware) by refresh() below.
        self._freq.setStyleSheet(f"color: {style.ACCENT}; font-weight: 600;")
        self._update_fkey_bar()
        self._update_radio_label()
        self._panel.restyle()
        self.refresh()  # rebuilds the score bar and CAT-aware indicators

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        entries = self.recent_logs_provider() if self.recent_logs_provider else []
        if not entries:
            self._recent_menu.addAction("(no recent logs)").setEnabled(False)
            return
        for path, label in entries:
            self._recent_menu.addAction(
                label,
                lambda checked=False, p=path: self.on_open_log_path and self.on_open_log_path(p),
            )

    def _show_shortcuts(self) -> None:
        dialog = ShortcutsDialog(parent=self)
        self._shortcuts_dialog = dialog  # keep alive while open
        dialog.finished.connect(lambda _result: setattr(self, "_shortcuts_dialog", None))
        dialog.open()

    def _show_about(self) -> None:
        dialog = AboutDialog(parent=self)
        self._about_dialog = dialog  # keep alive while open
        dialog.finished.connect(lambda _result: setattr(self, "_about_dialog", None))
        dialog.open()

    def _show_help(self) -> None:
        if self._help_window is None:
            self._help_window = HelpWindow()  # keep the ref alive like the others
        self._help_window.show()
        self._help_window.raise_()
        self._help_window.activateWindow()

    def _open_sections(self) -> None:
        if self._sections_window is None:
            self._sections_window = SectionsWindow(self.session)
        self._sections_window.show()
        self._sections_window.raise_()
        self._sections_window.activateWindow()

    def _open_cluster(self) -> None:
        if self._cluster_window is None:
            self._cluster_window = ClusterWindow(
                poller=self._poller,
                login_call=self.session.config.my_call,
                loop=self._loop,
            )
        self._cluster_window.set_poller(self._poller)
        self._cluster_window.show()
        self._cluster_window.raise_()
        self._cluster_window.activateWindow()

    # ------------------------------------------------------------------ #
    # reference data imports (Tools → Reference Data)
    # ------------------------------------------------------------------ #
    def _pick_refdata_file(self, title: str) -> str | None:
        """Prompt for a reference file and return its text, or None if cancelled."""
        path, _ = QFileDialog.getOpenFileName(
            self, title, "", "Reference data (*.txt *.dat *.scp *.csv);;All files (*)"
        )
        if not path:
            return None
        try:
            return Path(path).read_text(errors="ignore")
        except OSError as exc:
            self.statusBar().showMessage(f"Could not read {Path(path).name}: {exc}", 4000)
            return None

    def _import_scp(self) -> None:
        text = self._pick_refdata_file("Import Super Check Partial")
        if text is not None:
            count = self._refdata.import_scp(text)
            self.statusBar().showMessage(f"Loaded {count} super-check-partial calls", 4000)

    def _import_city(self) -> None:
        text = self._pick_refdata_file("Import city.dat")
        if text is not None:
            count = self._refdata.import_city_dat(text)
            self.statusBar().showMessage(f"Loaded {count} city.dat records", 4000)

    def _import_lotw(self) -> None:
        text = self._pick_refdata_file("Import LoTW users")
        if text is not None:
            count = self._refdata.import_lotw(text)
            self.statusBar().showMessage(f"Loaded {count} LoTW users", 4000)

    def _import_eqsl(self) -> None:
        text = self._pick_refdata_file("Import eQSL users")
        if text is not None:
            count = self._refdata.import_eqsl(text)
            self.statusBar().showMessage(f"Loaded {count} eQSL users", 4000)

    def _import_qrz(self) -> None:
        text = self._pick_refdata_file("Import QRZ users")
        if text is not None:
            count = self._refdata.import_qrz(text)
            self.statusBar().showMessage(f"Loaded {count} QRZ users", 4000)

    def _radio_menu_clicked(self) -> None:
        if self.on_change_radio is not None:
            self.on_change_radio()

    def set_poller(self, poller: RadioPoller | None) -> None:
        """Attach (or detach) a radio poller and rewire CAT state live."""
        self._poller = poller
        self._cat = poller is not None
        self._radio_freq = None
        self._radio_mode = None
        self._radio_connected = poller.connected if poller is not None else False
        self._band.setEnabled(not self._cat)
        self._mode.setEnabled(not self._cat)
        if poller is not None:
            poller.on_state = self._on_radio_state
            poller.on_status = self._on_radio_status
            if poller.state is not None:
                self._apply_radio_state(poller.state)
        if self._cluster_window is not None:
            self._cluster_window.set_poller(poller)
        self._refresh_indicators()
        self._update_radio_label()

    def _update_radio_label(self) -> None:
        if self._poller is None:
            self._radio_status_label.setText("📻 No radio (manual)")
            self._radio_status_label.setStyleSheet(f"color: {style.TEXT_DIM};")
            return
        desc = self._poller.radio.description()
        if self._radio_connected:
            self._radio_status_label.setText(f"📻 {desc}")
            self._radio_status_label.setStyleSheet(f"color: {style.MULT};")
        else:
            self._radio_status_label.setText(f"📻 {desc} · disconnected")
            self._radio_status_label.setStyleSheet(f"color: {style.AMBER};")

    def closeEvent(self, event: QCloseEvent) -> None:
        # Hand control back to the app loop for graceful async shutdown.
        if self._on_close is not None:
            self._on_close()
        event.accept()

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    def _build_score_bar(self) -> QLabel:
        self._score_label = QLabel()
        self._score_label.setObjectName("scoreBar")  # themed in ui/style.py
        self._score_label.setTextFormat(Qt.TextFormat.RichText)
        return self._score_label

    def _build_entry_row(self) -> QWidget:
        row = QWidget()
        hbox = QHBoxLayout(row)

        self._call = QLineEdit()
        self._call.setPlaceholderText("Call")
        self._call.setToolTip(_CALL_TOOLTIP)
        self._call.setMinimumWidth(110)
        self._call.setMaximumWidth(160)
        make_upper(self._call)
        self._call.textChanged.connect(lambda *_: self._refresh_indicators())
        self._call.textChanged.connect(self._on_call_typed)
        self._call.textChanged.connect(lambda *_: self._on_call_qrz())
        self._call.returnPressed.connect(self._on_enter)
        hbox.addWidget(QLabel("Call"))
        hbox.addWidget(self._call)

        # Exchange fields, generated from the contest definition.
        self._exchange_edits: dict[str, QLineEdit] = {}
        for field in self.session.contest.exchange_fields():
            edit = QLineEdit()
            edit.setMinimumWidth(72)
            edit.setMaximumWidth(100)
            edit.setPlaceholderText(field.label)
            make_upper(edit)
            edit.returnPressed.connect(self._on_enter)
            edit.textChanged.connect(lambda *_: self._refresh_indicators())
            self._exchange_edits[field.name] = edit
            hbox.addWidget(QLabel(field.label))
            hbox.addWidget(edit)

        # Band + mode (no CAT yet — chosen manually; auto-fill comes next).
        self._band = QComboBox()
        for band in self._sorted_bands():
            self._band.addItem(band.label, band)
        default_band = self._band.findText("20m")  # busiest FD band
        if default_band >= 0:
            self._band.setCurrentIndex(default_band)
        self._band.currentIndexChanged.connect(lambda *_: self._refresh_indicators())
        hbox.addWidget(QLabel("Band"))
        hbox.addWidget(self._band)

        self._mode = QComboBox()
        for mode in _ENTRY_MODES:
            self._mode.addItem(mode.value, mode)
        self._mode.currentIndexChanged.connect(lambda *_: self._refresh_indicators())
        hbox.addWidget(QLabel("Mode"))
        hbox.addWidget(self._mode)

        log_btn = QPushButton("Log (Enter)")
        log_btn.clicked.connect(self._try_log)
        hbox.addWidget(log_btn)

        # ESM indicator — visible only while ESM (Enter sends messages) is on.
        self._esm_badge = QLabel("ESM")
        self._esm_badge.setObjectName("esmBadge")
        self._esm_badge.setVisible(self._esm)
        hbox.addWidget(self._esm_badge)

        # One status badge, shared by the dupe (red) and new-multiplier (green)
        # indicators — only one applies at a time, so they occupy the same space and
        # just swap text + color. Min width so toggling never squishes the fields.
        self._status_badge = QLabel()
        self._status_badge.setMinimumWidth(220)
        hbox.addWidget(self._status_badge)

        hbox.addStretch(1)
        return row

    def _build_log_table(self) -> QTableWidget:
        self._table = QTableWidget(0, len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        return self._table

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _sorted_bands(self) -> list[Band]:
        bands = [band_by_label(lbl) for lbl in self.session.allowed_bands()]
        bands = [b for b in bands if b is not None]
        bands.sort(key=lambda b: b.low_hz)
        return bands

    def _current_band(self) -> Band:
        return self._band.currentData()

    def _current_freq(self) -> int:
        if self._cat and self._radio_freq is not None:
            return self._radio_freq
        band = self._current_band()
        return (band.low_hz + band.high_hz) // 2

    def _current_mode(self) -> Mode:
        if self._cat and self._radio_mode is not None:
            return self._radio_mode
        return self._mode.currentData()

    # ------------------------------------------------------------------ #
    # CAT (radio) integration
    # ------------------------------------------------------------------ #
    def _on_radio_state(self, state: RadioState) -> None:
        self._apply_radio_state(state)

    def _on_radio_status(self, connected: bool, error: str | None) -> None:
        self._radio_connected = connected
        if not connected:
            self.statusBar().showMessage(
                f"Radio disconnected{f' ({error})' if error else ''}", 3000
            )
        self._update_freq_readout()
        self._update_radio_label()

    def _apply_radio_state(self, state: RadioState) -> None:
        self._radio_freq = state.freq_hz
        self._radio_mode = state.mode
        # Mirror onto the (disabled) combos for a familiar display.
        band = band_for_freq(state.freq_hz)
        if band is not None:
            idx = self._band.findText(band.label)
            if idx >= 0:
                self._band.setCurrentIndex(idx)
        mode_idx = self._mode.findData(state.mode)
        if mode_idx >= 0:
            self._mode.setCurrentIndex(mode_idx)
        self._refresh_indicators()  # updates dupe/mult badges + the freq readout
        self._update_radio_label()  # model/nickname may have just arrived

    def _update_freq_readout(self) -> None:
        freq = self._current_freq()
        mhz, khz, hz = freq // 1_000_000, (freq // 1000) % 1000, (freq % 1000) // 10
        band = band_for_freq(freq)
        text = f"{mhz}.{khz:03d}.{hz:02d}  {band.label if band else '?'}"
        if self._cat:
            if self._radio_connected:
                self._freq.setText(f"📻 {text}")
                self._freq.setStyleSheet(f"color: {style.ACCENT}; font-weight: 600;")
            else:
                self._freq.setText("📻 no radio")
                self._freq.setStyleSheet(f"color: {style.AMBER}; font-weight: 600;")
        else:
            self._freq.setText(text)
            self._freq.setStyleSheet(f"color: {style.TEXT_DIM};")

    # ------------------------------------------------------------------ #
    # entry behavior
    # ------------------------------------------------------------------ #
    def _badge_style(self, color: str) -> str:
        """Inline style for the shared status badge: bold colored text on a tinted,
        bordered backing (red for dupes, green for new multipliers)."""
        return (
            f"font-weight: bold; color: {color}; "
            f"border: 1px solid {color}; border-radius: 3px; padding: 2px 6px;"
        )

    def _refresh_indicators(self) -> None:
        """Update the shared dupe/new-multiplier badge and tint mult exchange fields."""
        call = self._call.text().strip().upper()
        if not call:
            self._esm_sent = False  # new QSO starts unsent
        freq, mode = self._current_freq(), self._current_mode()
        dupe_msg = self.session.dupe_label(call, freq, mode) if call else ""
        is_dupe = bool(dupe_msg)

        exchange = {name: e.text().strip().upper() for name, e in self._exchange_edits.items()}
        new = self.session.new_mults(call, freq, mode, exchange) if call and not is_dupe else set()
        new_types = {mtype for mtype, _ in new}

        # Dupe (red) wins over a new multiplier (green); they share one badge.
        if is_dupe:
            self._status_badge.setText(dupe_msg)
            self._status_badge.setStyleSheet(self._badge_style(style.DUPE))
        elif new:
            self._status_badge.setText("★ NEW " + "/".join(sorted(t.upper() for t in new_types)))
            self._status_badge.setStyleSheet(self._badge_style(style.MULT))
        else:
            self._status_badge.setText("")
            self._status_badge.setStyleSheet("")
        # Tint the exchange field(s) that carry a new multiplier.
        for field in self.session.contest.exchange_fields():
            edit = self._exchange_edits[field.name]
            if field.name in new_types and edit.text().strip():
                edit.setStyleSheet(
                    f"border: 1px solid {style.MULT}; background-color: {style.MULT_BG};"
                )
            else:
                edit.setStyleSheet("")

        self._update_call_hint(call)
        self._update_freq_readout()
        self._update_fkey_bar()  # F-key labels follow the mode (CW vs phone)
        # Let peers see what band/mode we're on (broadcast by the presence loop).
        self.session.set_local_status(freq, mode)

    def _update_call_hint(self, call: str) -> None:
        """Tooltip on the call field: SCP partial matches + known-user flags.

        Non-intrusive — only shown when reference data is loaded and matches. SCP
        suggestions also draw from the operator's already-worked calls.
        """
        if not call:
            self._call.setToolTip(_CALL_TOOLTIP)
            return
        lines: list[str] = []
        worked = self.session.partial_matches(call)
        scp = self._refdata.is_scp_match(call)
        suggestions = sorted({*worked, *scp})[:12]
        if suggestions:
            lines.append("Matches: " + "  ".join(suggestions))
        flags = []
        if self._refdata.uses_lotw(call):
            flags.append("LoTW")
        if self._refdata.uses_eqsl(call):
            flags.append("eQSL")
        if self._refdata.qrz_known(call):
            flags.append("QRZ")
        if flags:
            lines.append("Known to: " + ", ".join(flags))
        qth = self._refdata.city_lookup(call)
        if qth:
            parts = [qth.get("name"), qth.get("state"), qth.get("section")]
            label = ", ".join(p for p in parts if p)
            if label:
                lines.append("QTH: " + label)
        self._call.setToolTip("\n".join(lines))

    def _advance_or_log(self) -> None:
        if not self._call.text().strip():
            self._call.setFocus()
            return
        for field in self.session.contest.exchange_fields():
            edit = self._exchange_edits[field.name]
            if field.required and not edit.text().strip():
                edit.setFocus()
                return
        self._try_log()

    def _try_log(self) -> None:
        call = self._call.text().strip().upper()
        if not call:
            self._flash(self._call)
            self._call.setFocus()
            self.statusBar().showMessage("Enter a callsign to log", 3000)
            return
        parsed = {name: e.text().strip().upper() for name, e in self._exchange_edits.items()}
        errors = self.session.validate_exchange(parsed)
        if errors:
            # Make the failure obvious: flash the first bad field and focus it.
            self._highlight_invalid(parsed)
            self.statusBar().showMessage("Not logged — " + " • ".join(errors), 5000)
            return

        # Record locally and synchronously so the log updates instantly, then
        # broadcast to peers as a best-effort side effect (offline = no-op).
        qso = self.session.record_qso(
            call=call, freq_hz=self._current_freq(), mode=self._current_mode(), exchange=parsed
        )
        self._broadcast(qso)

        self._call.clear()
        for edit in self._exchange_edits.values():
            edit.clear()
        self._call.setFocus()
        self.statusBar().showMessage(f"Logged {call}", 2500)

    def _broadcast(self, qso) -> None:
        """Fire-and-forget network broadcast; the QSO is already logged locally."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return  # no running loop (offline/tests) -> local log is enough
        try:
            loop.create_task(self.session.broadcast(qso))
        except Exception as exc:  # noqa: BLE001 - never block logging on the network
            self.statusBar().showMessage(f"Logged (broadcast deferred: {exc})", 3000)

    def _highlight_invalid(self, parsed: dict[str, str]) -> None:
        focused = False
        for field in self.session.contest.exchange_fields():
            value = parsed.get(field.name, "")
            ok = bool(value) and (field.validator is None or field.validator(value))
            if (field.required and not value) or not ok:
                edit = self._exchange_edits[field.name]
                self._flash(edit)
                if not focused:
                    edit.setFocus()
                    focused = True

    def _flash(self, widget: QLineEdit) -> None:
        """Briefly outline a field in red to signal a problem."""
        widget.setStyleSheet(f"border: 1px solid {style.DUPE}; background-color: #3a2326;")
        QTimer.singleShot(900, lambda: widget.setStyleSheet(""))

    # ------------------------------------------------------------------ #
    # refresh (fired by the session on any log change)
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        self._update_score_bar()
        self._refresh_indicators()
        self._reload_table()

    def _update_score_bar(self) -> None:
        s = self.session.score()
        mult = s.breakdown.get("power_multiplier", 1)
        peers = len(self.session.peers)
        peer_txt = (
            f" &nbsp;|&nbsp; Peers <b style='color:{style.PEER}'>{peers}</b>" if peers else ""
        )
        call = self.session.config.my_call
        operator = self.session.engine.operator
        name = self.session.contest.name
        mult_label = self.session.contest.mult_label
        op_txt = (
            f" <span style='color:{style.TEXT_DIM}'>op</span> {operator}"
            if operator and operator != call
            else ""
        )
        self._score_label.setText(
            f"<span style='color:{style.TEXT_DIM}'>Station</span> "
            f"<b style='color:{style.ACCENT}'>{call}</b>{op_txt} &nbsp;·&nbsp; {name} "
            f"&nbsp;|&nbsp; "
            f"QSOs <b style='color:{style.TEXT}'>{s.qso_count}</b> &nbsp; "
            f"Pts <b style='color:{style.TEXT}'>{s.qso_points}</b> &nbsp; "
            f"{mult_label} <b style='color:{style.MULT}'>{s.mult_count}</b> &nbsp; "
            f"Pwr <b style='color:{style.AMBER}'>×{mult}</b> &nbsp; "
            f"Score <b style='color:{style.AMBER}'>{s.total}</b>{peer_txt}"
        )

    def _reload_table(self) -> None:
        qsos = list(reversed(self.session.recent(200)))  # newest first
        self._table.setRowCount(len(qsos))
        local_station = self.session.engine.station_id
        for row, q in enumerate(qsos):
            exchange = " ".join(
                q.exchange_rcvd.get(f.name, "") for f in self.session.contest.exchange_fields()
            )
            values = [q.timestamp.strftime("%H:%M:%S"), q.call, q.band_label, q.mode.value]
            if self.session.contest.exchanges_rst:
                values += [q.rst_sent, q.rst_rcvd]
            values += [exchange.strip(), q.operator]
            is_peer = q.station_id != local_station  # logged at another station
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if is_peer:
                    item.setForeground(QColor(style.PEER))
                self._table.setItem(row, col, item)

    # ------------------------------------------------------------------ #
    # export
    # ------------------------------------------------------------------ #
    def _export_adif(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export ADIF", "partyhams.adi", "ADIF (*.adi)")
        if path:
            Path(path).write_text(self.session.export_adif())
            self.statusBar().showMessage(f"Exported ADIF to {path}", 4000)

    def _export_cabrillo(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Cabrillo", "partyhams.cbr", "Cabrillo (*.cbr *.log)"
        )
        if path:
            Path(path).write_text(self.session.export_cabrillo())
            self.statusBar().showMessage(f"Exported Cabrillo to {path}", 4000)

    def _edit_qrz(self) -> None:
        from partyhams.ui.qrz_dialog import QrzDialog

        dialog = QrzDialog(self._qrz.username, self._qrz.password, parent=self)
        self._qrz_dialog = dialog  # keep alive while open
        dialog.finished.connect(lambda result: self._qrz_done(dialog, result))
        dialog.open()

    def _qrz_done(self, dialog, result: int) -> None:
        self._qrz_dialog = None
        if result != QDialog.DialogCode.Accepted.value:
            return
        username, password = dialog.settings()
        self.set_qrz_credentials(username, password)
        if self.on_change_qrz is not None:
            self.on_change_qrz(username, password)  # app persists it
        if self._qrz_enabled():
            self.statusBar().showMessage(f"QRZ login set for {username}", 3000)
            self._qrz_lookup_now()  # look up the current call right away
        else:
            self.statusBar().showMessage("QRZ lookups disabled", 3000)

    def _edit_autoexport(self) -> None:
        from partyhams.ui.autoexport_dialog import AutoExportDialog

        dialog = AutoExportDialog(
            self._autoexport_enabled,
            self._autoexport_minutes,
            self._autoexport_only_if_new,
            parent=self,
        )
        self._autoexport_dialog = dialog  # keep alive while open
        dialog.finished.connect(lambda result: self._autoexport_done(dialog, result))
        dialog.open()

    def _autoexport_done(self, dialog, result: int) -> None:
        self._autoexport_dialog = None
        if result != QDialog.DialogCode.Accepted.value:
            return
        enabled, minutes, only_if_new = dialog.settings()
        self.set_autoexport(enabled, minutes, only_if_new)
        if self.on_change_autoexport is not None:
            self.on_change_autoexport(enabled, self._autoexport_minutes, only_if_new)
        state = "on" if enabled else "off"
        self.statusBar().showMessage(
            f"Auto-export {state} ({self._autoexport_minutes} min)", 3000
        )
