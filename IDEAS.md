# PartyHams Logger — Idea Document

> A cross-platform, multi-station amateur radio logging application.
> N1MM-class capability, dramatically easier to set up, configure, and operate.

**Status:** Draft v0.4 — working document
**Last updated:** 2026-06-06

---

## 0. Decisions Locked (2026-06-06)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Multi-station sync model | **Peer-to-peer LAN** (N1MM-style UDP, every station holds the full log) |
| 2 | Primary focus | **Contest-first** (dense keyboard entry, scoring, mults, Cabrillo, macros) |
| 3 | CAT control strategy | **Hamlib base + native FlexRadio & Icom CI-V drivers** |
| 4 | MVP scope | **Multi-station shared log from day one** |
| 5 | First contest module | **ARRL Field Day** (canonical multi-op event) |
| 6 | MVP keying | **CW via rigctl/Hamlib + Voice (.wav)**; digital deferred to v1 |
| 7 | SO2R / SO2V | **Deferred to v1** (single-radio-clean entry UI first) |
| 8 | Dev/test platform | **macOS first**, then Windows 10+ & Ubuntu 22.04+ |
| 9 | GUI binding | **PySide6** (LGPL Qt6) |
| 10 | Offline-first | **Yes** — events may have no internet; QRZ/cluster optional |
| 11 | License | **GPL-3.0-or-later** (open source; ham-radio convention) |
| 12 | Session auth | **None** — each station just names its operator; trusted LAN |
| 13 | Extensibility | **Pluggable from day one** — new contests = data files, new radios = backends |

**What this means in one sentence:** the MVP is a contest-capable, networked,
peer-to-peer logger where several operators on a LAN share one live log with
cross-station dupe checking — i.e., N1MM's headline scenario, done cleanly and
cross-platform.

---

## 1. Vision & Goals

Give serious operators the power of **N1MM Logger+** (contesting, networked
multi-op, CAT control, band maps, spotting, scoring) while removing its biggest
pain points: Windows-only, fiddly setup, dated UI, steep config curve.

### Design principles
- **Cross-platform first** — Windows, macOS, Linux from one Qt6 / Python codebase.
- **Multi-station native** — built from day one for several operators on one event.
- **Setup in minutes** — auto-detect radios, sane defaults, guided wizards, no `.ini` editing.
- **Familiar to N1MM users** — entry window, band map, log, F-key macros, keyboard-driven.
- **Open & inspectable** — ADIF, Cabrillo, a documented network protocol, scriptable.

### Explicit non-goals (for now)
- Not an SDR/DSP app — we *talk to* radios, we don't demodulate.
- Not replacing WSJT-X / fldigi — we *integrate* with them.

---

## 2. Target Users & Scenarios (in priority order)

1. **Multi-op contest / Field Day club station** — 3–10 networked stations, shared
   log, cross-station dupe + mult checking, live aggregate score. *(Primary MVP driver.)*
2. **Single-op contester** — fast entry, CAT, macros, SO2R/SO2V, Cabrillo.
3. **DX / general daily logging** — QRZ lookup, awards, ADIF/LoTW sync.
4. **POTA/SOTA / special event** — quick, portable, often offline.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Station App (Qt6 / Python) — one instance per operator         │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌────────────────┐    │
│  │ Entry UI │ │ Band Map │ │ Log View  │ │ Score / Status │    │
│  └────┬─────┘ └────┬─────┘ └─────┬─────┘ └───────┬────────┘    │
│  ┌────┴────────────┴─────────────┴───────────────┴────────┐    │
│  │   Core Engine: logging · dupes · contest scoring · mults │    │
│  └────┬───────────────┬───────────────┬───────────────────┘    │
│   ┌───┴────┐   ┌───────┴───────┐   ┌───┴────────┐               │
│   │ Radio  │   │ P2P Sync       │   │ Local DB   │               │
│   │ Abstr. │   │ (UDP LAN)      │   │ (SQLite)   │               │
│   └───┬────┘   └───────┬───────┘   └────────────┘               │
└───────┼────────────────┼─────────────────────────────────────────┘
        │                │  UDP broadcast/multicast on LAN
   ┌────┴─────┐   ┌──────┴──────────────────────────────┐
   │ Hamlib   │   │  ▲ ▲ ▲  other PartyHams stations      │
   │ FlexAPI  │   │         (each holds full log)         │
   │ Icom CIV │   └──────────────────────────────────────┘
   └──────────┘
