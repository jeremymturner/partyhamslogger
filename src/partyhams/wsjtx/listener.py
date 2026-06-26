"""Asyncio UDP listener for WSJT-X messages.

:class:`WsjtxListener` binds a UDP port (WSJT-X's default is 2237), parses every
datagram with the pure :mod:`partyhams.wsjtx.protocol`, and fans the result out
to caller-supplied callbacks. It remembers the address the last datagram came
from so :meth:`send_highlight` can reply to WSJT-X (e.g. to color a callsign
whose section we still need). Bad packets are dropped silently — a listener must
never crash the logger.

Both unicast and multicast binds are supported: if the configured host is a
multicast group (224.0.0.0/4) the socket joins it; otherwise it binds the host
directly (``""`` = all interfaces).
"""

from __future__ import annotations

import asyncio
import socket
import struct
from collections.abc import Callable

from partyhams.wsjtx.protocol import (
    Clear,
    Decode,
    QSOLogged,
    Status,
    encode_highlight_callsign,
    encode_reply,
    parse_message,
)

DEFAULT_PORT = 2237


def _is_multicast(host: str) -> bool:
    try:
        first = int(host.split(".")[0])
    except (ValueError, IndexError):
        return False
    return 224 <= first <= 239


class WsjtxListener:
    """Receives WSJT-X UDP datagrams and dispatches parsed messages.

    Callbacks (all optional) are invoked synchronously from the asyncio thread:
    ``on_qso_logged(QSOLogged)``, ``on_status(Status)``, ``on_decode(Decode)``,
    ``on_clear(Clear)``. Any exception raised by a callback is swallowed so one
    bad handler can't tear down the receive loop.
    """

    def __init__(
        self,
        *,
        port: int = DEFAULT_PORT,
        host: str = "",
        on_qso_logged: Callable[[QSOLogged], None] | None = None,
        on_status: Callable[[Status], None] | None = None,
        on_decode: Callable[[Decode], None] | None = None,
        on_clear: Callable[[Clear], None] | None = None,
    ) -> None:
        self.port = port
        self.host = host
        self.on_qso_logged = on_qso_logged
        self.on_status = on_status
        self.on_decode = on_decode
        self.on_clear = on_clear
        #: Address (host, port) of the most recently heard WSJT-X — the reply target.
        self.peer_addr: tuple[str, int] | None = None
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        sock = self._make_socket()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _WsjtxProtocol(self), sock=sock
        )

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def _make_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        if _is_multicast(self.host):
            sock.bind(("", self.port))
            mreq = struct.pack("=4sl", socket.inet_aton(self.host), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        else:
            sock.bind((self.host, self.port))
        sock.setblocking(False)
        return sock

    # ------------------------------------------------------------------ #
    # dispatch + reply
    # ------------------------------------------------------------------ #
    def _dispatch(self, data: bytes, addr: tuple[str, int]) -> None:
        message = parse_message(data)
        if message is None:
            return
        self.peer_addr = addr
        if isinstance(message, QSOLogged):
            self._fire(self.on_qso_logged, message)
        elif isinstance(message, Status):
            self._fire(self.on_status, message)
        elif isinstance(message, Decode):
            self._fire(self.on_decode, message)
        elif isinstance(message, Clear):
            self._fire(self.on_clear, message)

    @staticmethod
    def _fire(callback: Callable[..., None] | None, message: object) -> None:
        if callback is None:
            return
        try:
            callback(message)
        except Exception:  # noqa: BLE001 - a bad handler must not kill the loop
            pass

    def send_highlight(
        self,
        wsjtx_id: str,
        callsign: str,
        *,
        background: tuple[int, int, int, int] | None = None,
        foreground: tuple[int, int, int, int] | None = None,
        highlight_last: bool = False,
    ) -> bool:
        """Ask WSJT-X to color ``callsign``. Returns False if we can't send yet.

        Best-effort: needs both an open transport and a known WSJT-X address
        (learned from the first datagram we received).
        """
        if self._transport is None or self.peer_addr is None:
            return False
        data = encode_highlight_callsign(
            wsjtx_id,
            callsign,
            background=background,
            foreground=foreground,
            highlight_last=highlight_last,
        )
        try:
            self._transport.sendto(data, self.peer_addr)
        except OSError:
            return False
        return True

    def send_reply(self, wsjtx_id: str, decode) -> bool:  # noqa: ANN001 - protocol.Decode
        """Ask WSJT-X to answer ``decode`` (UDP equivalent of double-clicking it).
        Best-effort; returns False if we can't send yet."""
        if self._transport is None or self.peer_addr is None:
            return False
        try:
            self._transport.sendto(encode_reply(wsjtx_id, decode), self.peer_addr)
        except OSError:
            return False
        return True


class _WsjtxProtocol(asyncio.DatagramProtocol):
    """asyncio glue: hand each datagram to the listener's dispatcher."""

    def __init__(self, owner: WsjtxListener) -> None:
        self._owner = owner

    def datagram_received(self, data: bytes, addr: object) -> None:
        if isinstance(addr, tuple):
            self._owner._dispatch(data, addr)
