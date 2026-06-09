# Main logging window

![Main logging window](../screenshots/main-window.png)

The main window is where you spend the contest. It is **keyboard-first** and
modeled on N1MM-style entry: type a call, press Enter to advance, and a final
Enter logs the QSO.

## Layout, top to bottom

- **Score bar** — your station call, the contest name, and a live tally:
  QSOs, points, sections (multipliers), power multiplier, and total score.
- **Entry row** — the call field plus exchange fields generated from the
  contest definition, then Band and Mode, a **Log (Enter)** button, and the
  current frequency. When a radio is connected the band/mode/frequency follow
  the rig (CAT) and the manual combos mirror them read-only.
- **Log table** — every QSO in the active log, newest at the top, with columns
  adapted to the contest (e.g. Field Day has no RST columns).
- **F-key macro bar** — twelve function-key messages for the current mode and
  Run/S&P bank. In data modes driven by WSJT-X this bar is replaced by the
  [WSJT-X panel](wsjtx.md).
- **Status bar** — transmit indicator on the left, the connected radio (or
  "No radio (manual)") on the right, plus transient messages.
- **Network dock** — the [Network panel](network-panel.md) docks on the right.

## Keyboard flow

| Key | Action |
| --- | --- |
| Type in **Call** | Enter the worked station's callsign |
| **Enter** | Advance to the next empty field; on the last field, log the QSO |
| **F1–F12** | Send the corresponding macro |
| **Tab** | Toggle Run / Search & Pounce (changes the macro bank) |

The Call field shows live hints as a tooltip: dupe status, super-check-partial
matches, and (if configured) QRZ lookup results.

## Menus

- **Logs** — New / Open / Open Recent, Export ADIF, Export Cabrillo, Auto-export.
- **Radio** — Select Radio (choose/change the CAT connection).
- **WSJT-X** — enable the UDP listener and set its port.
- **Macros** — edit messages, toggle ESM, Auto-CQ and its interval.
- **View** — Sections Worked, DX Cluster, Theme, Font, and the Network dock toggle.
- **Tools** — QRZ Login, Reference Data imports.
- **Help** — User Guide, Keyboard Shortcuts, About.

## Limitations

- CAT auto-fill follows the rig only while a radio is connected; otherwise band
  and mode are chosen manually.
- The window binds to a single active log at a time; use **Logs → Open** to
  switch (see [Open Log](open-log.md)).
- Voice (phone) macros play `.wav` files and require Qt Multimedia, which is
  bundled in packaged builds.
