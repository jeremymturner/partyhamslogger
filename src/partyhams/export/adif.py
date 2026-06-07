"""ADIF export — the universal log interchange format (LoTW/QRZ/eQSL, etc.).

Emits ADIF 3.x. Each field is ``<NAME:len>value``; records end with ``<EOR>``
and the header ends with ``<EOH>``. Contest exchange fields are flattened into
the standard ``STX_STRING`` / ``SRX_STRING`` fields.
"""

from __future__ import annotations

from collections.abc import Iterable

from partyhams import __version__
from partyhams.contest.base import ContestConfig, ContestDefinition
from partyhams.core.models import QSO, Mode

# our Mode -> ADIF MODE enumeration
_ADIF_MODE: dict[Mode, str] = {
    Mode.CW: "CW",
    Mode.USB: "SSB",
    Mode.LSB: "SSB",
    Mode.FM: "FM",
    Mode.AM: "AM",
    Mode.RTTY: "RTTY",
    Mode.PSK31: "PSK",
    Mode.FT8: "FT8",
    Mode.FT4: "FT4",
}


def _field(name: str, value: str) -> str:
    value = value or ""
    return f"<{name}:{len(value)}>{value}"


def _adif_band(label: str) -> str:
    # "20m" -> "20M"; passthrough for anything unexpected.
    return label.upper()


def _exchange_string(exchange: dict[str, str]) -> str:
    return " ".join(str(v) for v in exchange.values() if v)


def qso_to_adif(qso: QSO, config: ContestConfig) -> str:
    parts = [
        _field("CALL", qso.call.upper()),
        _field("QSO_DATE", qso.timestamp.strftime("%Y%m%d")),
        _field("TIME_ON", qso.timestamp.strftime("%H%M%S")),
        _field("BAND", _adif_band(qso.band_label)),
        _field("FREQ", f"{qso.freq_hz / 1_000_000:.6f}"),
        _field("MODE", _ADIF_MODE.get(qso.mode, qso.mode.value)),
        _field("RST_SENT", qso.rst_sent),
        _field("RST_RCVD", qso.rst_rcvd),
        _field("OPERATOR", qso.operator.upper()),
        _field("STATION_CALLSIGN", config.my_call.upper()),
    ]
    sent = _exchange_string(config.sent_exchange)
    rcvd = _exchange_string(qso.exchange_rcvd)
    if sent:
        parts.append(_field("STX_STRING", sent))
    if rcvd:
        parts.append(_field("SRX_STRING", rcvd))
    return "".join(parts) + "<EOR>"


def write_adif(
    qsos: Iterable[QSO],
    config: ContestConfig,
    contest: ContestDefinition | None = None,
) -> str:
    """Render a full ADIF document (header + records) as a string."""
    header_lines = [
        "PartyHams Logger ADIF export",
        _field("ADIF_VER", "3.1.4"),
        _field("PROGRAMID", "PartyHams"),
        _field("PROGRAMVERSION", __version__),
    ]
    if contest is not None and contest.cabrillo_name:
        header_lines.append(_field("CONTEST_ID", contest.cabrillo_name))
    header = "\n".join(header_lines) + "<EOH>\n"

    body = "\n".join(qso_to_adif(q, config) for q in qsos if not q.deleted)
    return header + body + ("\n" if body else "")
