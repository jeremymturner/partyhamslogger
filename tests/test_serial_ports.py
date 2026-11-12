"""Serial-port discovery + CI-V serial Verify for the radio dialog."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fake_civ import FakeCivSerial

from partyhams.radio import icom_civ
from partyhams.radio.icom_civ import list_serial_ports, probe_port


def _port(device, hwid="n/a", vid=None, serial_number=None, product=None, description="n/a"):
    return SimpleNamespace(device=device, hwid=hwid, vid=vid, serial_number=serial_number,
                           product=product, description=description)


# What macOS reports with an IC-7610 (two CP2102s, each listed under two names),
# a programming cable, and the usual Bluetooth/debug noise.
_IC7610_A = "USB VID:PID=10C4:EA60 SER=IC-7610 12003680 A LOCATION=0-1.2.3.2.2"
_IC7610_B = "USB VID:PID=10C4:EA60 SER=IC-7610 12003680 B LOCATION=0-1.2.3.2.3"
_MAC_PORTS = [
    _port("/dev/cu.debug-console"),
    _port("/dev/cu.Bluetooth-Incoming-Port"),
    _port("/dev/cu.usbserial-RT1SQ1OS", "USB VID:PID=2100:9E5F SER=RT1SQ1OS LOCATION=0-1.2.4.2",
          0x2100, "RT1SQ1OS", "RTS05 Radio Cable"),
    _port("/dev/cu.SLAB_USBtoUART", _IC7610_A, 0x10C4, "IC-7610 12003680 A", "CP2102"),
    _port("/dev/cu.usbserial-123220", _IC7610_A, 0x10C4, "IC-7610 12003680 A", "CP2102"),
    _port("/dev/tty.usbserial-123220", _IC7610_A, 0x10C4, "IC-7610 12003680 A", "CP2102"),
    _port("/dev/cu.usbserial-123230", _IC7610_B, 0x10C4, "IC-7610 12003680 B", "CP2102"),
    _port("/dev/cu.SLAB_USBtoUART7", _IC7610_B, 0x10C4, "IC-7610 12003680 B", "CP2102"),
]


def test_lists_one_entry_per_physical_port_icom_first():
    ports = list_serial_ports(lambda: _MAC_PORTS)
    assert [p.device for p in ports] == [
        "/dev/cu.usbserial-123220",
        "/dev/cu.usbserial-123230",
        "/dev/cu.usbserial-RT1SQ1OS",
    ]
    assert ports[0].label == "IC-7610 12003680 A — /dev/cu.usbserial-123220"
    assert [p.is_icom for p in ports] == [True, True, False]


def test_icom_vendor_id_counts_as_icom():
    ic705 = _port("/dev/cu.usbmodem1101", "USB VID:PID=0C26:0036 SER=X", 0x0C26, "X", "IC-705")
    other = _port("/dev/cu.usbmodem9", "USB VID:PID=1234:0001 SER=Y", 0x1234, "Y", "Arduino")
    ports = list_serial_ports(lambda: [other, ic705])
    assert [(p.device, p.is_icom) for p in ports] == [
        ("/dev/cu.usbmodem1101", True),
        ("/dev/cu.usbmodem9", False),
    ]
    assert ports[0].label == "IC-705 — /dev/cu.usbmodem1101"


def test_windows_com_ports_are_listed():
    com = _port("COM4", "USB VID:PID=10C4:EA60 SER=IC-7610 1 A LOCATION=1-1", 0x10C4,
                "IC-7610 1 A", "CP2102")
    assert [p.device for p in list_serial_ports(lambda: [com])] == ["COM4"]


def test_probe_reports_detected_baud():
    rig = FakeCivSerial(civ_address=0x98)
    rig.required_baud = 115200
    assert probe_port("/dev/fake", 0x98, serial_factory=lambda: rig) == 115200
    assert rig.closed


def test_probe_wrong_address_is_none():
    rig = FakeCivSerial(civ_address=0xA4)  # an IC-705 on the port, but we asked for 7610
    assert probe_port("/dev/fake", 0x98, serial_factory=lambda: rig) is None
    assert rig.closed


def test_probe_unopenable_port_raises():
    def boom():
        raise OSError("no such file")

    with pytest.raises(OSError):
        probe_port("/dev/nope", 0x98, serial_factory=boom)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("[Errno 35] Could not exclusively lock port /dev/cu.x", "/dev/cu.x is in use"),
        ("could not open port 'COM4': PermissionError(13, 'Access is denied.')",
         "/dev/cu.x is in use"),
        ("[Errno 2] could not open port /dev/cu.x: No such file", "can't open /dev/cu.x"),
    ],
)
def test_dialog_verify_reports_busy_and_missing_ports(monkeypatch, error, expected):
    from partyhams.ui import radio_dialog

    def raise_(port, addr, baud=None):
        raise OSError(error)

    monkeypatch.setattr(icom_civ, "probe_port", raise_)
    ok, message = radio_dialog.verify_serial("icom7610", "/dev/cu.x")
    assert not ok and message.startswith(expected)


def test_dialog_verify_serial(monkeypatch):
    from partyhams.ui import radio_dialog

    seen = []
    monkeypatch.setattr(icom_civ, "probe_port",
                        lambda port, addr, baud=None: seen.append((port, addr)) or 115200)
    assert radio_dialog.verify_serial("icom7610", " /dev/cu.x ") == (
        True, "radio answering at 115200 baud")
    assert radio_dialog.verify_radio("icom705", "/dev/cu.y") is True
    assert seen == [("/dev/cu.x", 0x98), ("/dev/cu.y", 0xA4)]

    monkeypatch.setattr(icom_civ, "probe_port", lambda port, addr, baud=None: None)
    assert radio_dialog.verify_serial("icom7300mk2", "/dev/cu.z") == (
        False, "no CI-V reply on /dev/cu.z")
    assert radio_dialog.verify_serial("icom7610", "  ") == (False, "pick a serial port")


@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _fake_ports(monkeypatch):
    monkeypatch.setattr(icom_civ, "list_serial_ports",
                        lambda comports=None: list_serial_ports(lambda: _MAC_PORTS))


def test_dialog_switching_from_lan_picks_a_port(qapp, monkeypatch):
    from partyhams.ui.radio_dialog import RadioDialog

    _fake_ports(monkeypatch)
    dlg = RadioDialog({"kind": "icom7610-lan", "conn": "10.21.78.240"})
    dlg._radio.setCurrentIndex(dlg._radio.findData("icom7610"))
    assert dlg.settings()["conn"] == "/dev/cu.usbserial-123220"  # IP replaced
    dlg._port_combo.setCurrentIndex(1)
    assert dlg.settings()["conn"] == "/dev/cu.usbserial-123230"


def test_dialog_switching_to_lan_clears_a_serial_path(qapp, monkeypatch):
    from partyhams.ui.radio_dialog import RadioDialog

    _fake_ports(monkeypatch)
    dlg = RadioDialog({"kind": "icom7610", "conn": "/dev/cu.usbserial-123220"})
    dlg._radio.setCurrentIndex(dlg._radio.findData("icom7610-lan"))
    assert dlg.settings()["conn"] == ""
    dlg._conn.setText("10.21.78.240")
    dlg._radio.setCurrentIndex(dlg._radio.findData("hamlib"))
    assert dlg.settings()["conn"] == "10.21.78.240"  # host-to-host is kept


def test_dialog_close_waits_for_a_slow_verify(qapp, monkeypatch):
    """A serial probe of a silent port runs ~4 s; closing must wait it out, not abort."""
    import time

    from partyhams.ui import radio_dialog

    real_wait = radio_dialog.QThread.wait
    waits: list = []
    monkeypatch.setattr(radio_dialog.QThread, "wait",
                        lambda self, *a: waits.append(a) or real_wait(self, *a))
    monkeypatch.setattr(radio_dialog, "verify_serial",
                        lambda k, c, b=None: time.sleep(0.2) or (False, ""))
    _fake_ports(monkeypatch)
    dlg = radio_dialog.RadioDialog({"kind": "icom7610", "conn": "/dev/cu.usbserial-123230"})
    dlg._verify()
    dlg.reject()
    assert waits == [()]  # waited with no time limit
    assert not dlg._verify_worker.isRunning()


def test_dialog_keeps_a_saved_port_even_if_unlisted(qapp, monkeypatch):
    from partyhams.ui.radio_dialog import RadioDialog

    _fake_ports(monkeypatch)
    dlg = RadioDialog({"kind": "icom7610", "conn": "/dev/cu.SLAB_USBtoUART"})
    assert dlg.settings()["conn"] == "/dev/cu.SLAB_USBtoUART"
    assert dlg._port_combo.currentData() == "/dev/cu.SLAB_USBtoUART"


def test_dialog_baud_defaults_to_auto_and_round_trips(qapp, monkeypatch):
    from partyhams.ui.radio_dialog import RadioDialog

    _fake_ports(monkeypatch)
    dlg = RadioDialog({"kind": "icom7610", "conn": "/dev/cu.usbserial-123220"})
    assert dlg.settings()["baud"] is None  # auto-detect
    dlg = RadioDialog({"kind": "icom7610", "conn": "/dev/cu.usbserial-123220", "baud": 9600})
    assert dlg.settings()["baud"] == 9600


def test_dialog_verify_serial_uses_a_fixed_baud(monkeypatch):
    from partyhams.ui import radio_dialog

    seen = []
    monkeypatch.setattr(icom_civ, "probe_port",
                        lambda port, addr, baud=None: seen.append(baud) or None)
    ok, message = radio_dialog.verify_serial("icom7610", "/dev/cu.x", 9600)
    assert (ok, message, seen) == (False, "no CI-V reply on /dev/cu.x at 9600 baud", [9600])
