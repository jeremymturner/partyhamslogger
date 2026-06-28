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


def test_esm_step_run_partial_call_holds():
    # A partial call ("?") in Run sends it back verbatim and does NOT advance:
    # query is set, key is None, and none of the advance flags fire.
    q = esm_step(True, call_present=True, esm_sent=False, exch_complete=False, call_uncertain=True)
    assert q.query and q.key is None
    assert not (q.set_sent or q.log or q.reset)
    # The hold sticks even after the exchange has been sent.
    q2 = esm_step(True, call_present=True, esm_sent=True, exch_complete=True, call_uncertain=True)
    assert q2.query and q2.key is None

    # With the opt-in checkbox, an uncertain call behaves exactly as a normal one.
    s = esm_step(
        True,
        call_present=True,
        esm_sent=False,
        exch_complete=False,
        call_uncertain=True,
        send_on_query=True,
    )
    assert s.key == 2 and s.set_sent and not s.query

    # An empty call still triggers CQ regardless of the uncertain flag.
    assert esm_step(True, call_present=False, esm_sent=False, exch_complete=False).query is False


def test_esm_step_sp():
    assert esm_step(False, call_present=False, esm_sent=False, exch_complete=False).key is None
    s = esm_step(False, call_present=True, esm_sent=False, exch_complete=False)
    assert s.key == 4 and s.set_sent and s.focus_exchange
    final = esm_step(False, call_present=True, esm_sent=True, exch_complete=True)
    assert final.key == 2 and final.log and final.reset


def test_esm_step_sp_ignores_partial_call():
    # The partial-call hold is Run-only; S&P advances normally even with "?".
    s = esm_step(False, call_present=True, esm_sent=False, exch_complete=False, call_uncertain=True)
    assert s.key == 4 and s.set_sent and not s.query


def test_load_defaults_and_round_trip(tmp_path):
    contest = get("arrl-field-day")
    # No file yet -> contest defaults.
    ms = load_macros(contest, macros_dir=tmp_path)
    assert ms.cw_wpm == DEFAULT_WPM
    assert ms.cw_kbd_wpm == DEFAULT_WPM
    assert ms.get("CW.RUN", 1).content == "CQ FD {MYCALL} {MYCALL} FD"

    # Customize + save, then reload from the per-contest file.
    ms.cw_wpm = 32
    ms.cw_kbd_wpm = 18  # the separate keyboard speed round-trips too
    ms.get("CW.RUN", 1).content = "CQ TEST {MYCALL}"
    save_macros(contest.id, ms, macros_dir=tmp_path)
    assert (tmp_path / "arrl-field-day.json").exists()

    reloaded = load_macros(contest, macros_dir=tmp_path)
    assert reloaded.cw_wpm == 32
    assert reloaded.cw_kbd_wpm == 18
    assert reloaded.get("CW.RUN", 1).content == "CQ TEST {MYCALL}"


def test_macroset_get_missing():
    ms = MacroSet()
    assert ms.get("CW", 1) is None


def test_clamp_wpm_bounds():
    from partyhams.app.macros import WPM_MAX, WPM_MIN, clamp_wpm

    assert clamp_wpm(24) == 24
    assert clamp_wpm(WPM_MIN - 5) == WPM_MIN
    assert clamp_wpm(WPM_MAX + 99) == WPM_MAX
    assert clamp_wpm(WPM_MIN) == WPM_MIN
    assert clamp_wpm(WPM_MAX) == WPM_MAX


def test_normalize_cw_speed_mode():
    from partyhams.app.macros import (
        CW_SPEED_DEFAULT,
        CW_SPEED_RESTORE,
        normalize_cw_speed_mode,
    )

    assert normalize_cw_speed_mode("restore") == CW_SPEED_RESTORE
    assert normalize_cw_speed_mode("sync") == "sync"
    assert normalize_cw_speed_mode("bogus") == CW_SPEED_DEFAULT
    assert normalize_cw_speed_mode(None) == CW_SPEED_DEFAULT


def test_cw_duration_seconds_scales_with_length_and_speed():
    from partyhams.app.macros import cw_duration_seconds

    # Longer text takes longer; faster speed takes less time.
    assert cw_duration_seconds("CQ TEST", 25) > cw_duration_seconds("CQ", 25)
    assert cw_duration_seconds("CQ TEST", 40) < cw_duration_seconds("CQ TEST", 20)
    # Always a positive, finite estimate (even for empty text / silly speeds).
    assert cw_duration_seconds("", 25) > 0
    assert cw_duration_seconds("X", 0) > 0  # wpm floored to 1, no ZeroDivision
