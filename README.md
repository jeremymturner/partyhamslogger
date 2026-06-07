# PartyHams Logger

A cross-platform, multi-station amateur radio **contest logger** — N1MM-class
capability, dramatically easier to set up, configure, and operate.

Built with **Python 3.12 + Qt6 (PySide6)**. Runs on macOS, Windows, and Linux.

> 🚧 **Pre-alpha.** Scaffolding stage. See [IDEAS.md](IDEAS.md) for the full design
> document and decision log.

## What it is

- **Contest-first**, keyboard-driven logging in the spirit of N1MM Logger+.
- **Multi-station, peer-to-peer** over the LAN — several operators share one live
  log with cross-station dupe checking. No server, no single point of failure.
- **Radio CAT control** via **Hamlib** (universal) plus native **FlexRadio** and
  **Icom CI-V** drivers.
- **Pluggable** — new contests are data-driven definitions; new radios are
  backends. The MVP contest is **ARRL Field Day**.

See [IDEAS.md](IDEAS.md) §0 for the full list of locked design decisions.

## Project layout

```
src/partyhams/
├── core/      # QSO/operator models, dupe + identity logic
├── db/        # SQLite store (one log per station)
├── contest/   # pluggable contest engine + ARRL Field Day module
├── radio/     # radio abstraction + Hamlib / Flex / Icom CI-V backends
├── net/       # peer-to-peer UDP multicast sync (protocol + engine)
├── export/    # ADIF + Cabrillo writers
├── app/       # LogSession controller (Qt-free; the UI binds to this)
└── ui/        # PySide6 entry / log / score windows + first-run dialog
tests/         # contest, sync convergence, session, and export tests
```

Launch the logger with `make run`. On first launch it shows the **log-creation**
screen — pick the activity (Field Day; others as they're added), enter your call /
exchange / power and an optional network name. It then asks you to **select a
radio** (Hamlib, FlexRadio, or None for manual band/mode). Both the current log
and the radio choice are remembered (under `~/.partyhams/`), so the next launch
reopens your log straight into the keyboard-first entry window: type the call,
Enter walks the exchange fields, Enter logs. Live score and dupe checking update
as you go; **Export ADIF / Cabrillo** when you're done.

## Getting started (dev)

Requires Python 3.12+. Using [uv](https://docs.astral.sh/uv/):

```bash
uv venv
uv pip install -e ".[dev]"

# run the tests
uv run pytest

# launch the app (UI is minimal at this stage)
uv run partyhams
```

Or with stock tooling:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m partyhams
```

### Try the peer-to-peer sync (Phase-0 spike)

See the multi-station log sync in action — run in two terminals (or on two
machines on the same LAN), each with a different callsign:

```bash
make spike CALL=W7ABC
make spike CALL=K2XYZ
```

Each instance logs a fake QSO every few seconds; watch the **QSO count** climb
together and the **log hash** match — that's the peer-to-peer log converging.

## License

[GPL-3.0-or-later](LICENSE). Free and open source, in keeping with the amateur
radio software tradition (Hamlib, fldigi, WSJT-X).

## 73
Contributions welcome once the foundation settles. de PartyHams.
