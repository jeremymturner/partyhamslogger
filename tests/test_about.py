"""The About dialog: the credit body and a headless build under offscreen Qt."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from partyhams import __version__  # noqa: E402
from partyhams.ui import about_dialog  # noqa: E402


def test_about_html_has_credit_and_repo_link():
    html = about_dialog.about_html()
    assert "Colorado Party Hams" in html
    assert "fun and collaborative logging application" in html
    assert about_dialog.REPO_URL in html


def test_dialog_builds_and_shows_version():
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])
    assert app is not None

    dialog = about_dialog.AboutDialog()
    # Some header label carries the live version string.
    labels = dialog.findChildren(QLabel)
    assert any(__version__ in lbl.text() for lbl in labels)
    dialog.deleteLater()
