"""Blocking Flex discovery + connectivity check used by the radio dialog."""

from __future__ import annotations

import socket
import threading
import time

from fake_flex import build_discovery_packet

from partyhams.radio.flex import discover_sync, verify_connectivity


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_discover_sync_finds_a_radio():
    port = _free_udp_port()
    out: list = []
    worker = threading.Thread(target=lambda: out.extend(discover_sync(timeout=1.0, port=port)))
    worker.start()
    time.sleep(0.15)  # let the listener bind

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pkt = build_discovery_packet(
        {"model": "FLEX-6400", "serial": "9988", "ip": "192.168.1.9", "nickname": "Shack"}
    )
    for _ in range(4):
        sender.sendto(pkt, ("127.0.0.1", port))
        time.sleep(0.05)
    sender.close()
    worker.join(3)

    assert any(r.model == "FLEX-6400" and r.ip == "192.168.1.9" for r in out)


def test_verify_connectivity():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    assert verify_connectivity("127.0.0.1", port, timeout=1.0) is True
    server.close()
    assert verify_connectivity("127.0.0.1", port, timeout=0.3) is False
    assert verify_connectivity("", port) is False
