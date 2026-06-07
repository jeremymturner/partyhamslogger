"""F-key macros: variable expansion, persistence, and Field Day defaults."""

from __future__ import annotations

from partyhams.app.macros import (
    DEFAULT_WPM,
    MacroSet,
    bank_key,
    esm_step,
    expand,
    load_macros,
    save_macros,
)
from partyhams.contest import get


def test_expand_substitutes_variables():
    ctx = {"MYCALL": "N0AW", "CALL": "K1ABC", "EXCH": "2A OR"}
    text, actions = expand("CQ FD {MYCALL} {MYCALL} FD", ctx)
    assert text == "CQ FD N0AW N0AW FD"
    assert actions == []

    text, actions = expand("{CALL} {EXCH}", ctx)
    assert text == "K1ABC 2A OR"


def test_expand_extracts_actions_and_collapses_space():
    ctx = {"MYCALL": "N0AW"}
    text, actions = expand("TU {MYCALL} FD {LOG}", ctx)
    assert text == "TU N0AW FD"  # the {LOG} marker is removed from the sent text
    assert actions == ["log"]

    text, actions = expand("  {WIPE}  ", {})
    assert text == ""
    assert actions == ["wipe"]


def test_expand_unknown_token_is_empty():
    text, _ = expand("{MYCALL} {NOPE}", {"MYCALL": "N0AW"})
    assert text == "N0AW"


def test_field_day_default_macros():
    macros = get("arrl-field-day").default_macros()
    assert set(macros) == {"CW.RUN", "CW.SP", "PHONE.RUN", "PHONE.SP"}
    run = {m.key: m.content for m in macros["CW.RUN"]}
    assert run[1] == "CQ FD {MYCALL} {MYCALL} FD"
    assert "{LOG}" in run[3]  # F3 TU logs the QSO in Run
    assert run[12] == "{WIPE}"
    sp = {m.key: m.content for m in macros["CW.SP"]}
    assert sp[3] == "TU {LOG}"  # S&P gets a briefer TU


def test_bank_key():
    assert bank_key("CW", run=True) == "CW.RUN"
    assert bank_key("PHONE", run=False) == "PHONE.SP"


def test_esm_step_run():
    assert esm_step(True, call_present=False, esm_sent=False, exch_complete=False).key == 1
    s = esm_step(True, call_present=True, esm_sent=False, exch_complete=False)
    assert s.key == 2 and s.set_sent and s.focus_exchange
    assert esm_step(True, call_present=True, esm_sent=True, exch_complete=False).key == 2
    done = esm_step(True, call_present=True, esm_sent=True, exch_complete=True)
    assert done.key == 3 and done.reset


def test_esm_step_sp():
    assert esm_step(False, call_present=False, esm_sent=False, exch_complete=False).key is None
    s = esm_step(False, call_present=True, esm_sent=False, exch_complete=False)
    assert s.key == 4 and s.set_sent and s.focus_exchange
    final = esm_step(False, call_present=True, esm_sent=True, exch_complete=True)
    assert final.key == 2 and final.log and final.reset


def test_load_defaults_and_round_trip(tmp_path):
    contest = get("arrl-field-day")
    # No file yet -> contest defaults.
    ms = load_macros(contest, macros_dir=tmp_path)
    assert ms.cw_wpm == DEFAULT_WPM
    assert ms.get("CW.RUN", 1).content == "CQ FD {MYCALL} {MYCALL} FD"

    # Customize + save, then reload from the per-contest file.
    ms.cw_wpm = 32
    ms.get("CW.RUN", 1).content = "CQ TEST {MYCALL}"
    save_macros(contest.id, ms, macros_dir=tmp_path)
    assert (tmp_path / "arrl-field-day.json").exists()

    reloaded = load_macros(contest, macros_dir=tmp_path)
    assert reloaded.cw_wpm == 32
    assert reloaded.get("CW.RUN", 1).content == "CQ TEST {MYCALL}"


def test_macroset_get_missing():
    ms = MacroSet()
    assert ms.get("CW", 1) is None
