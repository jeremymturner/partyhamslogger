"""Reference-data parsers and the RefData store (pure, no Qt, no network)."""

from __future__ import annotations

from partyhams.refdata import parse_city_dat, parse_scp, parse_user_list
from partyhams.refdata.store import RefData

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


def test_refdata_city_lookup_longest_prefix(tmp_path):
    rd = RefData(dir_=tmp_path)
    rd.import_city_dat("W7,Generic,AZ,AZ\nW7ABC,Phoenix,AZ,AZ\n")
    assert rd.city_lookup("W7ABC") == {"name": "Phoenix", "state": "AZ", "section": "AZ"}
    # Falls back to the longest matching prefix for an unlisted call.
    assert rd.city_lookup("W7DEF")["name"] == "Generic"
    assert rd.city_lookup("K1NONE") is None
    assert rd.city_lookup("") is None
