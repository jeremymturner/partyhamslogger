"""Unit tests for DX-cluster spot parsing and the async client (fake server)."""

from __future__ import annotations

import asyncio

from fake_cluster import FakeCluster

from partyhams.cluster import DEFAULT_CLUSTERS, ClusterClient, parse_spot


def test_parse_basic_spot():
    spot = parse_spot("DX de W3LPL:     14025.0  DX0CALL      CW 599 NICE     1234Z")
    assert spot is not None
    assert spot.spotter == "W3LPL"
    assert spot.dx_call == "DX0CALL"
    assert spot.freq_hz == 14_025_000  # kHz -> Hz
    assert spot.band == "20m"
    assert spot.time == "1234Z"
    assert "CW 599 NICE" in spot.comment


def test_parse_varying_whitespace_and_no_colon():
    spot = parse_spot("DX de VE7CC 7040.5 K1ABC strong 1300Z")
    assert spot is not None
    assert spot.spotter == "VE7CC"
    assert spot.dx_call == "K1ABC"
    assert spot.freq_hz == 7_040_500
    assert spot.band == "40m"
    assert spot.comment == "strong"
    assert spot.time == "1300Z"


def test_parse_no_comment():
    spot = parse_spot("DX de K3LR:   21300.0  W7XYZ   1500Z")
    assert spot is not None
    assert spot.dx_call == "W7XYZ"
    assert spot.freq_hz == 21_300_000
    assert spot.band == "15m"
    assert spot.comment == ""


def test_parse_lowercase_calls_uppercased():
    spot = parse_spot("DX de oh2aq: 14250.5 jw7abc nice 0900Z")
    assert spot is not None
    assert spot.spotter == "OH2AQ"
    assert spot.dx_call == "JW7ABC"
    assert spot.freq_hz == 14_250_500


def test_parse_out_of_band_freq():
    spot = parse_spot("DX de N0XYZ:   99999.0  TEST  comment  0001Z")
    assert spot is not None
    assert spot.band == "?"


def test_parse_three_digit_time():
    spot = parse_spot("DX de N1AAA: 14010.0 G3ABC  030Z")
    assert spot is not None
    assert spot.time == "030Z"


def test_non_spot_lines_return_none():
    for line in [
        "",
        "Please enter your callsign:",
        "login: ",
        "W3LPL de N0CALL 14-Jun-2026 1234Z dxspider >",
        "WWV de VE7CC <12>:   SFI=120, A=5, K=2",
        "Hello and welcome to the cluster",
        "DX de noidea",  # malformed: no freq/call
    ]:
        assert parse_spot(line) is None


def test_default_clusters_well_formed():
    assert DEFAULT_CLUSTERS
    seen_names = set()
    for entry in DEFAULT_CLUSTERS:
        assert len(entry) == 3
        name, host, port = entry
        assert isinstance(name, str) and name
        assert isinstance(host, str) and "." in host
        assert isinstance(port, int) and 0 < port < 65536
        assert name not in seen_names  # names are unique for the picker
        seen_names.add(name)


async def test_client_logs_in_and_parses_spots():
    fake = FakeCluster()
    host, port = await fake.start()
    spots = []
    statuses = []
    client = ClusterClient(
        host, port, "N0CALL", on_spot=spots.append, on_status=statuses.append
    )
    await client.connect()
    await asyncio.wait_for(client.run(), timeout=2.0)
    await client.disconnect()
    await fake.stop()

    assert fake.login == "N0CALL"  # we answered the login prompt
    assert [s.dx_call for s in spots] == ["DX0CALL", "K1ABC"]
    assert spots[0].freq_hz == 14_025_000
    assert spots[1].band == "40m"
    assert any("Logged in" in s for s in statuses)


async def test_client_supports_async_on_spot():
    fake = FakeCluster(spots=["DX de W1AW: 14000.0 K2XX hi 1200Z"])
    host, port = await fake.start()
    spots = []

    async def on_spot(spot):
        await asyncio.sleep(0)
        spots.append(spot)

    client = ClusterClient(host, port, "N0CALL", on_spot=on_spot)
    await client.connect()
    await asyncio.wait_for(client.run(), timeout=2.0)
    await client.disconnect()
    await fake.stop()

    assert len(spots) == 1
    assert spots[0].dx_call == "K2XX"
