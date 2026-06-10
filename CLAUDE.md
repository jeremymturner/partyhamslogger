# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

PartyHams Logger is a cross-platform, multi-station amateur-radio contest logger
(N1MM-class) built on **PySide6 (Qt)** with an **asyncio** core bridged to Qt via
**qasync**. Python ≥ 3.12. Source lives under `src/partyhams/` (src layout).

## Commands

The `Makefile` is the front door; it manages a `.venv` and installs `-e ".[dev]"`
on first use. Override the bootstrap interpreter with `make PYTHON=/path/to/python3.12 …`.

- `make run` — launch the app (sets up the venv first if needed)
- `make test` — full test suite (`pytest -q`)
- `make lint` / `make format` — ruff check / ruff format + `--fix`
- `make check` — lint + test (what CI runs)
- `make package` — standalone build for the current OS via PyInstaller (see `docs/PACKAGING.md`); `make release VERSION=vX.Y.Z` cuts a GitHub release (`docs/RELEASING.md`)

Inside the venv (`.venv/bin/python`) or any env with deps installed:

- Run one test: `python -m pytest tests/test_engine.py::test_three_stations_converge -q`
- Tests are async-enabled (`asyncio_mode = "auto"` in pyproject) — plain `async def test_*` works, no decorator.
- **Headless Qt**: UI tests/scripts need `QT_QPA_PLATFORM=offscreen` (no display). Most logic is Qt-free and tests without it. Generate doc screenshots with `QT_QPA_PLATFORM=offscreen python scripts/screenshots.py`.

ruff `line-length = 100`. End commit messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Architecture (the parts you must read multiple files to grasp)

**Strict layering — everything outside `ui/` is Qt-free and unit-testable.** The UI
imports PySide6 lazily; `__main__.py` degrades gracefully if PySide6 is missing.
Keep new non-UI code import-clean of Qt.

- **`app/session.py` — `LogSession` is the controller the UI binds to.** It owns the
  contest, station config, the sync engine, and the SQLite store, and exposes the
  whole app API (record/dupe/score/roster/chat/export). It is deliberately Qt-free.
  Every QSO — logged locally *or* received from a peer — flows through one fan-out
  point: `engine.on_qso → LogSession._on_applied → store.upsert → UI listeners`. On
  construction it preloads the persisted log (and chat) into the engine.

