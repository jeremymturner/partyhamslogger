# Field Day / POTA activity notes

PartyHams is contest-agnostic — the entry row, scoring, and multiplier tracking
all come from the selected activity's definition. This page collects tips for
the two flagship activities. You pick the activity in the
[New Log](new-log.md) dialog.

## ARRL Field Day

- **Exchange:** class + section (no RST), e.g. `3A OR`. The entry row reflects
  this — there are no RST columns.
- **Multipliers:** ARRL/RAC sections, tracked live in
  [Sections Worked](sections.md).
- **Bands:** the contest HF bands plus VHF/UHF, excluding the WARC bands.
- **Power multiplier** is set at log creation and shown in the score bar.
- Well-suited to multi-op networked logging — see the
  [Network panel](network-panel.md).

## Parks on the Air (POTA)

- **Setup:** enter your activator park reference (e.g. `US-1234`) as a config
  field. It can be validated against the live POTA API.
- **Exchange:** RST, plus the contacted station's **optional** park reference for
  park-to-park (P2P) contacts.
- **Dupes:** POTA lets you re-work the same station on a different band, mode, or
  **day**, so the dupe check keys on `(call, band, mode group, UTC date)`.
- **Scoring:** POTA isn't a scored contest — the score line simply reports your
  QSO count.
- **Bands:** all amateur HF allocations plus 6 m and 2 m.

## Limitations

- Only the built-in activity definitions are selectable; others aren't supported.
- POTA park-reference validation against the live API needs internet access; the
  format check (`US-1234`) works offline.
- Field Day power multiplier and class are fixed at log creation.
