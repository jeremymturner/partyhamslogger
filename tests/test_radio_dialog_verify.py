"""Verify button picks the right probe/port per radio kind (no Qt widgets needed)."""

from __future__ import annotations

import pytest

from partyhams.ui import radio_dialog


@pytest.fixture
def calls(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr(
        "partyhams.radio.flex.verify_connectivity",
        lambda host, port, timeout: seen.append(("tcp", host, port)) or True,
    )
    monkeypatch.setattr(
        "partyhams.radio.icom_net.verify_reachable",
        lambda host, port, timeout: seen.append(("icom-udp", host, port)) or True,
    )
    monkeypatch.setattr(
        "partyhams.radio.icom_tcp.verify_connectivity",
        lambda host, port, timeout: seen.append(("icom-tcp", host, port)) or True,
    )
    return seen


@pytest.mark.parametrize(
    ("kind", "conn", "expected"),
    [
        ("icom7610-lan", "10.0.0.5", ("icom-udp", "10.0.0.5", 50001)),
        ("icom705-lan", "10.0.0.5:50011", ("icom-udp", "10.0.0.5", 50011)),
        ("icom7300mk2-lan", " rig.local ", ("icom-tcp", "rig.local", 50001)),
        ("hamlib", "127.0.0.1", ("tcp", "127.0.0.1", 4532)),
        ("hamlib", "127.0.0.1:4533", ("tcp", "127.0.0.1", 4533)),
        ("flex", "192.168.1.9", ("tcp", "192.168.1.9", 4992)),
    ],
)
def test_verify_uses_kind_specific_probe(calls, kind, conn, expected):
    assert radio_dialog.verify_radio(kind, conn) is True
    assert calls == [expected]


def test_verify_blank_host(calls):
    assert radio_dialog.verify_radio("icom7610-lan", "  ") is False
    assert calls == []


def test_verify_uses_the_lan_port_field_unless_conn_names_one(calls):
    assert radio_dialog.verify_radio("icom7610-lan", "10.0.0.5", lan_port=50011) is True
    assert radio_dialog.verify_radio("icom7610-lan", "10.0.0.5:50021", lan_port=50011) is True
    assert calls == [("icom-udp", "10.0.0.5", 50011), ("icom-udp", "10.0.0.5", 50021)]
