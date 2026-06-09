"""A minimal fake DX cluster for tests.

Prompts once for a login, records what the client sends, then emits a couple of
canned spot lines and closes the connection. No real network — bound to
``127.0.0.1:0`` like the other fake servers.
"""

from __future__ import annotations

import asyncio


class FakeCluster:
    def __init__(self, spots: list[str] | None = None) -> None:
        self.spots = spots or [
            "DX de W3LPL:     14025.0  DX0CALL      CW 599              1234Z",
            "DX de VE7CC:      7040.5  K1ABC        nice sig            1300Z",
        ]
        self.login: str | None = None
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> tuple[str, int]:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        host, port = self._server.sockets[0].getsockname()[:2]
        return host, port

    async def stop(self) -> None:
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
            writer.write(b"Please enter your callsign (login):\r\n")
            await writer.drain()
            raw = await reader.readline()  # the client's login response
            self.login = raw.decode(errors="replace").strip()
            for spot in self.spots:
                writer.write((spot + "\r\n").encode())
            writer.write(b"some chatter line, not a spot\r\n")
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()
