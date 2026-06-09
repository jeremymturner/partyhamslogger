# PartyHams Logger — User Guide

PartyHams Logger is a keyboard-first, network-aware contest logger for amateur
radio. It is contest-agnostic: the entry row and scoring are built from the
selected contest's definition, so the same window logs ARRL Field Day today and
another contest tomorrow.

This guide has one page per screen. Open any page below, or browse the same
content inside the app via **Help → User Guide…**.

## Contents

| Page | What it covers |
| --- | --- |
| [Main logging window](main-window.md) | Score bar, entry row, log table, F-key macros, menus |
| [Network panel](network-panel.md) | Station roster, per-station stats, chat |
| [Sections Worked](sections.md) | Multiplier grid and the schematic section map |
| [New Log](new-log.md) | Creating a log: contest, station, exchange, network |
| [Open Log](open-log.md) | Reopening and switching between saved logs |
| [Radio / CAT](radio.md) | Choosing a rig: Hamlib, FlexRadio, Icom CI-V / LAN |
| [Macros & ESM](macros.md) | F-key messages, ESM, and Auto-CQ |
| [WSJT-X](wsjtx.md) | FT8/FT4 logging over UDP (see also the full WSJT-X notes) |
| [DX Cluster](dx-cluster.md) | Connecting to a cluster and spotting |
| [Themes & fonts](themes-fonts.md) | Dark/light themes and base font |
| [Reference data](reference-data.md) | Super Check Partial, city.dat, LoTW/eQSL/QRZ user lists |
| [QRZ.com lookups](qrz.md) | Live callsign lookups as you type |
| [Auto-export](auto-export.md) | Periodic ADIF backups |
| [Field Day / POTA notes](pota.md) | Activity-specific tips |
| [About](about.md) | Version and credits |
| [Keyboard shortcuts](shortcuts.md) | The full key reference |

## A note on the screenshots

The images in this guide are captured with Qt's **offscreen** platform so they
can be regenerated in CI without a display. As a result fonts, spacing, and
widget metrics are *representative* rather than pixel-identical to what you see
on your desktop — colors and layout match, but exact text rendering may differ
slightly. All shots use the default dark theme (one extra light-theme shot of
the main window appears on the [Themes & fonts](themes-fonts.md) page).

Regenerate them any time with:

```
python scripts/screenshots.py
```
