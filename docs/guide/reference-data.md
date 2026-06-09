# Reference data

Reference data improves your call-entry hints. Import it from
**Tools → Reference Data**. Everything is optional; with nothing imported the
logger works fine, just without the extra hints.

## What you can import

| Import | What it gives you |
| --- | --- |
| **Super Check Partial** | As you type a partial call, likely full calls are suggested (the classic SCP database). |
| **city.dat** | Maps callsigns/prefixes to locations for richer hints. |
| **LoTW users** | Flags whether a worked station uses Logbook of The World. |
| **eQSL users** | Flags eQSL participation. |
| **QRZ users** | Flags QRZ logbook participation. |

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
