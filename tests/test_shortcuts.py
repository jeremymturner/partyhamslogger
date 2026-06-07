"""Keyboard-shortcut catalog: no colliding accelerators."""

from __future__ import annotations

from partyhams.ui.shortcuts import COMMANDS, OPERATING


def test_command_shortcuts_are_unique():
    keys = [keyspec for keyspec, _desc in COMMANDS]
    assert keys, "expected at least one command shortcut"
    assert len(keys) == len(set(keys)), "duplicate command accelerator"


def test_every_row_has_keys_and_description():
    for keyspec, desc in COMMANDS + OPERATING:
        assert keyspec.strip()
        assert desc.strip()