- **`net/` — peer-to-peer LAN sync (a CRDT, no server).** `engine.SyncEngine` ties a
  `Transport` to `sync.LogMerge` (an op-CRDT: per-`uuid` last-writer-wins ordered by
  `(lamport, station_id)` — idempotent, order-independent) and a `LamportClock`. The
  same LWW rule is mirrored in `db/store.SqliteLog.upsert`, so memory and disk
  converge identically. `protocol.py` is JSON-over-UDP-multicast (human-readable on
  purpose): `Hello / QsoMessage / SyncRequest / SyncResponse / FullLogRequest /
  Heartbeat / StationStatus / Chat / ChatSyncResponse`. The engine fires callbacks
  (`on_qso / on_status / on_chat / on_clock_off`) that the app layer wires to
  persistence + UI. Transports: `MulticastTransport` (real), `NullTransport`
  (offline), `LoopbackTransport`/`LoopbackBus` (tests). **Testing pattern:** drive the
  engine deterministically with `join()` + manual `pump_once()` (see
  `tests/test_engine.py`'s `converge()` helper), not the background loops that
  `start()` spawns.

- **`contest/` — pluggable contest framework.** `base.ContestDefinition` (ABC) defines
  `config_fields`/`exchange_fields`/`dupe_key`/`multipliers`/`score`/`allowed_bands`.
  Modules **self-register** via `@register` and must be imported in
  `contest/__init__.py` to take effect; the UI lists them via `available()` and builds
  one with `get(id)`. Field Day dupe rule = `(call, band, mode_group)` where
  `mode_group_for()` collapses modes into CW/PHONE/DIGITAL. `sections.py` holds the
  ARRL/RAC section data (+ the schematic map layout); `calendar.py` picks the default
  contest by date.

- **`radio/` — pluggable CAT backends.** `base.Radio` (ABC, async) advertises a
  `Capability` flag set; backends: `hamlib` (TCP rigctld), `flex` (UDP discovery + TCP
  SmartSDR), `icom_civ` (serial CI-V), `icom_net` (Icom native UDP LAN). `civ_protocol`
  (pure framing) + `civ_commands` (shared command layer) back both Icom drivers.
  `app/radio.RadioPoller` wraps a backend: polls `read_state()` on an interval, emits
  `on_state`/`on_status`, and **auto-reconnects** (connection loss is non-fatal).
  **Gotcha:** despite `radio/registry.py` existing, the UI does *not* use it — radios
  are constructed by a hand-written factory `_poller_from_radio()` in `ui/app.py` keyed
  on `kind` strings. Adding a radio means editing both `ui/radio_dialog.py` and that
  factory.

- **`ui/` — PySide6.** `app.py` is the bootstrap: builds the `QApplication`, starts the
  qasync loop, and runs the window/log/radio lifecycle (it owns persistence callbacks
  like `on_change_theme`/`on_change_radio`/`on_change_*` that write `AppState`).
  `main_window.py` is the large entry window (score bar, keyboard-first entry row, log
  table, F-key macro bar, menus, status bar). `style.py` is a **palette-driven theming
  system**: 6 themes, live-switchable. **Critical convention:** UI modules read colors
  via `from partyhams.ui import style` then `style.ACCENT` (live attributes) — *never*
  `from partyhams.ui.style import ACCENT`, which copies the value at import and breaks
  live theme switching. `restyle()` methods re-apply inline styles after a theme change.

- **Integrations** are isolated packages, each pure-parse + thin-transport so they're
  testable without the external system: `wsjtx/` (UDP protocol decode + QSOLogged→QSO),
  `cluster/` (telnet DX-cluster spot parsing), `qrz/` (XML API), `refdata/`
  (super-check-partial / city.dat / LoTW-eQSL-QRZ user lists). Network clients
  (`qrz`, `pota_api`, `calendar`) take an injectable `fetch` callable so tests run
  offline; live paths (WSJT-X UDP, QRZ, cluster, POTA API, native CAT) are exercised
  only via crafted bytes / fake servers / injected fetch and are **noted as
  unverified-against-hardware** in their commits/docstrings.

- **`app/state.py`** persists `AppState` as JSON under `~/.partyhams/` (current log,
  radio choice, theme, font, auto-CQ, auto-export, WSJT-X, QRZ creds). Log files are
  **self-describing**: contest id + station config live in the SQLite `meta` table, so
  a `.sqlite` reopens standalone (`open_session`).

- **`export/`** — ADIF + Cabrillo writers, plus `timestamped_adif_name()` used by the
  periodic auto-export backup.

## Testing conventions

- Fakes mirror real transports for hardware/network-free tests: `tests/fake_flex.py`,
  `fake_rigctld.py`, `fake_cluster.py`, `fake_icom_net.py`, and `FakeCivSerial`
  (injected via a driver's `serial_factory`/`fetch` seam). Follow these when adding a
  backend or integration.
- Prefer testing pure logic (protocol encode/decode, scoring, dupe rules, CRDT
  convergence) over Qt. When Qt is unavoidable, construct widgets under
  `QT_QPA_PLATFORM=offscreen` and assert on state, not pixels.

## Background / design intent

`README.md` is the user-facing overview; `IDEAS.md` records locked design decisions
(notably #1 peer-to-peer LAN sync and #3 the radio abstraction layer) and the feature
roadmap. `docs/guide/` is the in-app User Guide (Help → User Guide), one page +
screenshot per screen; `docs/PACKAGING.md` and `docs/RELEASING.md` cover distribution.
