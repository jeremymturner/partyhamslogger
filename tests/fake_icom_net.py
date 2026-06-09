"""A fake network-equipped Icom rig for tests.

Speaks enough of Icom's UDP protocol — control-stream handshake, login, token,
capabilities, stream request, and the CI-V data stream — to drive
:class:`~partyhams.radio.icom_net.IcomNet` over loopback without real hardware.
"""

from __future__ import annotations

import asyncio
import struct

from partyhams.radio import icom_net_protocol as proto
from partyhams.radio.civ_protocol import (
    CIV_ADDR_IC7610,
    CONTROLLER_ADDR,
    bcd_to_freq,
    build_frame,
    freq_to_bcd,
    parse_frames,
)

_RADIO_ID = 0x12345678
_TOKEN = 0xCAFEF00D


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, handler) -> None:
        self._handler = handler

    def datagram_received(self, data: bytes, addr) -> None:
        self._handler(data, addr)


class FakeIcomRadio:
    def __init__(self, civ_address: int = CIV_ADDR_IC7610, name: str = "IC-7610",
                 username: str = "user", password: str = "pass") -> None:
        self.civ_address = civ_address
        self.name = name
        self.username = username
        self.password = password
        self.freq = 14_000_000
        self.mode_civ = 0x03  # CW
        self.cw_sent: list[str] = []
        self.reject_login = False  # when True, answer logins with bad-credentials

        self._control: asyncio.DatagramTransport | None = None
        self._civ: asyncio.DatagramTransport | None = None
        self.control_port = 0
        self.civ_port = 0
        self._civ_send_seq = 0

    async def start(self) -> tuple[str, int]:
        loop = asyncio.get_running_loop()
        self._control, _ = await loop.create_datagram_endpoint(
            lambda: _Proto(self._on_control), local_addr=("127.0.0.1", 0)
        )
        self._civ, _ = await loop.create_datagram_endpoint(
            lambda: _Proto(self._on_civ), local_addr=("127.0.0.1", 0)
        )
        self.control_port = self._control.get_extra_info("sockname")[1]
        self.civ_port = self._civ.get_extra_info("sockname")[1]
        return "127.0.0.1", self.control_port

    async def stop(self) -> None:
        for t in (self._control, self._civ):
            if t is not None:
                t.close()

    # -- control stream --------------------------------------------------- #
    def _on_control(self, data: bytes, addr) -> None:
        head = proto.parse_header(data)
        if head is None:
            return
        size = len(data)
        if size == proto.CONTROL_SIZE:
            if head.type == proto.TYPE_AREYOUTHERE:
                self._control.sendto(
                    proto.control(proto.TYPE_IAMHERE, 0, _RADIO_ID, head.sentid), addr)
            elif head.type == proto.TYPE_READY:  # client's "are you ready"
                self._control.sendto(
                    proto.control(proto.TYPE_READY, 0, _RADIO_ID, head.sentid), addr)
        elif size == proto.PING_SIZE and head.type == proto.TYPE_PING and data[0x10] == 0:
            self._control.sendto(
                proto.ping(head.seq, _RADIO_ID, head.sentid, 0x01,
                           int.from_bytes(data[0x11:0x15], "little")), addr)
        elif size == proto.LOGIN_SIZE:
            self._send_login_response(data, addr)
        elif size == proto.TOKEN_SIZE:
            self._send_capabilities(head, addr)  # token confirm -> capabilities
        elif size == proto.CONNINFO_SIZE:
            self._send_status(head, addr)

    def _send_login_response(self, data: bytes, addr) -> None:
        tokrequest = struct.unpack_from("<H", data, 0x1A)[0]
        buf = bytearray(proto.LOGIN_RESPONSE_SIZE)
        buf[0:16] = struct.pack("<IHHII", proto.LOGIN_RESPONSE_SIZE, 0, 0, _RADIO_ID,
                                proto.parse_header(data).sentid)
        struct.pack_into("<H", buf, 0x1A, tokrequest)
        struct.pack_into("<I", buf, 0x1C, _TOKEN)
        struct.pack_into("<I", buf, 0x30, 0xFEFFFFFF if self.reject_login else 0)
        buf[0x40:0x46] = b"WFVIEW"
        self._control.sendto(bytes(buf), addr)

    def _send_capabilities(self, head: proto.Header, addr) -> None:
        cap = bytearray(proto.CAPABILITIES_SIZE)
        cap[0:16] = struct.pack("<IHHII", proto.CAPABILITIES_SIZE + proto.RADIO_CAP_SIZE, 0, 0,
                                _RADIO_ID, head.sentid)
        struct.pack_into("<H", cap, 0x40, 1)  # numradios
        block = bytearray(proto.RADIO_CAP_SIZE)
        struct.pack_into("<H", block, 0x07, 0x8010)  # commoncap -> MAC
        block[0x0A:0x10] = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x01])
        block[0x10:0x10 + len(self.name)] = self.name.encode()
        block[0x52] = self.civ_address
        struct.pack_into(">I", block, 0x5A, 115200)
        self._control.sendto(bytes(cap) + bytes(block), addr)

    def _send_status(self, head: proto.Header, addr) -> None:
        buf = bytearray(proto.STATUS_SIZE)
        buf[0:16] = struct.pack("<IHHII", proto.STATUS_SIZE, 0, 0, _RADIO_ID, head.sentid)
        struct.pack_into("<I", buf, 0x30, 0)  # error ok
        buf[0x40] = 0x00  # not disconnected
        struct.pack_into(">H", buf, 0x42, self.civ_port)  # CI-V port (big-endian)
        struct.pack_into(">H", buf, 0x46, self.civ_port + 1)  # audio port (ignored)
        self._control.sendto(bytes(buf), addr)

    # -- CI-V stream ------------------------------------------------------ #
    def _on_civ(self, data: bytes, addr) -> None:
        head = proto.parse_header(data)
        if head is None:
            return
        if len(data) == proto.CONTROL_SIZE:
            if head.type == proto.TYPE_AREYOUTHERE:
                self._civ.sendto(proto.control(proto.TYPE_IAMHERE, 0, _RADIO_ID, head.sentid), addr)
            elif head.type == proto.TYPE_READY:
                self._civ.sendto(proto.control(proto.TYPE_READY, 0, _RADIO_ID, head.sentid), addr)
            return
        if len(data) == proto.PING_SIZE and head.type == proto.TYPE_PING and data[0x10] == 0:
            self._civ.sendto(proto.ping(head.seq, _RADIO_ID, head.sentid, 0x01,
                                        int.from_bytes(data[0x11:0x15], "little")), addr)
            return
        if len(data) <= proto.DATA_HEADER_SIZE:
            return  # openclose / idle — nothing to do
        frames, _ = parse_frames(proto.extract_civ(data))
        for frame in frames:
            if frame.to_addr == self.civ_address and frame.payload:
                self._respond_civ(frame.payload, head.sentid, addr)

    def _respond_civ(self, payload: bytes, client_id: int, addr) -> None:
        cmd = payload[0]
        resp: bytes | None = None
        if cmd == 0x03:  # read freq
            resp = bytes([0x03]) + freq_to_bcd(self.freq)
        elif cmd == 0x04:  # read mode
            resp = bytes([0x04, self.mode_civ, 0x01])
        elif cmd == 0x05:  # set freq
            self.freq = bcd_to_freq(payload[1:6])
            resp = bytes([0xFB])
        elif cmd == 0x06:  # set mode
            self.mode_civ = payload[1]
            resp = bytes([0xFB])
        elif cmd == 0x1C:  # PTT
            resp = bytes([0xFB])
        elif cmd == 0x17:  # send CW — no reply
            self.cw_sent.append(payload[1:].decode("ascii", "ignore"))
        if resp is None:
            return
        frame = build_frame(CONTROLLER_ADDR, self.civ_address, resp)
        pkt = proto.civ_data(0, _RADIO_ID, client_id, self._civ_send_seq & 0xFFFF, frame)
        self._civ_send_seq += 1
        self._civ.sendto(pkt, addr)
