"""IcomNet driver against a fake network Icom rig (loopback UDP)."""

from __future__ import annotations

import asyncio

from fake_icom_net import FakeIcomRadio

from partyhams.core.models import Mode
from partyhams.radio.base import Capability
from partyhams.radio.civ_protocol import (
    CIV_ADDR_IC705,
    CIV_ADDR_IC7300MK2,
    CIV_ADDR_IC7610,
)
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


async def test_ic7300mk2_lan():
    # The IC-7300 MK2's built-in Ethernet speaks Icom's native UDP remote protocol
    # (same as the IC-705/IC-7610), so the existing LAN driver works once it knows
    # the MK2's CI-V address (0xB6). NOTE: unverified against real hardware.
    radio = FakeIcomRadio(civ_address=CIV_ADDR_IC7300MK2, name="IC-7300 MK2")
    drv = await _connect(radio)
    try:
        state = await drv.read_state()
        assert state.freq_hz == 14_000_000
        assert state.mode is Mode.CW
        assert "IC-7300 MK2" in drv.description()
        # Single-receiver radio: must not advertise the IC-7610's sub-receiver.
        assert Capability.SUB_RECEIVER not in drv.capabilities

        await drv.set_frequency(7_030_000)
        assert radio.freq == 7_030_000
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


async def test_verify_reachable_answers_are_you_there():
    """The settings-dialog probe gets "I am here" from a live rig on UDP."""
    from partyhams.radio.icom_net import verify_reachable

    radio = FakeIcomRadio()
    host, port = await radio.start()
    try:
        assert await asyncio.to_thread(verify_reachable, host, port, 1.0) is True
    finally:
        await radio.stop()


def test_verify_reachable_no_radio():
    import socket

    from partyhams.radio.icom_net import verify_reachable

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))  # a UDP port that never replies
    port = sock.getsockname()[1]
    try:
        assert verify_reachable("127.0.0.1", port, timeout=0.3) is False
    finally:
        sock.close()
    assert verify_reachable("", port) is False


async def test_disconnect_releases_session_for_reconnect():
    """A clean disconnect deletes the login token, so the rig accepts the next session.

    A real IC-7610 refuses a new session (status error 0xFFFFFFFF) while the previous
    one is still held — restarting the app used to hit this for about a minute.
    """
    radio = FakeIcomRadio()
    host, port = await radio.start()
    try:
        for _ in range(2):
            drv = IcomNet(host, "user", "pass", civ_address=CIV_ADDR_IC7610, control_port=port)
            await asyncio.wait_for(drv.connect(), 5)
            assert (await drv.read_state()).freq_hz == radio.freq
            await drv.disconnect()
            await asyncio.sleep(0.05)  # let the token delete land
        assert radio.tokens_deleted == 2
        assert radio.session_token is None
    finally:
        await radio.stop()


async def test_busy_radio_fails_fast_with_clear_message():
    radio = FakeIcomRadio()
    radio.session_token = 0xDEAD  # someone else (or a stale session) holds the rig
    host, port = await radio.start()
    drv = IcomNet(host, "user", "pass", civ_address=CIV_ADDR_IC7610, control_port=port)
    loop = asyncio.get_running_loop()
    start = loop.time()
    try:
        try:
            await asyncio.wait_for(drv.connect(), 5)
            raise AssertionError("connect should have been refused")
        except OSError as exc:
            assert "previous session" in str(exc)
        assert loop.time() - start < 2  # refused immediately, not after the 10 s timeout
    finally:
        await drv.disconnect()
        await radio.stop()


async def test_token_is_renewed_periodically(monkeypatch):
    """An IC-7610 stops serving a session ~90 s after login unless the token is renewed."""
    import partyhams.radio.icom_net as icom_net

    monkeypatch.setattr(icom_net, "_TOKEN_RENEW_INTERVAL", 0.05)
    radio = FakeIcomRadio()
    host, port = await radio.start()
    drv = IcomNet(host, "user", "pass", civ_address=CIV_ADDR_IC7610, control_port=port)
    try:
        await asyncio.wait_for(drv.connect(), 5)
        await asyncio.sleep(0.3)
        assert radio.tokens_renewed >= 3
        assert (await drv.read_state()).freq_hz == radio.freq
    finally:
        await drv.disconnect()
        await radio.stop()


