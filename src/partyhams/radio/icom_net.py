"""Icom LAN (native UDP) backend — direct Ethernet/Wi-Fi to IC-705 / IC-7610 / IC-7300 MK2.

Connects straight to a network-equipped Icom rig (no serial bridge) using Icom's
proprietary UDP protocol — see ``radio/icom_net_protocol.py`` for the wire format.
Once the control stream authenticates and the CI-V stream opens, raw CI-V frames
tunnel over UDP, so this backend reuses the exact CI-V command set as the serial
backend via :class:`~partyhams.radio.civ_commands.CivRadio`.

Two UDP streams are used: *control* (login/keepalive) and *CI-V* (commands).
Audio (the third Icom stream) is never opened — a logger only needs control.

PROTOCOL NOTE: layouts are transcribed from wfview and exercised by a fake-radio
integration test, but this path has not yet been validated against real hardware.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time

from partyhams.radio import icom_net_protocol as proto
from partyhams.radio.base import RadioUnsupported
from partyhams.radio.civ_commands import CivRadio
from partyhams.radio.civ_protocol import (
    CIV_ADDR_IC705,
    CIV_ADDR_IC7300MK2,
    CIV_ADDR_IC7610,
    CONTROLLER_ADDR,
    build_frame,
    parse_frames,
)
from partyhams.radio.registry import register

log = logging.getLogger(__name__)

_MODEL_NAMES = {
    CIV_ADDR_IC705: "IC-705",
    CIV_ADDR_IC7610: "IC-7610",
    CIV_ADDR_IC7300MK2: "IC-7300 MK2",
}
_CONNECT_TIMEOUT = 10.0  # seconds to reach an authenticated, CI-V-open session
# Renew the login token this often (wfview: TOKEN_RENEWAL 60 s). An IC-7610 silently
# stops serving a session ~90 s after login if the token is never renewed.
_TOKEN_RENEW_INTERVAL = 60.0
_TRANSACT_TIMEOUT = 0.6


def verify_reachable(
    host: str, port: int = proto.DEFAULT_CONTROL_PORT, timeout: float = 2.0
) -> bool:
    """True if an Icom rig answers "are you there" on its UDP control port.

    Unauthenticated and side-effect free (a disconnect follows any reply), so it
    is safe to call from a settings dialog to check the IP/port before logging in.
    """
    if not host:
        return False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return False
    try:
        sock.connect((host, port))
        local_ip, local_port = sock.getsockname()[:2]
        my_id = proto.make_id(local_ip, local_port)
        attempts = 4
        sock.settimeout(timeout / attempts)
        for _ in range(attempts):
            sock.send(proto.control(proto.TYPE_AREYOUTHERE, 0, my_id, 0))
            try:
                data = sock.recv(2048)
            except TimeoutError:
                continue
            head = proto.parse_header(data)
            if head is not None and head.type == proto.TYPE_IAMHERE:
                sock.send(proto.control(proto.TYPE_DISCONNECT, 0, my_id, head.sentid))
                return True
        return False
    except OSError:
        return False
    finally:
        sock.close()


class _Stream(asyncio.DatagramProtocol):
    """One UDP stream to the radio: connect handshake, keepalive, retransmit.

    Generic over control vs CI-V — the differences are the ``on_ready`` callback
    (login vs open-stream) and how ``on_packet`` interprets non-handshake packets.
    """

    def __init__(self, local_ip: str, on_packet, on_ready, name: str) -> None:
        self.local_ip = local_ip
        self.on_packet = on_packet  # (data: bytes) -> None  for non-handshake packets
        self.on_ready = on_ready  # () -> None  fired once on "I am ready"
        self.name = name
        self.transport: asyncio.DatagramTransport | None = None
        self.radio_addr: tuple[str, int] | None = None
        self.my_id = 0
        self.remote_id = 0
        self.local_port = 0
        # common-header seq (LE @0x06), per tracked packet. Starts at 1 like wfview:
        # "are you ready" goes out untracked as seq 1 and the radio drops a first
        # tracked packet (the login) stamped seq 0, so the session never authenticates.
        self._send_seq = 1
        self._inner_seq = 0  # CI-V data/openclose sendseq (BE)
        self._ping_seq = 0
        self._tx_buffer: dict[int, bytes] = {}  # seq -> bytes, for retransmit honoring
        self._ready_fired = False
        self._tasks: list[asyncio.Task] = []
        self._closing = False

    # -- lifecycle -------------------------------------------------------- #
    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport
        self.local_port = transport.get_extra_info("sockname")[1]
        self.my_id = proto.make_id(self.local_ip, self.local_port)

    def start(self, radio_addr: tuple[str, int]) -> None:
        """Begin the handshake toward ``radio_addr`` (and keepalive loops)."""
        self.radio_addr = radio_addr
        self._tasks.append(asyncio.ensure_future(self._areyouthere_loop()))

    def close(self) -> None:
        self._closing = True
        for task in self._tasks:
            task.cancel()
        if self.transport is not None and self.radio_addr is not None:
            try:
                self._send(proto.control(proto.TYPE_DISCONNECT, 0, self.my_id, self.remote_id))
            except Exception:  # noqa: BLE001 - best effort on the way out
                pass
        if self.transport is not None:
            self.transport.close()

    # -- senders ---------------------------------------------------------- #
    def _send(self, data: bytes) -> None:
        if self.transport is not None and self.radio_addr is not None:
            self.transport.sendto(data, self.radio_addr)

    def _send_tracked(self, data: bytes) -> None:
        """Stamp the next seq, buffer for possible retransmit, and send."""
        buf = bytearray(data)
        buf[6:8] = (self._send_seq & 0xFFFF).to_bytes(2, "little")
        out = bytes(buf)
        self._tx_buffer[self._send_seq & 0xFFFF] = out
        if len(self._tx_buffer) > 256:
            self._tx_buffer.pop(next(iter(self._tx_buffer)))
        self._send_seq = (self._send_seq + 1) & 0xFFFF
        self._send(out)

    def send_idle(self) -> None:
        self._send_tracked(proto.control(proto.TYPE_IDLE, 0, self.my_id, self.remote_id))

    def send_civ(self, civ_frame: bytes) -> None:
        pkt = proto.civ_data(0, self.my_id, self.remote_id, self._inner_seq & 0xFFFF, civ_frame)
        self._inner_seq = (self._inner_seq + 1) & 0xFFFF
        self._send_tracked(pkt)

    def send_openclose(self, *, close: bool) -> None:
        pkt = proto.openclose(0, self.my_id, self.remote_id, self._inner_seq & 0xFFFF, close=close)
        self._inner_seq = (self._inner_seq + 1) & 0xFFFF
        self._send_tracked(pkt)

    # -- receive ---------------------------------------------------------- #
    def datagram_received(self, data: bytes, addr) -> None:
        head = proto.parse_header(data)
        if head is None:
            return
        if len(data) == proto.CONTROL_SIZE:
            self._handle_control(head, data)
            return
        if len(data) == proto.PING_SIZE and head.type == proto.TYPE_PING:
            self._handle_ping(head, data)
            return
        if head.type == proto.TYPE_RETRANSMIT:  # variable-length retransmit request
            self._handle_retransmit(data)
            return
        # Everything else (auth packets, CI-V data, capabilities) goes to the owner.
        if self.name == "control":
            log.debug("control: rx len=0x%02x type=0x%02x", len(data), head.type)
        self.on_packet(data)

    def _handle_control(self, head: proto.Header, data: bytes) -> None:
        if head.type == proto.TYPE_IAMHERE:
            log.debug("%s: I am here (remote id 0x%08x)", self.name, head.sentid)
            self.remote_id = head.sentid
            # Acknowledge with "are you ready" (untracked, seq=1) per the protocol.
            self._send(proto.control(proto.TYPE_READY, 1, self.my_id, self.remote_id))
        elif head.type == proto.TYPE_READY:  # "I am ready"
            self.remote_id = head.sentid
            if not self._ready_fired:
                log.debug("%s: I am ready", self.name)
                self._ready_fired = True
                self._tasks.append(asyncio.ensure_future(self._keepalive_loop()))
                self.on_ready()
        elif head.type == proto.TYPE_RETRANSMIT:  # single-packet retransmit request
            resend = self._tx_buffer.get(head.seq)
            if resend is not None:
                self._send(resend)
        elif head.type == proto.TYPE_DISCONNECT:
            log.debug("%s: radio sent disconnect", self.name)

    def _handle_ping(self, head: proto.Header, data: bytes) -> None:
        reply = data[0x10]
        if reply == 0x00:  # radio's ping request -> echo it back as a reply
            time_ms = int.from_bytes(data[0x11:0x15], "little")
            self._send(proto.ping(head.seq, self.my_id, self.remote_id, 0x01, time_ms))

    def _handle_retransmit(self, data: bytes) -> None:
        for off in range(0x10, len(data) - 1, 2):
            seq = int.from_bytes(data[off:off + 2], "little")
            resend = self._tx_buffer.get(seq)
            if resend is not None:
                self._send(resend)

    # -- keepalive loops -------------------------------------------------- #
    async def _areyouthere_loop(self) -> None:
        # Resend "are you there" until the handshake completes (ready fired).
        while not self._closing and not self._ready_fired:
            self._send(proto.control(proto.TYPE_AREYOUTHERE, 0, self.my_id, self.remote_id))
            await asyncio.sleep(0.5)

    async def _keepalive_loop(self) -> None:
        while not self._closing:
            time_ms = int(time.monotonic() * 1000) & 0xFFFFFFFF
            self._send(proto.ping(self._ping_seq, self.my_id, self.remote_id, 0x00, time_ms))
            self._ping_seq = (self._ping_seq + 1) & 0xFFFF
            self.send_idle()
            await asyncio.sleep(0.5)


@register
class IcomNet(CivRadio):
    backend_id = "icom-net"
    backend_name = "Icom LAN (native)"

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        civ_address: int = CIV_ADDR_IC705,
        control_port: int = proto.DEFAULT_CONTROL_PORT,
        client_name: str = "partyhams",
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.civ_address = civ_address
        self.control_port = control_port
        self.client_name = client_name[:16] or "partyhams"

        self._local_ip = "127.0.0.1"
        self._control: _Stream | None = None
        self._civ: _Stream | None = None
        self._lock = asyncio.Lock()

        # Auth/session state negotiated on the control stream.
        self._token = 0
        self._tokrequest = 0
        self._inner_auth_seq = 1
        self._chosen: proto.RadioCap | None = None
        self._audio_local_port = 0

        self._authed = asyncio.Event()
        self._civ_open = asyncio.Event()
        self._auth_error: str | None = None

        # CI-V receive plumbing (raw frames tunneled over the CI-V stream).
        self._civ_buf = b""
        self._civ_rx: asyncio.Queue[bytes] = asyncio.Queue()
        self._open_retry: asyncio.Task | None = None
        self._renew_task: asyncio.Task | None = None
        self._lost: str | None = None  # set when the radio drops the session

    def _reset_session(self) -> None:
        """Clear per-session state so the same instance can reconnect.

        RadioPoller reconnects by calling disconnect() then connect() on this same
        object; stale events/token/radio choice would otherwise make connect()
        return immediately without logging in.
        """
        self._token = 0
        self._tokrequest = 0
        self._inner_auth_seq = 1
        self._chosen = None
        self._authed = asyncio.Event()
        self._civ_open = asyncio.Event()
        self._auth_error = None
        self._civ_buf = b""
        self._civ_rx = asyncio.Queue()
        self._lost = None
        self._wpm_misses = 0

    def description(self) -> str:
        model = _MODEL_NAMES.get(self.civ_address, "LAN")
        return f"Icom {model} @ {self.host} (LAN)"

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> None:
        loop = asyncio.get_running_loop()
        self._reset_session()
        self._local_ip = self._detect_local_ip()
        self._audio_local_port = self._reserve_port()

        _, self._control = await loop.create_datagram_endpoint(
            lambda: _Stream(self._local_ip, self._on_control_packet, self._send_login, "control"),
            local_addr=(self._local_ip, 0),
        )
        # Pre-create the CI-V stream so we know its local port before requesting it.
        _, self._civ = await loop.create_datagram_endpoint(
            lambda: _Stream(self._local_ip, self._on_civ_packet, self._on_civ_ready, "civ"),
            local_addr=(self._local_ip, 0),
        )

        log.debug(
            "connect %s:%d from %s (control port %d, civ port %d, audio port %d)",
            self.host, self.control_port, self._local_ip, self._control.local_port,
            self._civ.local_port, self._audio_local_port,
        )
        self._control.start((self.host, self.control_port))
        try:
            # Auth failure also sets _authed (with _auth_error) so we fail fast.
            await asyncio.wait_for(self._authed.wait(), _CONNECT_TIMEOUT)
            if self._auth_error is not None:
                raise OSError(f"Icom LAN connect failed: {self._auth_error}")
            # A refused stream request also sets _civ_open (with _auth_error).
            await asyncio.wait_for(self._civ_open.wait(), _CONNECT_TIMEOUT)
            if self._auth_error is not None:
                raise OSError(f"Icom LAN connect failed: {self._auth_error}")
        except TimeoutError as exc:
            await self.disconnect()
            reason = self._auth_error or "no response from radio"
            log.debug("connect timed out: authed=%s civ_open=%s reason=%s",
                      self._authed.is_set(), self._civ_open.is_set(), reason)
            raise OSError(f"Icom LAN connect failed: {reason}") from exc
        except OSError:
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        if self._open_retry is not None:
            self._open_retry.cancel()
            self._open_retry = None
        if self._renew_task is not None:
            self._renew_task.cancel()
            self._renew_task = None
        # Release the session the way wfview does — close the CI-V data flow and
        # delete our login token before the per-stream "disconnect". Without this
        # the radio keeps the session reserved and refuses the next connection
        # (status error 0xFFFFFFFF) until it times the stale one out.
        if self._civ is not None and self._civ_open.is_set():
            self._civ.send_openclose(close=True)
        if self._control is not None and self._token:
            log.debug("control: deleting token")
            self._control._send_tracked(
                proto.token(self._control.my_id, self._control.remote_id, self._next_auth_seq(),
                            self._tokrequest, self._token, proto.TOKEN_DELETE)
            )
            self._token = 0
        for stream in (self._civ, self._control):
            if stream is not None:
                stream.close()
        self._civ = None
        self._control = None

    def _detect_local_ip(self) -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((self.host, self.control_port))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            sock.close()

    def _reserve_port(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self._local_ip, 0))
            return sock.getsockname()[1]
        finally:
            sock.close()

    # ------------------------------------------------------------------ #
    # control-stream handshake (login -> token -> capabilities -> stream)
    # ------------------------------------------------------------------ #
    def _send_login(self) -> None:
        # Fired when the control stream is "ready"; begin authentication.
        self._tokrequest = (int(time.monotonic() * 1e6) & 0xFFFF) or 0x1234
        pkt = proto.login(
            self._control.my_id, self._control.remote_id, self._next_auth_seq(),
            self._tokrequest, self.username, self.password, self.client_name,
        )
        log.debug("control: login sent (user=%r, tokrequest=0x%04x)",
                  self.username, self._tokrequest)
        self._control._send_tracked(pkt)

    def _next_auth_seq(self) -> int:
        seq = self._inner_auth_seq
        self._inner_auth_seq = (self._inner_auth_seq + 1) & 0xFFFF
        return seq

    def _on_control_packet(self, data: bytes) -> None:
        size = len(data)
        if size == proto.LOGIN_RESPONSE_SIZE:
            self._on_login_response(data)
        elif size == proto.STATUS_SIZE:
            self._on_status(data)
        elif size == proto.TOKEN_SIZE:
            self._on_token_response(data)
        elif proto.is_capabilities(data):
            self._on_capabilities(data)
        # Inbound CONNINFO (0x90) packets are informational; ignored.

    def _on_login_response(self, data: bytes) -> None:
        resp = proto.parse_login_response(data)
        log.debug("control: login response %s", {**resp, "token": "…"})
        if resp["error"] == 0xFEFFFFFF:
            self._auth_error = "invalid username/password"
            self._authed.set()  # release connect() so it fails fast
            return
        if resp["tokrequest"] != self._tokrequest:
            return  # not our login response
        self._token = resp["token"]
        # Confirm the token, then the radio sends its capabilities.
        pkt = proto.token(self._control.my_id, self._control.remote_id, self._next_auth_seq(),
                          self._tokrequest, self._token, proto.TOKEN_CONFIRM)
        self._control._send_tracked(pkt)
        self._authed.set()
        if self._renew_task is None:
            self._renew_task = asyncio.ensure_future(self._renew_loop())

    async def _renew_loop(self) -> None:
        while True:
            await asyncio.sleep(_TOKEN_RENEW_INTERVAL)
            if self._control is None or not self._token:
                return
            log.debug("control: renewing token")
            self._control._send_tracked(
                proto.token(self._control.my_id, self._control.remote_id, self._next_auth_seq(),
                            self._tokrequest, self._token, proto.TOKEN_RENEW)
            )

    def _on_token_response(self, data: bytes) -> None:
        resp = proto.parse_token_response(data)
        log.debug("control: token response type=0x%02x reply=0x%02x response=0x%08x",
                  resp["requesttype"], resp["requestreply"], resp["response"])
        if resp["requesttype"] == proto.TOKEN_RENEW and resp["response"] == 0xFFFFFFFF:
            # The radio no longer recognises our session; make the next command fail
            # so RadioPoller disconnects and logs in again.
            self._lost = "radio rejected token renewal (session expired)"

    def _on_capabilities(self, data: bytes) -> None:
        radios = proto.parse_capabilities(data)
        log.debug("control: capabilities %s",
                  [(r.name, hex(r.civ_address), r.use_guid) for r in radios])
        if not radios or self._chosen is not None:
            return
        # Prefer the radio matching the configured model; else take the first.
        self._chosen = next((r for r in radios if r.civ_address == self.civ_address), radios[0])
        pkt = proto.conninfo_request(
            self._control.my_id, self._control.remote_id, self._next_auth_seq(),
            self._tokrequest, self._token,
            name=self._chosen.name, username=self.username,
            use_guid=self._chosen.use_guid, guid=self._chosen.guid, mac=self._chosen.mac,
            civ_local_port=self._civ.local_port, audio_local_port=self._audio_local_port,
        )
        self._control._send_tracked(pkt)

    def _on_status(self, data: bytes) -> None:
        st = proto.parse_status(data)
        log.debug("control: status %s", st)
        if st["error"] == 0xFFFFFFFF:
            self._auth_error = (
                "radio refused the connection — it may still be holding a previous "
                "session (wait ~1 minute) or another program is connected"
            )
            self._authed.set()
            self._civ_open.set()  # release connect() now instead of timing out
            return
        if st["disconnected"] or not st["civ_port"]:
            return
        if self._civ is not None and self._civ.radio_addr is None:
            # The radio told us which port to talk CI-V on — open that stream.
            self._civ.start((self.host, st["civ_port"]))

    # ------------------------------------------------------------------ #
    # CI-V stream
    # ------------------------------------------------------------------ #
    def _on_civ_ready(self) -> None:
        # Ask the radio to start the CI-V data flow; resend until data arrives.
        log.debug("civ: stream ready, requesting open")
        self._civ.send_openclose(close=False)
        self._open_retry = asyncio.ensure_future(self._resend_open())
        self._civ_open.set()

    async def _resend_open(self) -> None:
        for _ in range(6):
            await asyncio.sleep(0.5)
            if self._civ is None or not self._civ_rx.empty():
                return
            self._civ.send_openclose(close=False)

    def _on_civ_packet(self, data: bytes) -> None:
        head = proto.parse_header(data)
        if head is None or head.type == proto.TYPE_RETRANSMIT:
            return
        if len(data) <= proto.DATA_HEADER_SIZE:  # not a CI-V data packet
            return
        self._civ_buf += proto.extract_civ(data)
        frames, self._civ_buf = parse_frames(self._civ_buf)
        for frame in frames:
            if frame.to_addr == CONTROLLER_ADDR and frame.payload:
                log.debug("civ: rx from=0x%02x payload=%s", frame.from_addr, frame.payload.hex())
                self._civ_rx.put_nowait(frame.payload)

    # ------------------------------------------------------------------ #
    # transport — CI-V transaction over the CI-V stream
    # ------------------------------------------------------------------ #
    async def _transact(
        self,
        payload: bytes,
        response_cmd: int | None = None,
        ack: bool = False,
        expect: bool = True,
    ) -> bytes | None:
        if self._civ is None or self._civ.radio_addr is None:
            raise RadioUnsupported("Icom LAN backend is not connected")
        if self._lost is not None:
            raise OSError(self._lost)
        async with self._lock:
            while not self._civ_rx.empty():  # drop stale/unsolicited frames
                self._civ_rx.get_nowait()
            self._civ.send_civ(build_frame(self.civ_address, CONTROLLER_ADDR, payload))
            if not expect:
                return None
            deadline = asyncio.get_running_loop().time() + _TRANSACT_TIMEOUT
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    log.debug("civ: no reply to %s", payload.hex())
                    return None
                try:
                    reply = await asyncio.wait_for(self._civ_rx.get(), remaining)
                except TimeoutError:
                    log.debug("civ: no reply to %s", payload.hex())
                    return None
                if ack and reply[0] in (0xFB, 0xFA):
                    return reply
                if not ack and response_cmd is not None and reply[0] == response_cmd:
                    return reply
