"""Icom radio kinds as saved in the radio settings, and each one's CI-V address.

Shared by the radio dialog (Verify) and the app's radio factory so the two can't
disagree about which address a model answers on.
"""

from __future__ import annotations

from partyhams.radio.civ_protocol import CIV_ADDR_IC705, CIV_ADDR_IC7300MK2, CIV_ADDR_IC7610

#: CI-V over a USB serial port; the connection string is the port path.
SERIAL_KINDS: dict[str, int] = {
    "icom705": CIV_ADDR_IC705,
    "icom7610": CIV_ADDR_IC7610,
    "icom7300mk2": CIV_ADDR_IC7300MK2,
}

#: Icom native LAN (UDP, username/password); the connection is the radio's IP/host.
UDP_LAN_KINDS: dict[str, int] = {
    "icom705-lan": CIV_ADDR_IC705,
    "icom7610-lan": CIV_ADDR_IC7610,
}

#: Plain CI-V over TCP (IC-7300 MK2 LAN); the connection is the radio's IP/host.
TCP_LAN_KINDS: dict[str, int] = {
    "icom7300mk2-lan": CIV_ADDR_IC7300MK2,
}