async def test_rejected_renewal_fails_next_command(monkeypatch):
    import partyhams.radio.icom_net as icom_net

    monkeypatch.setattr(icom_net, "_TOKEN_RENEW_INTERVAL", 0.05)
    radio = FakeIcomRadio()
    radio.reject_renewal = True
    host, port = await radio.start()
    drv = IcomNet(host, "user", "pass", civ_address=CIV_ADDR_IC7610, control_port=port)
    try:
        await asyncio.wait_for(drv.connect(), 5)
        await asyncio.sleep(0.2)
        try:
            await drv.read_state()
            raise AssertionError("read_state should fail once the session expired")
        except OSError as exc:
            assert "token renewal" in str(exc)
    finally:
        await drv.disconnect()
        await radio.stop()


async def test_same_instance_reconnects():
    """RadioPoller reconnects with disconnect()+connect() on the same driver object."""
    radio = FakeIcomRadio()
    host, port = await radio.start()
    drv = IcomNet(host, "user", "pass", civ_address=CIV_ADDR_IC7610, control_port=port)
    try:
        for freq in (14_000_000, 7_030_000):
            radio.freq = freq
            await asyncio.wait_for(drv.connect(), 5)
            assert (await drv.read_state()).freq_hz == freq
            await drv.disconnect()
            await asyncio.sleep(0.05)
    finally:
        await drv.disconnect()
        await radio.stop()


async def test_silent_radio_raises_instead_of_zero_hz():
    radio = FakeIcomRadio()
    host, port = await radio.start()
    drv = IcomNet(host, "user", "pass", civ_address=CIV_ADDR_IC7610, control_port=port)
    try:
        await asyncio.wait_for(drv.connect(), 5)
        radio.silent = True
        try:
            await drv.read_state()
            raise AssertionError("a silent radio must not read as 0 Hz")
        except OSError as exc:
            assert "no response" in str(exc)
    finally:
        await drv.disconnect()
        await radio.stop()


async def test_poller_recovers_after_session_drop():
    """End to end: radio goes silent mid-session -> poller reports it and logs in again."""
    from partyhams.app.radio import RadioPoller

    radio = FakeIcomRadio()
    host, port = await radio.start()
    statuses: list[tuple[bool, str | None]] = []
    drv = IcomNet(host, "user", "pass", civ_address=CIV_ADDR_IC7610, control_port=port)
    poller = RadioPoller(drv, on_status=lambda c, e: statuses.append((c, e)), interval=0.05)
    try:
        await asyncio.wait_for(poller.start(), 5)
        radio.silent = True  # session dropped
        for _ in range(100):
            if not poller.connected:
                break
            await asyncio.sleep(0.05)
        assert not poller.connected
        radio.silent = False  # the new login is served again
        radio.freq = 21_025_000
        for _ in range(100):
            if poller.connected and poller.state and poller.state.freq_hz == 21_025_000:
                break
            await asyncio.sleep(0.05)
        assert poller.connected
        assert poller.state.freq_hz == 21_025_000
        assert any(not c for c, _ in statuses)
    finally:
        await poller.stop()
        await radio.stop()


async def test_lan_keyer_speed_and_long_cw():
    radio = FakeIcomRadio(civ_address=CIV_ADDR_IC7610)
    drv = await _connect(radio)
    try:
        assert Capability.KEYER_SPEED in drv.capabilities
        assert await drv.read_wpm() == 28
        await drv.send_cw("CQ CQ CQ DE WW8L WW8L WW8L CQ FIELD DAY K", wpm=20)
        assert await drv.read_wpm() == 20
        assert radio.cw_sent == ["CQ CQ CQ DE WW8L WW8L WW8L CQ ", "FIELD DAY K"]
        assert (await drv.read_state()).wpm == 20
    finally:
        await drv.disconnect()
        await radio.stop()
