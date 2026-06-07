"""A fake CI-V radio as a fake pyserial object, for testing IcomCIV.

On ``write`` it parses the command frame, echoes it (CI-V is a shared bus), and
queues the appropriate response; ``read`` returns queued bytes. State (freq/mode)
is mutable so a test can simulate the operator turning the dial.
"""

from __future__ import annotations

from partyhams.radio.civ_protocol import (
    CONTROLLER_ADDR,
    bcd_to_freq,
    build_frame,
    freq_to_bcd,
    parse_frames,
)


class FakeCivSerial:
    def __init__(self, freq: int = 14_074_000, mode: int = 0x03, civ_address: int = 0xA4) -> None:
        self.freq = freq
        self.mode = mode  # CI-V mode byte (0x03 = CW)
        self.civ_address = civ_address
        self.timeout = 0.2
        self.ptt: int | None = None
        self.cw_sent: list[str] = []
        self.cw_stopped = False
        self.closed = False
        self._rx = bytearray()  # bytes the controller will read back

    # pyserial-like API ------------------------------------------------- #
    def write(self, data: bytes) -> int:
        frames, _ = parse_frames(bytes(data))
        for frame in frames:
            self._handle(frame.payload)
        return len(data)

    def read(self, n: int) -> bytes:
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def close(self) -> None:
        self.closed = True

    # radio behavior ---------------------------------------------------- #
    def _handle(self, payload: bytes) -> None:
        # Echo the controller's command back onto the bus.
        self._rx += build_frame(self.civ_address, CONTROLLER_ADDR, payload)
        cmd = payload[0]
        if cmd == 0x03:  # read freq
            self._reply(bytes([0x03]) + freq_to_bcd(self.freq))
        elif cmd == 0x04:  # read mode
            self._reply(bytes([0x04, self.mode, 0x01]))
        elif cmd == 0x05:  # set freq
            self.freq = bcd_to_freq(payload[1:6])
            self._ack(True)
        elif cmd == 0x06:  # set mode
            self.mode = payload[1]
            self._ack(True)
        elif cmd == 0x1C:  # PTT
            self.ptt = payload[2]
            self._ack(True)
        elif cmd == 0x17:  # send CW
            data = payload[1:]
            if data == b"\xff":
                self.cw_stopped = True
            elif data:
                self.cw_sent.append(data.decode("ascii", "ignore"))
        else:
            self._ack(False)

    def _reply(self, payload: bytes) -> None:
        self._rx += build_frame(CONTROLLER_ADDR, self.civ_address, payload)

    def _ack(self, ok: bool) -> None:
        self._reply(bytes([0xFB if ok else 0xFA]))
