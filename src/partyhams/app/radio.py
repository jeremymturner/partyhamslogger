"""RadioPoller — periodically reads the rig and reports state changes.

Wraps a :class:`~partyhams.radio.base.Radio` backend in an asyncio polling loop.
The UI subscribes via ``on_state`` to auto-fill band/mode/frequency from the rig.
Connection loss is non-fatal: the poller marks itself disconnected and keeps
trying to reconnect, so logging keeps working even if the radio (or rigctld) drops.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from partyhams.radio.base import Radio, RadioState


class RadioPoller:
    def __init__(
        self,
        radio: Radio,
        on_state: Callable[[RadioState], None] | None = None,
        on_status: Callable[[bool, str | None], None] | None = None,
        interval: float = 0.4,
    ) -> None:
        self.radio = radio
        self.on_state = on_state
        self.on_status = on_status  # (connected, error) callback
        self.interval = interval
        self.state: RadioState | None = None
        self.connected = False
        self.error: str | None = None
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Connect and begin polling. Raises if the initial connect fails."""
        await self.radio.connect()
        self._set_status(True, None)
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        try:
            await self.radio.disconnect()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    async def _loop(self) -> None:
        while self._running:
            try:
                state = await self.radio.read_state()
            except Exception as exc:  # noqa: BLE001 - connection hiccup -> reconnect
                self._set_status(False, str(exc))
                await asyncio.sleep(1.0)
                await self._try_reconnect()
                continue
            if not self.connected:
                self._set_status(True, None)
            if state != self.state:
                self.state = state
                if self.on_state is not None:
                    self.on_state(state)
            await asyncio.sleep(self.interval)

    async def _try_reconnect(self) -> None:
        try:
            await self.radio.disconnect()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self.radio.connect()
            self._set_status(True, None)
        except Exception as exc:  # noqa: BLE001 - keep trying next loop
            self._set_status(False, str(exc))

    def _set_status(self, connected: bool, error: str | None) -> None:
        self.connected = connected
        self.error = error
        if self.on_status is not None:
            self.on_status(connected, error)
