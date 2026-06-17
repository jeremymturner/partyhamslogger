"""Reference-data parsers and the RefData store (pure, no Qt, no network)."""

from __future__ import annotations

from partyhams.refdata import parse_city_dat, parse_scp, parse_user_list
from partyhams.refdata.parsers import parse_call_history
from partyhams.refdata.store import RefData

FD_FIELDS = {"class", "section"}

# N1MM Call History: a !!Order!! header names the columns; #-comments + blanks
# are ignored; "Sect" aliases to our "section"; columns we don't know are dropped.
N1MM_HISTORY = """\
!!Order!!,Call,Name,Sect,State,Class
# a comment line
K1ABC,Alice,EMA,MA,2A

W7XYZ,Bob,OR,OR,3A
n0call,Carol,WWA,WA,1D
not-a-call,Dave,EMA,MA,9Z
"""

# A real N1MM Field Day call-history file: the class column is named "Exch1"
# (not "Class"), and a #-comment block sits between the header and the data.
FD_N1MM_HISTORY = """\
!!Order!!,Call,Exch1,Sect,UserText
# FD
# LastEdit,2026-06-16
# Original file from Mike W1MI

AA0B,1A,MO,Central MO Radio Assn.
AA0EL,2A,CO,(K0IIT GOTA) Montrose ARC
AA0IZ,1D,OR
"""

# Simple CSV: a plain header row (first column Call), no !!Order!! marker.
CSV_HISTORY = """\
Call,Class,Section
K1ABC,2A,EMA
W7XYZ,3A,OR
"""

SCP_SAMPLE = """\
# super check partial — comment line
W7ABC

K1XYZ   # trailing comment after a call
n0call
not a call!
"""

CITY_SAMPLE = """\
# prefix, name, state, section
W7ABC,Phoenix,AZ,AZ
K1XYZ,Boston,MA,EMA
W0 Denver CO CO
"""

USERS_PLAIN = """\
# eQSL users
W7ABC
K1XYZ
"""

USERS_CSV = """\
Call,Date
W7ABC,2024-01-01
N0CALL,2024-02-02
"""


def test_parse_scp_skips_comments_blanks_and_junk():
    calls = parse_scp(SCP_SAMPLE)
    assert calls == {"W7ABC", "K1XYZ", "N0CALL"}


def test_parse_user_list_plain_and_uppercases():
    assert parse_user_list(USERS_PLAIN) == {"W7ABC", "K1XYZ"}


def test_parse_user_list_csv_first_column():
    assert parse_user_list(USERS_CSV, column=0) == {"W7ABC", "N0CALL"}


def test_parse_city_dat_csv_and_whitespace_records():
    table = parse_city_dat(CITY_SAMPLE)
    assert table["W7ABC"] == {"name": "Phoenix", "state": "AZ", "section": "AZ"}
    assert table["K1XYZ"]["section"] == "EMA"
    assert table["W0"] == {"name": "Denver", "state": "CO", "section": "CO"}


def test_refdata_scp_prefix_match_and_persistence(tmp_path):
    rd = RefData(dir_=tmp_path)
    assert rd.import_scp("W7ABC\nW7XYZ\nK1ABC\n") == 3
    assert rd.is_scp_match("W7") == ["W7ABC", "W7XYZ"]
    assert rd.is_scp_match("") == []
    # A fresh store loads the persisted normalized copy from disk.
    reloaded = RefData(dir_=tmp_path)
    reloaded.load()
    assert reloaded.is_scp_match("W7") == ["W7ABC", "W7XYZ"]


def test_refdata_user_membership(tmp_path):
    rd = RefData(dir_=tmp_path)
    rd.import_lotw("W7ABC\nK1XYZ\n")
    rd.import_eqsl("W7ABC\n")
    rd.import_qrz("N0CALL\n")
    assert rd.uses_lotw("w7abc") is True
    assert rd.uses_lotw("W9ZZZ") is False
    assert rd.uses_eqsl("W7ABC") is True
    assert rd.uses_eqsl("K1XYZ") is False
    assert rd.qrz_known("N0CALL") is True
    assert rd.qrz_known("W7ABC") is False


def test_parse_call_history_n1mm_format():
    hist = parse_call_history(N1MM_HISTORY, FD_FIELDS)
    # "Sect" -> section (alias); "Class" matches directly; Name/State ignored.
    assert hist["K1ABC"] == {"section": "EMA", "class": "2A"}
    assert hist["W7XYZ"] == {"section": "OR", "class": "3A"}
    assert hist["N0CALL"]["section"] == "WWA"  # call uppercased
    assert "NOT-A-CALL" not in hist  # junk callsign rejected


def test_parse_call_history_n1mm_exch1_maps_to_class():
    # The standard N1MM FD file names the class column "Exch1"; it must map to
    # our "class" field, and rows with no UserText must still parse (issue #19).
    hist = parse_call_history(FD_N1MM_HISTORY, FD_FIELDS)
    assert hist["AA0B"] == {"class": "1A", "section": "MO"}
    assert hist["AA0EL"] == {"class": "2A", "section": "CO"}
    assert hist["AA0IZ"] == {"class": "1D", "section": "OR"}


def test_parse_call_history_simple_csv():
    hist = parse_call_history(CSV_HISTORY, FD_FIELDS)
    assert hist == {
        "K1ABC": {"class": "2A", "section": "EMA"},
        "W7XYZ": {"class": "3A", "section": "OR"},
    }


def test_parse_call_history_drops_entries_with_no_known_fields():
    # Fields for a different contest -> no columns resolve -> nothing kept.
    assert parse_call_history(CSV_HISTORY, {"park"}) == {}
    # No "Call" column at all -> empty.
    assert parse_call_history("Name,Sect\nAlice,EMA\n", FD_FIELDS) == {}


def test_refdata_call_history_lookup_and_persistence(tmp_path):
    rd = RefData(dir_=tmp_path)
    assert rd.import_call_history(CSV_HISTORY, FD_FIELDS) == 2
    assert rd.history_lookup("k1abc") == {"class": "2A", "section": "EMA"}  # case-insensitive
    assert rd.history_lookup("W9NONE") is None
    # A fresh store recovers the persisted map from disk.
    reloaded = RefData(dir_=tmp_path)
    reloaded.load()
    assert reloaded.history_lookup("W7XYZ") == {"class": "3A", "section": "OR"}


def test_refdata_city_lookup_longest_prefix(tmp_path):
    rd = RefData(dir_=tmp_path)
    rd.import_city_dat("W7,Generic,AZ,AZ\nW7ABC,Phoenix,AZ,AZ\n")
    assert rd.city_lookup("W7ABC") == {"name": "Phoenix", "state": "AZ", "section": "AZ"}
    # Falls back to the longest matching prefix for an unlisted call.
    assert rd.city_lookup("W7DEF")["name"] == "Generic"
    assert rd.city_lookup("K1NONE") is None
    assert rd.city_lookup("") is None