```

### 3.1 Radio abstraction layer
Single `Radio` interface, pluggable backends. **Hamlib is the universal base**
(via `rigctld` or Python bindings — covers hundreds of rigs); **native drivers**
for FlexRadio (SmartSDR TCP API, multi-slice) and **Icom IC-7610 CI-V** (direct
serial/USB) layer on top for higher fidelity (S-meter streaming, slices,
spectrum, faster polling).

Capabilities surfaced: frequency, mode, VFO A/B, split, PTT, S-meter, RIT/XIT,
sub-receiver/slice. Backend selection per radio; auto-detect attempted, manual
override always available.

**Hardware on hand for driver validation** (maps cleanly onto the three backends):

| Radio | Backend to validate | Notes |
|-------|--------------------|-------|
| FlexRadio **6500** | **Flex native** (SmartSDR TCP API) | Multi-slice, spectrum; primary Flex target |
| **Icom IC-705** | **Icom CI-V native** | CI-V over USB/Bluetooth; shares CI-V with the 7610 |
| **Icom IC-7610** *(remote, maybe)* | **Icom CI-V native** | Same driver as IC-705; secondary validation |
| **Yaesu FT-891** | **Hamlib** (`rigctld`) | Proves the universal base backend |

This set is ideal: one radio exercises each backend path (Flex native, Icom CI-V
native, Hamlib universal), so all three code paths get real-hardware coverage.

### 3.2 Peer-to-peer LAN sync (core design)
Modeled on N1MM's proven approach, modernized:

- **Every station holds the full log** in its own SQLite DB. No server, no single
  point of failure.
- **Transport:** UDP on the LAN. Default **multicast** (cleaner than broadcast,
  fewer dropped packets, works across managed switches) with broadcast fallback.
  Each event uses a shared **network name + passphrase** so multiple events on one
  LAN don't cross-talk.
- **Each QSO** is stamped with `(station_id, local_seq, uuid, utc_timestamp)` and
  broadcast on log/edit/delete. Receivers merge by `uuid`; last-writer-wins on
  edits using a logical clock, with an edit history kept for audit.
- **Late join / catch-up:** a joining station requests a delta sync; peers reply
  with everything after the requestor's high-water mark per `station_id`.
- **Dupe + multiplier checking** runs against the merged view, so any station sees
  dupes worked by any other station in real time.
- **Operator identity:** no authentication — a trusted LAN is assumed. Each station
  simply declares its **operator name/call** when joining; QSOs are stamped with it.
- **Serial-number coordination** (for serial-exchange contests): each station owns
  a distinct serial space (interleaved by `station_id`, or assigned blocks) so two
  ops never hand out the same number. Configurable per contest.
- **Resilience:** periodic lightweight "heartbeat + log hash" lets stations detect
  divergence and trigger a reconciliation sync.
- **Interop:** also speak the documented **N1MM UDP XML** formats (contact, spot,
  score, radio) so existing tools and displays can join the party. *(v1.)*

> Conflict resolution, serial coordination, and reconciliation are the parts most
> worth prototyping early — they're where N1MM clones usually get it wrong.

### 3.3 Data & formats
- **Local store:** SQLite per station.
- **Interchange:** ADIF (import/export), Cabrillo (contest submission).
- **Online (later):** LoTW, QRZ logbook, eQSL, Club Log.

---

## 4. Contest Engine (primary focus — expanded)

A **declarative contest definition** drives everything: exchange fields, parsing,
scoring, multipliers, dupe rules, and Cabrillo mapping. Goal: add a new contest by
writing a definition file, not code.

A contest definition specifies:
- **Exchange schema** — ordered fields and types, e.g.
  `RST + serial`, `RST + state/province`, `RST + CQ zone`, `grid`,
  `name + power`, `RST + ITU zone`, `class + section` (Field Day).
- **Sent exchange** — fixed (e.g. your zone/section) or per-QSO (serial).
- **QSO points** — by band, by mode, by same-continent / same-country / DX, etc.
- **Multipliers** — DXCC entities, CQ/ITU zones, US states + VE provinces (WAS),
  grid squares, prefixes (WPX), ARRL/RAC sections — counted per band or once.
- **Dupe rule** — per band, per band+mode, or once-per-contest.
- **Band/mode/time validity** — legal bands, contest period, off-time rules.
- **Cabrillo mapping** — how logged fields render into a Cabrillo `QSO:` line.

Engine features:
- Real-time **score, QSO count, and multiplier** display, per band and total.
- **Multiplier highlighting** in entry and band map (new mult vs. dupe vs. worked).
- **Exchange auto-fill & validation** (e.g. resolve zone/section from callsign/CTY.dat).
- **Function-key macros** with N1MM-style variable substitution
  (`{MYCALL}`, `{SENTRST}`, `{EXCH}`, `{F2}`, `{CORRECT}`, etc.) for CW / voice / digital.
- **Run vs. S&P** modes with appropriate macro sets.
- **Rate meters** (1h/10min QSO rate), goals. *(v1+.)*

### 4.1 First module — ARRL Field Day

Chosen because it's the canonical multi-op/multi-station event and hammers the
networking core. Specifics the engine must model:

- **Exchange:** `Class + Section`. Class = number of transmitters + category
  letter, e.g. `3A`, `2F`, `1E`, `1B`. Section = ARRL/RAC section (e.g. `OR`,
  `EPA`, `STX`) or `DX` for stations outside US/Canada.
- **Categories (letters):** A (club/group, 3+ ops, portable), B (1–2 ops portable),
  C (mobile), D (home/commercial power), E (home/emergency power), F (EOC).
- **Bands:** all contest HF bands **except WARC** (30/17/12 m are *not* allowed),
  plus 6 m, 2 m, etc.
- **Dupes:** per band **and** per mode-group, where mode groups are
  **CW / Phone / Digital** (so 20 m CW and 20 m Phone are different slots).
- **QSO points by mode:** Phone = **1 pt**, CW = **2 pt**, Digital = **2 pt**.
- **Power multiplier (applies to QSO points):** ≤5 W (battery/solar) = **×5**,
  ≤150 W = **×2**, >150 W = **×1**.
- **Bonus points:** GOTA, satellite QSO, public-info table, emergency power,
  alt-power, NTS messages, web submission, etc. (a checklist the app tallies).
- **Score:** `(QSO points × power multiplier) + bonus points`.

> **Important nuance:** Field Day has **no QSO-count multipliers** (sections are
> exchange data, *not* mults). So it stress-tests networking, multi-band/mode
> dupe checking, power multiplier, and bonus tallying — but **not** the
> multiplier-tracking subsystem. To exercise that, the **second** module should be
> a mult-heavy contest (CQ WW = zones+DXCC, or WPX = prefixes+serials). Build the
> mult engine generic now; validate it with module #2.

---

## 5. Feature Checklist

Legend: `[MVP]` first release · `[v1]` 1.0 · `[later]` post-1.0

### 5.1 Logging core
- [MVP] Fast keyboard-driven QSO entry, UTC auto-fill, manual override
- [MVP] Real-time dupe checking across networked stations
- [MVP] Edit / delete / search log
- [v1] Partial-call check & Super Check Partial (master.dta / master.scp)
- [v1] Callsign history / prior-QSO recall

### 5.2 Radio / CAT control
- [MVP] Hamlib backend (rigctld)
- [MVP] FlexRadio native API
- [MVP] Icom IC-7610 CI-V native
- [MVP] Auto-fill band/mode/freq from radio
- [MVP] CW keying via rigctl/Hamlib (radio's built-in keyer over CAT)
- [MVP] Voice messages via `.wav` playback on F-keys (phone)
- [v1] Winkeyer (hardware CW), digital keying (via WSJT-X/fldigi)
- [v1] SO2R / SO2V
- [later] Rig auto-detect wizard

### 5.3 Band map & spotting
- [v1] Band map (spots vs. current VFO), click-to-tune
- [v1] DX cluster (telnet) connect & filter
- [v1] Mult/dupe coloring, spot age
- [later] CW Skimmer / RBN

### 5.4 Contest engine
- [MVP] Declarative contest definitions (1+ contest at MVP, e.g. Field Day)
- [MVP] Exchange parsing/validation, dupe rules
- [MVP] Real-time score + multiplier tracking
- [MVP] Function-key macros — CW (over CAT) + voice (.wav)
- [MVP] Cabrillo export
- [v1] More contest modules, rate meters, goals
- [v1] Run/S&P macro sets

### 5.5 Multi-station / networking
- [MVP] P2P shared log over LAN (multicast UDP)
- [MVP] Cross-station dupe + multiplier checking
- [MVP] Operator identity, serial-number coordination
- [MVP] Late-join delta sync + divergence reconciliation
- [v1] Live aggregate score, "who's on what" panel, op-to-op chat
- [v1] N1MM-compatible UDP interop

### 5.6 Digital & external integration
- [v1] WSJT-X / JTDX UDP (auto-log FT8/FT4)
- [v1] fldigi (XML-RPC)
- [later] Winkeyer, rotator (rotctld)

### 5.7 Lookups & awards
- [v1] QRZ / HamQTH lookup, CTY.dat prefix/country, grid/distance/bearing
- [later] DXCC / WAS / WAZ / POTA / SOTA tracking
- [later] LoTW / eQSL / Club Log upload

### 5.8 UX & configuration
- [MVP] First-run setup wizard, radio test-connection button
- [MVP] N1MM-like layout (Entry, Log, Band Map, Check, Score windows)
- [MVP] Join-network flow (name + passphrase, see peers)
- [v1] Theming, dockable/movable windows, multi-monitor, profiles
- [later] Cloud config backup

---

## 6. Technology Stack (proposed)
- **Language:** Python 3.12+
- **GUI:** PySide6 (official Qt6 bindings, LGPL) — *confirmed*
- **DB:** SQLite per station
- **Networking:** asyncio; UDP multicast for sync; Qt event-loop integration (qasync)
- **Radio:** Hamlib (`rigctld` / Python bindings), FlexRadio API, pyserial for CI-V
- **Audio (voice macros):** Qt Multimedia or sounddevice for `.wav` playback
- **Packaging:** Briefcase or PyInstaller → native installers per OS
- **Dev/test order:** macOS 13+ first → Windows 10+ → Ubuntu 22.04+

---

## 7. Open Questions

**Resolved** (see Decisions table §0): first module = Field Day · keying = CW(CAT)+voice ·
SO2R deferred · PySide6 · macOS-first · offline-first.

**Resolved (this round):** license = **GPL-3.0-or-later** · auth = **none, name the
operator** · test gear = **Flex 6500, IC-705, IC-7610 (remote), FT-891** · build
**pluggable** for future contests + radios · **scaffold the repo now**.

**Still to settle (next round):**
1. **Field Day realism** — bonus-point checklist + GOTA handling in the MVP, or score
   the QSOs first and add bonuses in a fast-follow?
2. **CI** — set up GitHub Actions (lint + tests on macOS/Windows/Linux) now or later?
3. **Distribution** — GitHub repo under a personal account or a club/org?

---

## 8. Roadmap

- **Phase 0 — Spikes (de-risk the hard parts):**
  - ✅ **P2P sync prototype — DONE.** Real UDP-multicast transport
    (`net/transport.py`), `SyncEngine` (join → Hello-driven catch-up → live QSO
    broadcast → heartbeat/log-hash reconciliation), and a runnable harness
    (`net/spike.py`, `make spike CALL=…`). Verified: two engines converge over
    live sockets *and* deterministically over an in-memory loopback bus
    (`net/loopback.py`) in CI. Known follow-up: unicast (not multicast)
    sync-responses, and full version-vector anti-entropy for cross-station edits.
  - Hamlib CAT spike: connect, read freq/mode, send CW over CAT (macOS).
  - PySide6 entry-window prototype: keyboard-first QSO entry feel.
- **Phase 1 — MVP (in progress):**
  - ✅ **Logging core + entry window — DONE.** `LogSession` controller
    (`app/session.py`) ties contest + P2P sync + SQLite + dupe/score/export; the
    PySide6 entry window (`ui/`) is keyboard-first, builds its exchange fields from
    the contest schema, shows live score + DUPE indicator, and lists the log
    (peer QSOs coloured). Field Day fully wired; **ADIF + Cabrillo export** done;
    first-run dialog done; offline *and* networked (multicast) modes.
  - ⏳ **Remaining:** live CAT auto-fill of band/mode/freq (Hamlib first, then Flex
    + Icom CI-V drivers), CW(CAT)+voice F-key macros, and on-the-air testing
    across macOS/Windows/Linux.
- **Phase 2:** Module #2 (mult-heavy: CQ WW or WPX) to validate the multiplier engine,
  band map + DX cluster, rate meters, run/S&P macro sets, SO2R/SO2V, N1MM UDP interop.
- **Phase 3:** Digital integration (WSJT-X/fldigi), QRZ/CTY lookups, awards tracking,
  online log sync (LoTW/QRZ/Club Log), theming & polish.
