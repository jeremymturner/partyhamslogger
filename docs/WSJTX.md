# WSJT-X integration (FT8 / FT4 and other data modes)

PartyHams Logger can listen to [WSJT-X](https://wsjt.sourceforge.io/) over UDP.
When enabled it:

- **Logs your WSJT-X QSOs automatically** — every time you click *Log QSO* in
  WSJT-X, the contact (call, grid, frequency, mode, reports, exchange) is entered
  into the active PartyHams log and broadcast to your networked stations.
- **Shows a WSJT-X panel in data modes** — while WSJT-X is in a digital mode the
  function-key macro bar at the bottom of the window is hidden (WSJT-X is doing
  the transmitting) and replaced by a compact panel showing the current
  mode/dial frequency, transmit state, the odd/even Tx period, what you're
  sending, and a rolling list of recent decodes.
- **Highlights stations to work** *(best-effort)* — for callsigns calling CQ
  whose section you still need, PartyHams asks WSJT-X to color the callsign in
  its decode windows, nudging you to answer them.

> **Status:** the UDP path was developed and unit-tested against hand-built
> datagrams matching the documented WSJT-X protocol, but **has not been verified
> against a live WSJT-X instance**. The in-WSJT-X callsign highlighting in
> particular depends on WSJT-X's "Accept UDP requests" setting and is
> best-effort. Please report what you see on the air.

## 1. Decide how the rig is shared

WSJT-X and PartyHams can both talk to the radio, but only one program can own the
serial/CAT port at a time. Two common arrangements:

- **WSJT-X owns CAT (recommended for data-mode operating).** Point WSJT-X at the
  rig (Settings → Radio) and run PartyHams with **no radio** (manual) or with a
  CAT *sharing* layer such as Hamlib's `rigctld`, flrig, or a virtual COM
  splitter. PartyHams will still get frequency/mode from WSJT-X's UDP Status
  messages, which is enough for logging.
- **PartyHams owns CAT.** Keep PartyHams connected to the rig and set WSJT-X's
  CAT to *None* or to a shared `rigctld`. You operate FT8/FT4 split via WSJT-X's
  audio while PartyHams reads the band/mode.

If you use split or rig control in WSJT-X, set up the usual **Split Operation =
Rig or Fake It** and PTT method in WSJT-X → Settings → Radio.

## 2. Turn on WSJT-X UDP reporting

In **WSJT-X → Settings → Reporting → UDP Server**:

- **UDP Server:** the host running PartyHams. On the same machine, `127.0.0.1`
  is the simplest choice. A multicast group (`224.0.0.1`–`239.255.255.255`, e.g.
  to feed several apps at once) also works — set the **same** group as
  PartyHams' UDP Server (below) so PartyHams joins it; otherwise it won't receive
  the multicast traffic.
- **UDP Server port number:** `2237` (PartyHams' default — change both if needed).
- Tick **Accept UDP requests** — required for the "highlight needed sections"
  feature (the `HighlightCallsignInProgram` reply).
- Optionally tick **Notify on accepted UDP request** / **Accepted UDP request
  restores window** to your taste.

Leave the standard reporting boxes (PSK Reporter etc.) however you normally run
them — they don't affect PartyHams.

## 3. Enable the listener in PartyHams

In PartyHams Logger, open the **WSJT-X** menu:

- **Enable WSJT-X (UDP)** — starts/stops the listener. The choice is remembered.
- **Set UDP Server…** — the address to bind: blank for all interfaces (the
  default, fine for `127.0.0.1` unicast), or a multicast group to join (set this
  to match WSJT-X's UDP Server when you use multicast).
- **Set UDP Port…** — change the listen port if you didn't use `2237`.

When enabled you'll see `WSJT-X UDP listening on :2237` in the status bar. As
soon as WSJT-X sends a Status message in a data mode, the bottom bar switches to
the WSJT-X panel.

## 4. What gets logged

From WSJT-X's `QSOLogged` message PartyHams records:

| WSJT-X field      | PartyHams                          |
| ----------------- | ---------------------------------- |
| DX Call           | Call                               |
| Date & Time Off   | QSO timestamp (the contact's real time, not packet arrival) |
| Tx Frequency (Hz) | Frequency → band                   |
| Mode              | Mode (FT8/FT4 → DIGITAL group; other data sub-modes map to FT8) |
| Report Sent/Recv  | RST sent / received                |
| DX Grid           | Exchange `grid`                    |
| Exchange Recv     | Exchange `exchange` (if present)   |

Duplicate suppression is handled by the PartyHams sync engine, so a QSO that
also arrives from a networked peer is merged rather than double-counted. Note
that FT8/FT4 decodes do **not** carry an ARRL/RAC section, so for section-based
contests (Field Day) you may still want to confirm/add the section by hand if
the exchange isn't embedded in WSJT-X's free-text.

## 5. Troubleshooting

- **No panel / nothing logged:** confirm WSJT-X's UDP Server host+port match
  PartyHams, the listener is enabled, and (if on different machines) that UDP
  `2237` isn't blocked by a firewall.
- **Highlighting does nothing:** ensure **Accept UDP requests** is ticked in
  WSJT-X. Highlighting is best-effort and unverified against a live WSJT-X.
- **Rig conflicts / "port in use":** only one program may own the CAT port — see
  step 1 and consider a shared `rigctld`.
