"""WSJT-X caller tracking: who is calling us, with POTA + Field Day context."""

from __future__ import annotations

from partyhams.contest.sections import is_valid_section
from partyhams.wsjtx.callers import (
    CallerTracker,
    cq_caller,
    directed_caller,
    is_pota_cq,
    looks_like_call,
    pota_activator,
    section_sent,
)
from partyhams.wsjtx.protocol import Decode


def _decode(message: str, snr: int = -5) -> Decode:
    return Decode(id="WSJT", message=message, snr=snr, time_ms=120_000, delta_freq=1500)


# --- parsing --------------------------------------------------------------- #
def test_looks_like_call_rejects_grids_and_junk():
    assert looks_like_call("K1ABC")
    assert looks_like_call("AB1QRP")
    assert not looks_like_call("FN42")  # a grid, not a call
    assert not looks_like_call("POTA")  # no digit
    assert not looks_like_call("73")


def test_directed_caller():
    assert directed_caller("W7PH K1ABC FN42", "W7PH") == "K1ABC"
    assert directed_caller("W7PH K1ABC RR73", "W7PH") == "K1ABC"
    assert directed_caller("CQ K1ABC FN42", "W7PH") == ""  # not directed at us
    assert directed_caller("N0XX K1ABC FN42", "W7PH") == ""  # directed at someone else


def test_cq_and_pota_parsing():
    assert cq_caller("CQ K1ABC FN42") == "K1ABC"
    assert cq_caller("CQ DX K1ABC FN42") == "K1ABC"
    assert cq_caller("CQ POTA K1ABC FN42") == "K1ABC"
    assert is_pota_cq("CQ POTA K1ABC FN42")
    assert not is_pota_cq("CQ K1ABC FN42")
    assert pota_activator("CQ POTA K1ABC FN42") == "K1ABC"
    assert pota_activator("CQ K1ABC FN42") == ""


def test_section_sent_field_day():
    assert section_sent("W7PH K1ABC 2A EMA", "W7PH", is_valid_section) == "EMA"
    assert section_sent("W7PH K1ABC R 2A EMA", "W7PH", is_valid_section) == "EMA"
    assert section_sent("W7PH K1ABC FN42", "W7PH", is_valid_section) == ""  # grid, no section


# --- tracker --------------------------------------------------------------- #
def test_tracker_records_directed_callers_only():
    t = CallerTracker()
    assert t.ingest(_decode("CQ K1ABC FN42"), my_call="W7PH", now=0.0) is None
    c = t.ingest(_decode("W7PH K1ABC FN42"), my_call="W7PH", now=1.0)
    assert c is not None and c.call == "K1ABC"
    assert [x.call for x in t.active(1.0)] == ["K1ABC"]


def test_tracker_expires_after_ttl():
    t = CallerTracker(ttl_s=300)
    t.ingest(_decode("W7PH K1ABC FN42"), my_call="W7PH", now=0.0)
    assert [c.call for c in t.active(299.0)] == ["K1ABC"]
    assert t.active(301.0) == []  # past the 5-minute TTL
    t.prune(301.0)
    assert t.decode_for("K1ABC") is None


def test_tracker_marks_pota_activators_green():
    t = CallerTracker()
    # Heard them activating a park, then they call us -> flagged POTA.
    t.ingest(_decode("CQ POTA K1ABC FN42"), my_call="W7PH", now=0.0)
    c = t.ingest(_decode("W7PH K1ABC FN42"), my_call="W7PH", now=1.0)
    assert c.pota is True
    # A caller never heard on CQ POTA is not flagged.
    other = t.ingest(_decode("W7PH N5DEF EM10"), my_call="W7PH", now=2.0)
    assert other.pota is False


def test_tracker_captures_field_day_section():
    t = CallerTracker(is_section=is_valid_section)
    c = t.ingest(_decode("W7PH K1ABC 2A EMA"), my_call="W7PH", now=0.0)
    assert c.section == "EMA"
    # A later bare-grid decode doesn't wipe the known section.
    c2 = t.ingest(_decode("W7PH K1ABC FN42"), my_call="W7PH", now=1.0)
    assert c2.section == "EMA"


def test_tracker_remove_drops_worked_station():
    t = CallerTracker()
    t.ingest(_decode("W7PH K1ABC FN42"), my_call="W7PH", now=0.0)
    t.ingest(_decode("W7PH N5DEF EM10"), my_call="W7PH", now=1.0)
    assert t.remove("k1abc") is True  # case-insensitive
    assert [c.call for c in t.active(1.0)] == ["N5DEF"]
    assert t.remove("K1ABC") is False  # already gone


def test_tracker_newest_first_and_decode_lookup():
    t = CallerTracker()
    t.ingest(_decode("W7PH K1ABC FN42"), my_call="W7PH", now=0.0)
    t.ingest(_decode("W7PH N5DEF EM10"), my_call="W7PH", now=5.0)
    assert [c.call for c in t.active(5.0)] == ["N5DEF", "K1ABC"]  # newest first
    assert t.decode_for("K1ABC").message == "W7PH K1ABC FN42"
