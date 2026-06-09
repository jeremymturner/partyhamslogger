"""The "About PartyHams Logger" credits dialog.

A small modal that shows the app icon, name + version, the W0CPH credit line,
and a link to the project repo. Like the rest of the UI it reads colors live
through :mod:`partyhams.ui.style` so it re-themes with the rest of the app.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from partyhams import __version__
from partyhams.ui import style

# Single source of truth for the project link (pyproject's URL is still a stub).
REPO_URL = "https://github.com/coloradopartyhams/partyhams-logger"

# The club we're tipping our hat to.
CREDIT = (
    "Built by <b>W0CPH — the Colorado Party Hams</b><br>"
    "for a fun and collaborative logging application."
)


def about_html() -> str:
    """The credit/link body as themed HTML (pure helper, no Qt widgets — testable)."""
    return (
        f"<p style='margin:0 0 8px 0;'>{CREDIT}</p>"
        f"<p style='margin:0;'><a style='color:{style.ACCENT};' "
        f"href='{REPO_URL}'>{REPO_URL}</a></p>"
    )


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About PartyHams Logger")
        self.setMinimumWidth(420)

        outer = QVBoxLayout(self)

        # Header: icon next to the app name + version.
        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(style.app_icon().pixmap(64, 64))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        header.addWidget(icon)

        title = QLabel(
            f"<div style='font-size:20px; font-weight:700; color:{style.TEXT};'>"
            f"PartyHams Logger</div>"
            f"<div style='color:{style.TEXT_DIM};'>Version {__version__}</div>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(title, 1)
        outer.addLayout(header)

        # Credit + repo link.
        body = QLabel(about_html())
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setOpenExternalLinks(True)
        body.setStyleSheet(f"color: {style.TEXT}; margin-top: 10px;")
        outer.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)
        outer.addWidget(buttons)
