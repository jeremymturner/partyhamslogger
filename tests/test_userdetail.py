"""Per-station detail: power / SWR / FT8-FT4 odd-even.

Pure + loopback only (no Qt). Covers the StationStatus wire round-trip (incl.
back-compat decode of a status dict missing the new fields), the pure
``tx_even_from_epoch`` / ``parse_tx_power`` derivations, that the engine stores
the fields when a StationStatus arrives, and that ``_station_row`` exposes them.
"""

from __future__ import annotations

from partyhams.core.clock import new_station_id
from partyhams.core.models import Mode
from partyhams.net.engine import SyncEngine
from partyhams.net.loopback import LoopbackBus, LoopbackTransport
from partyhams.net.protocol import StationStatus, decode, encode
from partyhams.wsjtx.convert import parse_tx_power, tx_even_from_epoch

NETWORK = "test-net"


# --- protocol round-trip -------------------------------------------------- #
def test_status_roundtrip_with_new_fields():
    msg = StationStatus(
        operator="N0AW",
        call="W7ABC",
        freq_hz=14_074_000,
        mode="FT8",
        power_w=5.0,
        swr=1.3,
        ft_tx_even=1,
    )
    data = encode(msg, NETWORK, "station-1")
    network, sender, decoded = decode(data)
    assert network == NETWORK
    assert sender == "station-1"
    assert isinstance(decoded, StationStatus)
    assert decoded.power_w == 5.0
    assert decoded.swr == 1.3
    assert decoded.ft_tx_even == 1
    assert decoded.freq_hz == 14_074_000
    assert decoded.mode == "FT8"


def test_status_decode_back_compat_defaults():
    """A status dict from an older peer (no new keys) decodes to unknown."""
    legacy = {
        "v": 1,
        "net": NETWORK,
        "sender": "old-peer",
        "type": "status",
        "operator": "K1OLD",
        "call": "K1OLD",
        "freq_hz": 7_040_000,
        "mode": "CW",
    }
    import json

    _, _, decoded = decode(json.dumps(legacy).encode("utf-8"))
    assert isinstance(decoded, StationStatus)
    assert decoded.power_w == 0.0
    assert decoded.swr == 0.0
    assert decoded.ft_tx_even == -1


# --- tx_even_from_epoch (pure) ------------------------------------------- #
def test_tx_even_ft8_15s_boundaries():
    # FT8: 15s slots within the minute -> indexes 0,1,2,3 = even,odd,even,odd.
    base = 1_700_000_000 - (1_700_000_000 % 60)  # a minute boundary
    assert tx_even_from_epoch(base + 0, "FT8") == 1  # 00s -> slot 0 (even)
    assert tx_even_from_epoch(base + 14, "FT8") == 1  # still slot 0
    assert tx_even_from_epoch(base + 15, "FT8") == 0  # slot 1 (odd)
    assert tx_even_from_epoch(base + 30, "FT8") == 1  # slot 2 (even)
    assert tx_even_from_epoch(base + 45, "FT8") == 0  # slot 3 (odd)


def test_tx_even_ft4_7p5s_boundaries():
    base = 1_700_000_000 - (1_700_000_000 % 60)
    assert tx_even_from_epoch(base + 0, "FT4") == 1  # slot 0 (even)
    assert tx_even_from_epoch(base + 7, "FT4") == 1  # still slot 0
    assert tx_even_from_epoch(base + 8, "FT4") == 0  # slot 1 (odd)
    assert tx_even_from_epoch(base + 15, "FT4") == 1  # slot 2 (even)


def test_tx_even_non_data_mode_unknown():
    assert tx_even_from_epoch(1_700_000_000, "CW") == -1
    assert tx_even_from_epoch(1_700_000_000, "SSB") == -1
    assert tx_even_from_epoch(1_700_000_000, "") == -1


def test_tx_even_case_insensitive():
    base = 1_700_000_000 - (1_700_000_000 % 60)
    assert tx_even_from_epoch(base + 15, "ft8") == 0


# --- parse_tx_power (pure) ----------------------------------------------- #
def test_parse_tx_power():
    assert parse_tx_power("5") == 5.0
    assert parse_tx_power("100 W") == 100.0
    assert parse_tx_power("  37.5  ") == 37.5
    assert parse_tx_power("") is None
    assert parse_tx_power("0") is None
    assert parse_tx_power("abc") is None


# --- engine stores the fields -------------------------------------------- #
async def test_engine_stores_status_fields():
    bus = LoopbackBus()
    transport = LoopbackTransport(bus, NETWORK, station_id=new_station_id())
    engine = SyncEngine(transport, operator="N0AW", call="W7ABC")
    msg = StationStatus(
        operator="K2PEER",
        call="K2PEER",
        freq_hz=14_074_000,
        mode="FT4",
        power_w=50.0,
        swr=1.5,
        ft_tx_even=0,
    )
    await engine._handle("peer-1", msg)
    info = engine.stations["peer-1"]
    assert info["power_w"] == 50.0
    assert info["swr"] == 1.5
    assert info["ft_tx_even"] == 0
    assert info["mode"] == "FT4"


# --- _station_row exposes the fields ------------------------------------- #
def _make_session():
    from partyhams.app.session import build_session

    return build_session(
        contest_id="arrl-field-day",
        my_call="W7ABC",
        operator="N0AW",
        sent_exchange={"class": "2A", "section": "OR"},
        power="low_150w",
        network=None,
    )


def test_station_row_exposes_peer_fields():
    s = _make_session()
    s.engine.stations["peer-1"] = {
        "operator": "K2PEER",
        "call": "K2PEER",
        "freq_hz": 14_074_000,
        "mode": "FT8",
        "power_w": 5.0,
        "swr": 1.2,
        "ft_tx_even": 1,
    }
    peer = next(r for r in s.roster() if r["station_id"] == "peer-1")
    assert peer["power_w"] == 5.0
    assert peer["swr"] == 1.2
    assert peer["ft_tx_even"] == 1


def test_station_row_self_defaults_unknown():
    s = _make_session()
    s.set_local_status(14_040_000, Mode.CW)
    me = next(r for r in s.roster() if r["is_self"])
    assert me["power_w"] == 0.0
    assert me["swr"] == 0.0
    assert me["ft_tx_even"] == -1


def test_set_local_status_broadcasts_power_and_even():
    s = _make_session()
    s.set_local_status(14_074_000, Mode.FT8, power_w=5.0, ft_tx_even=1)
    me = next(r for r in s.roster() if r["is_self"])
    assert me["power_w"] == 5.0
    assert me["ft_tx_even"] == 1
    # A later freq/mode-only update must not wipe the known power.
    s.set_local_status(14_074_000, Mode.FT8)
    me = next(r for r in s.roster() if r["is_self"])
    assert me["power_w"] == 5.0
