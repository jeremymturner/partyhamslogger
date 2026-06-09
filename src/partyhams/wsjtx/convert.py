"""Map a WSJT-X :class:`QSOLogged` onto our logging model.

Kept separate from both the pure protocol and the Qt UI so it can be unit-tested
directly. :func:`qso_logged_to_record` returns the keyword arguments for
:meth:`partyhams.app.session.LogSession.record_qso` (call / freq / mode /
exchange / reports); the session then stamps identity + merge metadata.
"""

from __future__ import annotations

from partyhams.core.models import Mode
from partyhams.wsjtx.protocol import QSOLogged

# WSJT-X mode strings -> our concrete Mode. WSJT-X reports many digital
# sub-modes (FT8, FT4, JT9, MSK144, ...); anything not FT4 maps to FT8's
# DIGITAL mode-group, which is what scoring/dupe rules key on.
_MODE_MAP: dict[str, Mode] = {
    "FT8": Mode.FT8,
    "FT4": Mode.FT4,
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
    """Best-effort WSJT-X mode string -> :class:`Mode` (default FT8/DIGITAL)."""
    return _MODE_MAP.get(mode.strip().upper(), Mode.FT8)


def qso_logged_to_record(msg: QSOLogged) -> dict[str, object]:
    """Build ``record_qso`` kwargs from a WSJT-X logged QSO.

    The received grid (and any free-form exchange WSJT-X carries) goes into
    ``exchange``; reports map to ``rst_sent``/``rst_rcvd``. The frequency is
    WSJT-X's dial/Tx frequency in Hz.
    """
    exchange: dict[str, str] = {}
    if msg.dx_grid:
        exchange["grid"] = msg.dx_grid.strip().upper()
    if msg.exchange_recv:
        exchange["exchange"] = msg.exchange_recv.strip()
    return {
        "call": msg.dx_call.strip().upper(),
        "freq_hz": int(msg.tx_frequency),
        "mode": map_mode(msg.mode),
        "exchange": exchange,
        "rst_sent": msg.report_sent.strip() or None,
        "rst_rcvd": msg.report_recv.strip() or "599",
    }
