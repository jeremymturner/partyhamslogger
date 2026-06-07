"""A fake FlexRadio for tests: a discovery-packet builder + a TCP control server.

Speaks enough of the SmartSDR protocol (V/H handshake, C->R commands, S status
pushes) to exercise the FlexRadio client without a real radio.
"""

from __future__ import annotations

import asyncio

from partyhams.radio.flex_protocol import FLEX_OUI, VITA_HEADER_BYTES


def build_discovery_packet(fields: dict[str, str]) -> bytes:
    """Build a VITA-49 discovery datagram carrying ``fields`` as the payload."""
    header = bytearray(VITA_HEADER_BYTES)
    header[8:12] = (FLEX_OUI & 0x00FFFFFF).to_bytes(4, "big")  # Class ID OUI
    payload = " ".join(f"{k}={v}" for k, v in fields.items()).encode("ascii")
    return bytes(header) + payload


class FakeFlex:
    def __init__(self, handle: str = "1A2B3C4D", version: str = "1.4.0.0") -> None:
        self.handle = handle
        self.version = version
        self.slices: dict[int, dict[str, str]] = {
            0: {
                "in_use": "1",
                "active": "1",
                "RF_frequency": "14.074000",
                "mode": "USB",
                "rxant": "ANT1",
            }
        }
        self.radio_status: dict[str, str] = {"model": "FLEX-6500", "callsign": "W7ABC"}
        self.bands: dict[str, dict[str, str]] = {"20": {"rfpower": "100", "tunepower": "10"}}
        self.cwx_sent: list[str] = []  # decoded CW text we were asked to send
        self.cw_wpm: str | None = None
        self.cwx_cleared = False
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
        except Exception:  # noqa: BLE001
            pass
        self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        writer.write(f"V{self.version}\n".encode())
        writer.write(f"H{self.handle}\n".encode())
        await writer.drain()
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace").rstrip("\r\n")
                if line.startswith("C"):
                    seq_str, _, cmd = line[1:].partition("|")
                    await self._exec(int(seq_str), cmd, writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    async def _exec(self, seq: int, cmd: str, writer: asyncio.StreamWriter) -> None:
        tokens = cmd.split()
        if cmd == "sub slice all":
            for idx in self.slices:
                self._push_slice(idx, writer)
        elif cmd == "sub radio all":
            self._push(f"radio {self._kv(self.radio_status)}", writer)
            for band_id, fields in self.bands.items():
                self._push(f"band {band_id} {self._kv(fields)}", writer)
        elif tokens[:2] == ["slice", "tune"]:
            idx = int(tokens[2])
            self.slices[idx]["RF_frequency"] = tokens[3]
            self._push_slice(idx, writer)
        elif tokens[:2] == ["slice", "set"]:
            idx = int(tokens[2])
            for tok in tokens[3:]:
                if "=" in tok:
                    key, _, value = tok.partition("=")
                    self.slices[idx][key] = value
            self._push_slice(idx, writer)
        elif tokens[:2] == ["cwx", "send"]:
            payload = cmd.split(" ", 2)[2] if len(tokens) >= 3 else ""
            self.cwx_sent.append(payload.replace("\x7f", " "))  # decode 0x7F -> space
        elif tokens[:2] == ["cwx", "wpm"]:
            self.cw_wpm = tokens[2]
        elif tokens[:2] == ["cwx", "clear"]:
            self.cwx_cleared = True
        # Acknowledge the command (0 == success).
        writer.write(f"R{seq}|0|\n".encode())

    def _push_slice(self, idx: int, writer: asyncio.StreamWriter) -> None:
        self._push(f"slice {idx} {self._kv(self.slices[idx])}", writer)

    def _push(self, payload: str, writer: asyncio.StreamWriter) -> None:
        writer.write(f"S{self.handle}|{payload}\n".encode())

    @staticmethod
    def _kv(fields: dict[str, str]) -> str:
        return " ".join(f"{k}={v}" for k, v in fields.items())
