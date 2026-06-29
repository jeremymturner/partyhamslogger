"""Icom CI-V: wire protocol + the IcomCIV client against a fake CI-V radio."""

from __future__ import annotations

from fake_civ import FakeCivSerial

from partyhams.core.models import Mode
from partyhams.radio.civ_protocol import (
    CIV_ADDR_IC705,
    CIV_ADDR_IC7300MK2,
    CIV_ADDR_IC7610,
    Frame,
    bcd_to_freq,
    build_frame,
    civ_to_mode,
    freq_to_bcd,
    mode_to_civ,
    parse_frames,
)
from partyhams.radio.icom_civ import IcomCIV


# --- protocol ------------------------------------------------------------- #
def test_freq_bcd_round_trip():
    for hz in (14_074_000, 7_030_000, 1_800_000, 148_000_000, 0):
        assert bcd_to_freq(freq_to_bcd(hz)) == hz
    # Known encoding: 14.074 MHz -> little-endian BCD.
    assert freq_to_bcd(14_074_000) == bytes([0x00, 0x40, 0x07, 0x14, 0x00])


def test_build_and_parse_frame():
    raw = build_frame(0xA4, 0xE0, bytes([0x03, 0x01, 0x02]))
    assert raw == bytes([0xFE, 0xFE, 0xA4, 0xE0, 0x03, 0x01, 0x02, 0xFD])
    frames, leftover = parse_frames(raw)
    assert leftover == b""
    assert frames == [Frame(to_addr=0xA4, from_addr=0xE0, payload=bytes([0x03, 0x01, 0x02]))]


def test_parse_multiple_and_incomplete():
    a = build_frame(0xE0, 0xA4, bytes([0x03]))
    b = build_frame(0xE0, 0xA4, bytes([0x04, 0x03]))
    frames, leftover = parse_frames(a + b + b"\xfe\xfe\xe0")  # trailing partial frame
    assert len(frames) == 2
    assert leftover == b"\xfe\xfe\xe0"


def test_mode_maps():
    assert civ_to_mode(0x03) is Mode.CW
    assert civ_to_mode(0x01) is Mode.USB
    assert mode_to_civ(Mode.LSB) == 0x00
    assert mode_to_civ(Mode.FT8) == 0x01  # data-USB


# --- client --------------------------------------------------------------- #
async def test_read_state():
    fake = FakeCivSerial(freq=14_074_000, mode=0x03, civ_address=CIV_ADDR_IC705)
    radio = IcomCIV("/dev/fake", civ_address=CIV_ADDR_IC705, serial_factory=lambda: fake)
    await radio.connect()

    state = await radio.read_state()
    assert state.freq_hz == 14_074_000
    assert state.mode is Mode.CW

    fake.freq = 7_030_000  # operator spins the dial, switches to USB
    fake.mode = 0x01
    state = await radio.read_state()
    assert state.freq_hz == 7_030_000
    assert state.mode is Mode.USB

    await radio.disconnect()
    assert fake.closed is True


async def test_set_frequency_and_mode():
    fake = FakeCivSerial()
    radio = IcomCIV("/dev/fake", serial_factory=lambda: fake)
    await radio.connect()

    await radio.set_frequency(7_030_000)
    assert fake.freq == 7_030_000
    await radio.set_mode(Mode.LSB)
    assert fake.mode == 0x00

    await radio.disconnect()


async def test_cw_and_stop_and_ptt():
    fake = FakeCivSerial()
    radio = IcomCIV("/dev/fake", serial_factory=lambda: fake)
    await radio.connect()

    await radio.set_ptt(True)
    assert fake.ptt == 0x01
    await radio.send_cw("CQ FD W7ABC")
    assert fake.cw_sent == ["CQ FD W7ABC"]
    await radio.stop_tx()
    assert fake.cw_stopped is True
    assert fake.ptt == 0x00  # PTT dropped on stop

    await radio.disconnect()


def test_ic7610_has_sub_receiver():
    from partyhams.radio.base import Capability

    r705 = IcomCIV("/dev/fake", civ_address=CIV_ADDR_IC705)
    r7610 = IcomCIV("/dev/fake", civ_address=CIV_ADDR_IC7610)
    assert not r705.supports(Capability.SUB_RECEIVER)
    assert r7610.supports(Capability.SUB_RECEIVER)


async def test_ic7300mk2_serial():
    # The IC-7300 MK2 defaults to CI-V address 0xB6 (manual p.58); the existing
    # serial driver handles it with no protocol changes — only the address differs.
    assert CIV_ADDR_IC7300MK2 == 0xB6
    fake = FakeCivSerial(freq=14_074_000, mode=0x03, civ_address=CIV_ADDR_IC7300MK2)
    radio = IcomCIV("/dev/fake", civ_address=CIV_ADDR_IC7300MK2, serial_factory=lambda: fake)
    await radio.connect()

    state = await radio.read_state()
    assert state.freq_hz == 14_074_000
    assert state.mode is Mode.CW
    assert "IC-7300 MK2" in radio.description()

    await radio.set_frequency(7_030_000)
    assert fake.freq == 7_030_000

    # The single-receiver MK2 must not claim the IC-7610's sub-receiver.
    from partyhams.radio.base import Capability

    assert not radio.supports(Capability.SUB_RECEIVER)

    await radio.disconnect()
