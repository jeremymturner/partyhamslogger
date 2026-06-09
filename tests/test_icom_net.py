"""IcomNet driver against a fake network Icom rig (loopback UDP)."""

from __future__ import annotations

import asyncio

from fake_icom_net import FakeIcomRadio

from partyhams.core.models import Mode
from partyhams.radio.base import Capability
from partyhams.radio.civ_protocol import CIV_ADDR_IC705, CIV_ADDR_IC7610
from partyhams.radio.icom_net import IcomNet


async def _connect(radio: FakeIcomRadio) -> IcomNet:
    host, port = await radio.start()
    drv = IcomNet(host, radio.username, radio.password,
                  civ_address=radio.civ_address, control_port=port)
    await asyncio.wait_for(drv.connect(), 5)
    return drv


async def test_connect_and_read_state():
    radio = FakeIcomRadio(civ_address=CIV_ADDR_IC7610)
    drv = await _connect(radio)
    try:
        state = await drv.read_state()
        assert state.freq_hz == 14_000_000
        assert state.mode is Mode.CW
    finally:
        await drv.disconnect()
        await radio.stop()


async def test_set_frequency_and_mode():
    radio = FakeIcomRadio(civ_address=CIV_ADDR_IC705, name="IC-705")
    drv = await _connect(radio)
    try:
        await drv.set_frequency(7_030_000)
        assert radio.freq == 7_030_000
        await drv.set_mode(Mode.USB)
        assert radio.mode_civ == 0x01  # USB
        # And the round-trip reads back what we set.
        state = await drv.read_state()
        assert state.freq_hz == 7_030_000
        assert state.mode is Mode.USB
    finally:
        await drv.disconnect()
        await radio.stop()


async def test_send_cw_and_caps():
    radio = FakeIcomRadio(civ_address=CIV_ADDR_IC7610)
    drv = await _connect(radio)
    try:
        await drv.send_cw("CQ TEST")
        await asyncio.sleep(0.05)
        assert radio.cw_sent == ["CQ TEST"]
        # IC-7610 advertises a sub-receiver; IC-705 does not.
        assert Capability.SUB_RECEIVER in drv.capabilities
    finally:
        await drv.disconnect()
        await radio.stop()


async def test_bad_password_fails_fast():
    radio = FakeIcomRadio()
    radio.reject_login = True
    host, port = await radio.start()
    drv = IcomNet(host, "user", "wrong", control_port=port)
    failed = False
    try:
        await asyncio.wait_for(drv.connect(), 5)
    except OSError as exc:
        failed = True
        assert "username/password" in str(exc)
    finally:
        await drv.disconnect()
        await radio.stop()
    assert failed
