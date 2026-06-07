"""RadioPoller against a fake rigctld: reports changes, survives disconnects."""

from __future__ import annotations

import asyncio

from fake_rigctld import FakeRigctld

from partyhams.app.radio import RadioPoller
from partyhams.core.models import Mode
from partyhams.radio.hamlib import HamlibRadio


async def test_poller_reports_dial_changes():
    fake = FakeRigctld(freq=14_074_000, mode="CW")
    host, port = await fake.start()
    states = []
    poller = RadioPoller(HamlibRadio(host, port), on_state=states.append, interval=0.02)
    await poller.start()
    await asyncio.sleep(0.06)  # let it read the initial state

    fake.freq = 21_300_000  # operator spins the dial
    fake.mode = "USB"
    await asyncio.sleep(0.1)
    await poller.stop()
    await fake.stop()

    freqs = [s.freq_hz for s in states]
    assert 14_074_000 in freqs
    assert 21_300_000 in freqs
    assert poller.state is not None
    assert poller.state.mode is Mode.USB


async def test_poller_survives_radio_drop():
    fake = FakeRigctld()
    host, port = await fake.start()
    statuses = []
    poller = RadioPoller(
        HamlibRadio(host, port),
        on_status=lambda connected, err: statuses.append(connected),
        interval=0.02,
    )
    await poller.start()
    await asyncio.sleep(0.05)
    assert poller.connected is True

    await fake.stop()  # rigctld goes away
    await asyncio.sleep(0.2)
    assert poller.connected is False  # noticed the drop, didn't crash

    await poller.stop()
    assert False in statuses
