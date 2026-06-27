"""Map a WSJT-X :class:`QSOLogged` onto our logging model.

Kept separate from both the pure protocol and the Qt UI so it can be unit-tested
directly. :func:`qso_logged_to_record` returns the keyword arguments for
:meth:`partyhams.app.session.LogSession.record_qso` (call / freq / mode /
exchange / reports); the session then stamps identity + merge metadata.
"""

from __future__ import annotations

import uuid as _uuid

from partyhams.core.models import Mode
from partyhams.wsjtx.protocol import QSOLogged

# Fixed namespace for deriving a stable QSO uuid from a WSJT-X logged contact, so
# a duplicated UDP delivery (WSJT-X sends one copy per "Outgoing interface", and
# multicast can re-deliver) maps to the SAME uuid and is deduped, not re-logged.
_WSJTX_NS = _uuid.UUID("9f1d2c3a-6b7e-4f80-9a11-7e1c0d2b3a45")


def stable_uuid(msg: QSOLogged) -> str:
    """A content-derived uuid for a WSJT-X logged QSO — identical across duplicate
    deliveries of the same contact, distinct across operators/contacts."""
    when = msg.date_time_off or msg.date_time_on
    key = "|".join(
        [
            (msg.operator_call or msg.my_call or "").strip().upper(),
            msg.dx_call.strip().upper(),
            str(int(msg.tx_frequency)),
            msg.mode.strip().upper(),
            when.isoformat() if when else "",
        ]
    )
    return str(_uuid.uuid5(_WSJTX_NS, key))

# WSJT-X mode strings -> our concrete Mode. WSJT-X reports many digital
# sub-modes (FT8, FT4, JT9, MSK144, ...); anything not FT4 maps to FT8's
# DIGITAL mode-group, which is what scoring/dupe rules key on.
#
# Status (type 1) packets carry the full mode name ("FT8"/"FT4"), but Decode
# (type 2) packets carry only the single-character submode code from WSJT-X's
# band-activity grid ("~" = FT8, "+" = FT4). Both forms are mapped here so FT8
# and FT4 are told apart wherever a packet's mode field is read.
_MODE_MAP: dict[str, Mode] = {
    "FT8": Mode.FT8,
    "~": Mode.FT8,  # Decode-packet submode code for FT8
    "FT4": Mode.FT4,
    "+": Mode.FT4,  # Decode-packet submode code for FT4
    "RTTY": Mode.RTTY,
    "PSK31": Mode.PSK31,
    "PSK": Mode.PSK31,
    "CW": Mode.CW,
    "USB": Mode.USB,
    "LSB": Mode.LSB,
    "FM": Mode.FM,
    "AM": Mode.AM,
}


def map_mode(mode: str) -> Mode:
    """Best-effort WSJT-X mode string -> :class:`Mode` (default FT8/DIGITAL).

    Accepts both the full name from Status packets ("FT8"/"FT4") and the
    single-character submode code from Decode packets ("~"/"+")."""
    return _MODE_MAP.get(mode.strip().upper(), Mode.FT8)


# FT8 transmits in 15s sequences, FT4 in 7.5s sequences (UTC-aligned). The
# sequence index is floor(seconds-into-minute / length); even index => "even".
_SEQ_LEN_S: dict[str, float] = {"FT8": 15.0, "FT4": 7.5}


def tx_even_from_epoch(epoch_seconds: float, mode: str) -> int:
    """Which FT8/FT4 sequence a transmit at ``epoch_seconds`` falls in.

    Returns ``1`` for an even sequence, ``0`` for odd, and ``-1`` when ``mode``
    is not a timed FT8/FT4 data mode (so odd/even is undefined). The sequence is
    aligned to UTC wall-clock seconds: FT8 uses 15s slots, FT4 uses 7.5s slots,
    and the slot index is ``floor((seconds-into-minute) / slot_length)``.

    Pure + UTC-only so it can be unit-tested without WSJT-X or Qt.
    """
    length = _SEQ_LEN_S.get(mode.strip().upper())
    if length is None:
        return -1
    seconds_into_minute = epoch_seconds % 60.0
    index = int(seconds_into_minute // length)
    return 1 if index % 2 == 0 else 0


def parse_tx_power(raw: str) -> float | None:
    """Parse WSJT-X's free-form Tx-power string into watts (``None`` if absent).

    WSJT-X carries power as a free-text field (e.g. ``"5"``, ``"100 W"``); we
    take the leading numeric part. Returns ``None`` when empty/unparseable so the
    caller can leave power unknown rather than broadcasting a bogus ``0``.
    """
    text = (raw or "").strip()
    if not text:
        return None
    num = ""
    for ch in text:
        if ch.isdigit() or ch in ".-":
            num += ch
        else:
            break
    try:
        value = float(num)
    except ValueError:
        return None
    return value if value > 0 else None


def qso_logged_to_record(msg: QSOLogged, contest=None) -> dict[str, object]:  # noqa: ANN001
    """Build ``record_qso`` kwargs from a WSJT-X logged QSO.

    The received exchange WSJT-X carries (e.g. Field Day ``"1D KS"``) is parsed
    into the contest's named exchange fields (``{class, section}``) via
    ``contest.parse_exchange`` so it displays and exports correctly; the grid
    rides separately under ``"grid"`` (not part of the contest exchange).
    Reports map to ``rst_sent``/``rst_rcvd``; frequency is WSJT-X's Tx freq (Hz).
    """
    exchange: dict[str, str] = {}
    raw = (msg.exchange_recv or "").strip()
    if raw and contest is not None:
        try:
            exchange.update(contest.parse_exchange(raw))
        except Exception:  # noqa: BLE001 - keep the raw exchange if it doesn't fit
            exchange["exchange"] = raw
    elif raw:
        exchange["exchange"] = raw
    if msg.dx_grid:
        exchange["grid"] = msg.dx_grid.strip().upper()
    record: dict[str, object] = {
        "call": msg.dx_call.strip().upper(),
        "freq_hz": int(msg.tx_frequency),
        "mode": map_mode(msg.mode),
        "exchange": exchange,
        "rst_sent": msg.report_sent.strip() or None,
        "rst_rcvd": msg.report_recv.strip() or "599",
        # Content-derived id => duplicate UDP deliveries dedupe instead of stacking.
        "uuid": stable_uuid(msg),
    }
    # Use WSJT-X's reported QSO time (off, else on) so the log shows when the
    # contact actually happened, not when our listener received the packet.
    when = msg.date_time_off or msg.date_time_on
    if when is not None:
        record["timestamp"] = when
    return record
