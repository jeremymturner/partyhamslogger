"""Icom CI-V: wire protocol + the IcomCIV client against a fake CI-V radio."""

from __future__ import annotations

import pytest
from fake_civ import FakeCivSerial

from partyhams.core.models import Mode
from partyhams.radio import icom_civ
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


# --- serial speed auto-detect + safe port open ------------------------------ #
@pytest.mark.parametrize("rig_baud", [115200, 19200, 9600, 4800])
async def test_connect_auto_detects_baud(rig_baud):
    fake = FakeCivSerial(freq=28_177_000, civ_address=CIV_ADDR_IC7610)
    fake.required_baud = rig_baud
    radio = IcomCIV("/dev/fake", civ_address=CIV_ADDR_IC7610, serial_factory=lambda: fake)
    await radio.connect()
    assert radio.baud == rig_baud
    assert (await radio.read_state()).freq_hz == 28_177_000
    await radio.disconnect()


async def test_connect_fails_clearly_when_nothing_answers():
    fake = FakeCivSerial(civ_address=CIV_ADDR_IC7610)
    fake.required_baud = 1200  # a speed we never try
    radio = IcomCIV("/dev/cu.wrong", civ_address=CIV_ADDR_IC7610, serial_factory=lambda: fake)
    with pytest.raises(OSError, match=r"no CI-V reply from /dev/cu.wrong.*0x98"):
        await radio.connect()
    assert fake.closed  # the port isn't left open after a failed connect


async def test_explicit_baud_is_not_scanned():
    fake = FakeCivSerial(civ_address=CIV_ADDR_IC7610)
    fake.required_baud = 115200
    radio = IcomCIV("/dev/fake", baud=19200, civ_address=CIV_ADDR_IC7610,
                    serial_factory=lambda: fake)
    with pytest.raises(OSError, match=r"tried 19200 baud"):
        await radio.connect()


def test_port_opens_with_rts_dtr_low(monkeypatch):
    """pyserial raises RTS/DTR by default; rigs set to key TX on them must not transmit."""
    import serial

    seen = {}

    class RecordingSerial:
        def __init__(self):
            self.rts = True
            self.dtr = True

        def open(self):
            seen["rts"], seen["dtr"] = self.rts, self.dtr

    monkeypatch.setattr(serial, "Serial", RecordingSerial)
    icom_civ.IcomCIV("/dev/fake")._open()
    assert seen == {"rts": False, "dtr": False}


def test_parse_frames_survives_any_read_split():
    """Serial reads can split a frame anywhere — including between the two 0xFE bytes."""
    echo = build_frame(CIV_ADDR_IC7610, 0xE0, b"\x03")
    reply = build_frame(0xE0, CIV_ADDR_IC7610, b"\x03\x00\x20\x19\x28\x00")
    stream = echo + reply
    for cut in range(1, len(stream)):
        got = []
        frames, rest = parse_frames(stream[:cut])
        got += frames
        frames, rest = parse_frames(rest + stream[cut:])
        got += frames
        assert [f.payload for f in got] == [b"\x03", b"\x03\x00\x20\x19\x28\x00"], cut


def test_parse_frames_byte_at_a_time():
    reply = build_frame(0xE0, CIV_ADDR_IC7610, b"\x04\x03\x01")
    buf, got = b"", []
    for i in range(len(reply)):
        frames, buf = parse_frames(buf + reply[i : i + 1])
        got += frames
    assert [f.payload for f in got] == [b"\x04\x03\x01"]


# --- CW keyer speed + long messages ------------------------------------- #
@pytest.mark.parametrize(("wpm", "level"), [(6, "0000"), (28, "0134"), (48, "0255")])
def test_wpm_level_encoding(wpm, level):
    from partyhams.radio.civ_protocol import level_to_wpm, wpm_to_level

    assert wpm_to_level(wpm).hex() == level
    assert level_to_wpm(bytes.fromhex(level)) == wpm


def test_every_wpm_round_trips_and_out_of_range_clamps():
    from partyhams.radio.civ_protocol import level_to_wpm, wpm_to_level

    assert all(level_to_wpm(wpm_to_level(w)) == w for w in range(6, 49))
    assert wpm_to_level(2) == wpm_to_level(6)
    assert wpm_to_level(60) == wpm_to_level(48)


def test_cw_chunks_split_at_30_on_word_breaks():
    from partyhams.radio.civ_protocol import cw_chunks

    text = "cq cq cq de ww8l ww8l ww8l test k"  # 33 characters
    chunks = cw_chunks(text)
    assert all(len(c) <= 30 for c in chunks)
    assert b"".join(chunks).decode() == text.upper()
    assert chunks[0] == b"CQ CQ CQ DE WW8L WW8L WW8L "  # cut at a space, gap kept


