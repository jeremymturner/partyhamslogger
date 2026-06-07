"""FlexRadio client against a fake SmartSDR server, plus loopback discovery."""

from __future__ import annotations

import asyncio
import socket

from fake_flex import FakeFlex, build_discovery_packet

from partyhams.core.models import Mode
from partyhams.radio.flex import FlexRadio, discover


async def test_connect_handshake_and_read_state():
    fake = FakeFlex()
    host, port = await fake.start()
    radio = FlexRadio(host, port)
    await radio.connect()

    assert radio.version == "1.4.0.0"
    assert radio.handle == "1A2B3C4D"

    state = await radio.read_state()
    assert state.freq_hz == 14_074_000
    assert state.mode is Mode.USB

    band = radio.current_band()
    assert band is not None and band.label == "20m"

    info = radio.radio_info()
    assert info.model == "FLEX-6500"
    assert info.callsign == "W7ABC"

    slices = radio.slices()
    assert slices[0]["index"] == 0
    assert slices[0]["band"] == "20m"
    assert slices[0]["active"] is True

    assert "20" in radio.bands()  # band info captured from sub radio all

    await radio.disconnect()
    await fake.stop()


async def test_set_frequency_and_mode():
    fake = FakeFlex()
    host, port = await fake.start()
    radio = FlexRadio(host, port)
    await radio.connect()

    await radio.set_frequency(7_030_000)
    assert fake.slices[0]["RF_frequency"] == "7.030000"
    # The status push updates our state before the command reply returns.
    assert (await radio.read_state()).freq_hz == 7_030_000

    await radio.set_mode(Mode.LSB)
    assert fake.slices[0]["mode"] == "LSB"
    assert (await radio.read_state()).mode is Mode.LSB

    await radio.disconnect()
    await fake.stop()


async def test_discover_loopback():
    # Find a free UDP port, then run discovery on it and unicast a packet to it.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    task = asyncio.create_task(discover(timeout=0.4, port=port))
    await asyncio.sleep(0.05)  # let the listener bind
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.sendto(
        build_discovery_packet({"model": "FLEX-6500", "serial": "S1", "ip": "192.168.1.77"}),
        ("127.0.0.1", port),
    )
    sender.close()

    radios = await task
    assert any(r.model == "FLEX-6500" and r.ip == "192.168.1.77" for r in radios)
