"""A minimal fake ``rigctld`` for tests.

Speaks enough of Hamlib's *extended* response protocol (commands prefixed with
``+``, replies terminated by an ``RPRT`` line) to exercise our HamlibRadio client
without real hardware. State is mutable so a test can simulate the operator
turning the dial (set ``.freq`` / ``.mode``) between polls.
"""

from __future__ import annotations

import asyncio


class FakeRigctld:
    def __init__(self, freq: int = 14_074_000, mode: str = "CW", passband: int = 500) -> None:
        self.freq = freq
        self.mode = mode
        self.passband = passband
        self.ptt = "0"
        self.morse: list[str] = []
        self.morse_stopped = False
        self.levels: dict[str, str] = {}
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> tuple[str, int]:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        host, port = self._server.sockets[0].getsockname()[:2]
        return host, port

    async def stop(self) -> None:
        """Shut down, dropping any open client connections (like a dying rigctld).

        We must close active connections ourselves: on Python 3.13+,
        ``Server.wait_closed()`` blocks until all connections are gone, so leaving
        a client's socket open here would deadlock.
        """
        if self._server is None:
            return
        for writer in list(self._writers):
            writer.close()
        self._server.close()
        try:
            await self._server.wait_closed()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace").strip()
                if line.startswith("+"):
                    line = line[1:]
                if not line:
                    continue
                writer.write(self._respond(line).encode())
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    def _respond(self, line: str) -> str:
        parts = line.split()
        cmd, args = parts[0], parts[1:]
        if cmd == "f":  # get_freq
            return f"get_freq:\nFrequency: {self.freq}\nRPRT 0\n"
        if cmd == "F":  # set_freq
            self.freq = int(args[0])
            return f"set_freq: {args[0]}\nRPRT 0\n"
        if cmd == "m":  # get_mode
            return f"get_mode:\nMode: {self.mode}\nPassband: {self.passband}\nRPRT 0\n"
        if cmd == "M":  # set_mode
            self.mode = args[0]
            if len(args) > 1:
                self.passband = int(args[1])
            return f"set_mode: {' '.join(args)}\nRPRT 0\n"
        if cmd == "T":  # set_ptt
            self.ptt = args[0]
            return f"set_ptt: {args[0]}\nRPRT 0\n"
        if cmd == "b":  # send_morse
            text = line.split(" ", 1)[1] if " " in line else ""
            self.morse.append(text)
            return f"send_morse: {text}\nRPRT 0\n"
        if cmd == "\\stop_morse":  # abort CW
            self.morse_stopped = True
            return "stop_morse:\nRPRT 0\n"
        if cmd == "L":  # set_level
            if len(args) >= 2:
                self.levels[args[0]] = args[1]
            return f"set_level: {' '.join(args)}\nRPRT 0\n"
        return "RPRT -11\n"  # not implemented
