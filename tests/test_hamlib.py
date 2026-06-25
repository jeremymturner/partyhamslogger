"""HamlibRadio client against a fake rigctld (validates the rigctld protocol code)."""

from __future__ import annotations

from fake_rigctld import FakeRigctld

from partyhams.core.models import Mode
from partyhams.radio.hamlib import HamlibRadio


async def test_read_state():
    fake = FakeRigctld(freq=14_074_000, mode="CW")
    host, port = await fake.start()
    radio = HamlibRadio(host, port)
    await radio.connect()

    state = await radio.read_state()
    assert state.freq_hz == 14_074_000
    assert state.mode is Mode.CW

    # Simulate the operator spinning the dial and changing mode.
    fake.freq = 21_300_000
    fake.mode = "USB"
    state = await radio.read_state()
    assert state.freq_hz == 21_300_000
    assert state.mode is Mode.USB

    await radio.disconnect()
    await fake.stop()


async def test_set_frequency_and_mode():
    fake = FakeRigctld()
    host, port = await fake.start()
    radio = HamlibRadio(host, port)
    await radio.connect()

    await radio.set_frequency(7_030_000)
    assert fake.freq == 7_030_000
    await radio.set_mode(Mode.LSB)
    assert fake.mode == "LSB"

    await radio.disconnect()
    await fake.stop()


async def test_ptt_and_cw():
    fake = FakeRigctld()
    host, port = await fake.start()
    radio = HamlibRadio(host, port)
    await radio.connect()

    await radio.set_ptt(True)
    assert fake.ptt == "1"
    await radio.send_cw("TEST DE W7ABC", wpm=28)
    assert "TEST DE W7ABC" in fake.morse
    assert fake.levels.get("KEYSPD") == "28"

    await radio.disconnect()
    await fake.stop()


async def test_read_and_set_wpm():
    fake = FakeRigctld()
    host, port = await fake.start()
    radio = HamlibRadio(host, port)
    await radio.connect()

    await radio.set_wpm(22)
    assert fake.levels.get("KEYSPD") == "22"
    assert await radio.read_wpm() == 22

    # read_state surfaces the keyer speed once the rig reports it.
    state = await radio.read_state()
    assert state.wpm == 22

    await radio.disconnect()
    await fake.stop()


async def test_read_state_wpm_latches_off_when_unsupported():
    fake = FakeRigctld()
    host, port = await fake.start()
    radio = HamlibRadio(host, port)
    await radio.connect()

    # First poll probes KEYSPD, fails (no level), and disables further probes.
    state = await radio.read_state()
    assert state.wpm is None
    assert radio._keyspd_ok is False

    # Even after the operator sets a speed, we no longer poll it in read_state
    # (the latch stays off for the session) — but an explicit read still works.
    await radio.set_wpm(30)
    assert (await radio.read_state()).wpm is None
    assert await radio.read_wpm() == 30

    await radio.disconnect()
    await fake.stop()


async def test_stop_tx_aborts_cw_and_drops_ptt():
    fake = FakeRigctld()
    host, port = await fake.start()
    radio = HamlibRadio(host, port)
    await radio.connect()

    await radio.set_ptt(True)
    await radio.stop_tx()
    assert fake.morse_stopped is True
    assert fake.ptt == "0"

    await radio.disconnect()
    await fake.stop()


async def test_command_error_raises():
    fake = FakeRigctld()
    host, port = await fake.start()
    radio = HamlibRadio(host, port)
    await radio.connect()
    # The fake returns RPRT -11 for unknown commands; force one through _command.
    try:
        await radio._command("ZZZ")
        raise AssertionError("expected an error for an unsupported command")
    except OSError:
        pass
    await radio.disconnect()
    await fake.stop()
