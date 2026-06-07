"""Small reusable Qt widget helpers."""

from __future__ import annotations

from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QLineEdit


class UpperCaseValidator(QValidator):
    """Forces a line edit's text to upper case as the user types.

    Callsigns, classes, sections, and grids are conventionally upper case; this
    keeps the displayed text consistent with how it's stored and compared.
    """

    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        return (QValidator.State.Acceptable, text.upper(), pos)


def make_upper(*edits: QLineEdit) -> None:
    """Attach an :class:`UpperCaseValidator` to each line edit."""
    for edit in edits:
        edit.setValidator(UpperCaseValidator(edit))
