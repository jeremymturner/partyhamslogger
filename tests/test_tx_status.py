"""The transmit indicator shown on the left of the status bar."""

from __future__ import annotations

from partyhams.ui.main_window import _format_tx_status


def test_transmitting_then_sent():
    assert (
        _format_tx_status("TRANSMITTING", 1, "CQ FD", "CQ CQ FD W7ABC")
        == "TRANSMITTING — F1 — CQ FD — CQ CQ FD W7ABC"
    )
    assert (
        _format_tx_status("SENT", 1, "CQ FD", "CQ CQ FD W7ABC")
        == "SENT — F1 — CQ FD — CQ CQ FD W7ABC"
    )


def test_blank_label_is_omitted():
    assert _format_tx_status("TRANSMITTING", 5, "", "bare text") == "TRANSMITTING — F5 — bare text"
