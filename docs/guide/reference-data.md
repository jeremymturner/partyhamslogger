# Reference data

Reference data improves your call-entry hints. Import it from
**Tools → Reference Data**. Everything is optional; with nothing imported the
logger works fine, just without the extra hints.

## What you can import

| Import | What it gives you |
| --- | --- |
| **Super Check Partial** | As you type a partial call, likely full calls are suggested (the classic SCP database). |
| **city.dat** | Maps callsigns/prefixes to locations for richer hints. |
| **Call History** | When you enter a known call, its exchange (e.g. Field Day class/section) is filled in automatically. |
| **LoTW users** | Flags whether a worked station uses Logbook of The World. |
| **eQSL users** | Flags eQSL participation. |
| **QRZ users** | Flags QRZ logbook participation. |

### Call History (auto-fill the exchange)

A call-history file maps callsigns to the exchange you expect from them, so
tuning to a familiar station in Search & Pounce pre-fills its Class/Section for
you. Two layouts are accepted:

- **N1MM Call History** — the standard format whose first line is
  `!!Order!!,Call,Sect,…`; existing community/club files work as-is. The `Sect`
  column maps to the Section field.
- **Simple CSV** — a header row whose first column is `Call`, followed by columns
  named after the contest's exchange fields, e.g.:

  ```
  Call,Class,Section
  K1ABC,2A,EMA
  W7XYZ,3A,OR
  ```

Column names are matched (case-insensitively) to the active contest's exchange
fields, so import the file **after** choosing your contest. Auto-fill only
populates *blank* exchange fields — anything you type always wins — and it never
blocks logging.

Imports are read from the files you point at and stored on disk, so they load
automatically on the next launch.

## Where the hints appear

- The **Call** field tooltip on the main window shows super-check-partial
  matches and QSL-network flags for the call you're entering.
- Combined with [QRZ.com lookups](qrz.md), you get both offline (SCP/city) and
  online (name/QTH/grid) context.

## Limitations

- These are **static snapshots** — refresh them periodically by re-importing the
  latest files from their sources.
- File formats must match the expected SCP / city.dat / user-list formats;
  malformed files are ignored.
- Reference hints are advisory and never block logging.