def test_cw_chunks_drop_unsendable_and_split_long_words():
    from partyhams.radio.civ_protocol import cw_chunks

    assert cw_chunks("5nn {oh}*") == [b"5NN OH"]
    assert cw_chunks("") == []
    assert [len(c) for c in cw_chunks("A" * 65)] == [30, 30, 5]


async def test_icom_keyer_speed_read_set_and_in_state():
    from partyhams.radio.base import Capability

    fake = FakeCivSerial()
    radio = IcomCIV("/dev/fake", serial_factory=lambda: fake)
    await radio.connect()
    assert radio.supports(Capability.KEYER_SPEED)
    assert await radio.read_wpm() == 28
    await radio.set_wpm(22)
    assert await radio.read_wpm() == 22
    assert (await radio.read_state()).wpm == 22
    await radio.disconnect()


async def test_send_cw_sets_speed_then_sends_in_pieces():
    fake = FakeCivSerial()
    radio = IcomCIV("/dev/fake", serial_factory=lambda: fake)
    await radio.connect()
    await radio.send_cw("CQ CQ CQ DE WW8L WW8L WW8L CQ FIELD DAY K", wpm=32)
    assert await radio.read_wpm() == 32
    assert fake.cw_sent == ["CQ CQ CQ DE WW8L WW8L WW8L CQ ", "FIELD DAY K"]
    await radio.disconnect()


async def test_send_cw_without_wpm_keeps_rig_speed():
    fake = FakeCivSerial()
    radio = IcomCIV("/dev/fake", serial_factory=lambda: fake)
    await radio.connect()
    await radio.send_cw("TU")
    assert await radio.read_wpm() == 28
    await radio.disconnect()


async def test_send_cw_raises_when_rig_rejects():
    fake = FakeCivSerial()
    radio = IcomCIV("/dev/fake", serial_factory=lambda: fake)
    await radio.connect()
    fake._ack = lambda ok: fake._reply(b"\xfa")  # rig NGs everything
    with pytest.raises(OSError, match="rejected CW"):
        await radio.send_cw("TEST")
    await radio.disconnect()


def test_cw_chunks_never_split_a_prosign():
    from partyhams.radio.civ_protocol import cw_chunks

    for pad in (27, 28, 29, 30):
        chunks = cw_chunks("A" * pad + "^AR")
        assert b"".join(chunks) == b"A" * pad + b"^AR"
        assert all(len(c) <= 30 for c in chunks)
        assert any(c.startswith(b"^AR") or b"^AR" in c for c in chunks), chunks


async def test_stop_between_pieces_drops_the_rest_of_the_message():
    fake = FakeCivSerial()
    radio = IcomCIV("/dev/fake", serial_factory=lambda: fake)
    await radio.connect()
    real_transact = radio._transact

    async def transact(payload, *a, **kw):
        result = await real_transact(payload, *a, **kw)
        if payload[0] == 0x17 and payload[1:] != b"\xff" and len(fake.cw_sent) == 1:
            await radio.stop_tx()  # Esc lands right after the first piece
        return result

    radio._transact = transact
    await radio.send_cw("CQ CQ CQ DE WW8L WW8L WW8L CQ FIELD DAY K")
    assert fake.cw_sent == ["CQ CQ CQ DE WW8L WW8L WW8L CQ "]  # piece 2 never sent
    assert fake.cw_stopped
    radio._transact = real_transact
    await radio.send_cw("TU")  # the next message is unaffected
    assert fake.cw_sent[-1] == "TU"
    await radio.disconnect()


async def test_keyer_speed_poll_stops_after_repeated_silence():
    fake = FakeCivSerial()
    radio = IcomCIV("/dev/fake", serial_factory=lambda: fake)
    await radio.connect()
    real_handle = fake._handle
    asked = []

    def no_keyer(payload):
        if payload[:2] == b"\x14\x0c":
            asked.append(payload)
            return  # a rig that never answers the keyer-speed read
        real_handle(payload)

    fake._handle = no_keyer
    for _ in range(5):
        assert (await radio.read_state()).wpm is None
    assert len(asked) == 3  # gave up after three misses; freq/mode polls continue
    await radio.disconnect()
    await radio.connect()  # a fresh connection tries again
    fake._handle = real_handle
    assert (await radio.read_state()).wpm == 28
    await radio.disconnect()


def test_port_opens_locked(monkeypatch):
    import serial

    seen = {}

    class RecordingSerial:
        def open(self):
            seen["exclusive"] = self.exclusive

    monkeypatch.setattr(serial, "Serial", RecordingSerial)
    icom_civ.IcomCIV("/dev/fake")._open()
    assert seen == {"exclusive": True}
