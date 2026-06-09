"""In-app User Guide viewer.

Renders the Markdown pages under ``docs/guide/`` with :class:`QTextBrowser`
(which understands ``setMarkdown`` plus links and images). A left-hand contents
list selects a page; the page renders on the right with its screenshot embedded.

The docs directory is resolved at runtime so this works both from a source
checkout and a packaged build; if no docs are found the viewer degrades to a
short message rather than failing.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QTextBrowser,
    QWidget,
)

# Contents: (page filename under docs/guide, sidebar label). Order matters.
_PAGES: list[tuple[str, str]] = [
    ("index.md", "Overview"),
    ("main-window.md", "Main window"),
    ("network-panel.md", "Network panel"),
    ("sections.md", "Sections Worked"),
    ("new-log.md", "New Log"),
    ("open-log.md", "Open Log"),
    ("radio.md", "Radio / CAT"),
    ("macros.md", "Macros & ESM"),
    ("wsjtx.md", "WSJT-X"),
    ("dx-cluster.md", "DX Cluster"),
    ("themes-fonts.md", "Themes & fonts"),
    ("reference-data.md", "Reference data"),
    ("qrz.md", "QRZ.com lookups"),
    ("auto-export.md", "Auto-export"),
    ("pota.md", "Field Day / POTA"),
    ("about.md", "About"),
    ("shortcuts.md", "Keyboard shortcuts"),
]


def find_docs_dir() -> Path | None:
    """Locate the ``docs`` directory in a source checkout or packaged build.

    Returns the directory that contains ``guide/`` and ``screenshots/``, or
    ``None`` if it can't be found (the viewer then degrades gracefully).
    """
    candidates: list[Path] = []
    # 1) Repo layout: <repo>/docs, with this file at <repo>/src/partyhams/ui/.
    here = Path(__file__).resolve()
    candidates.append(here.parents[3] / "docs")
    # 2) PyInstaller one-file/one-dir: data bundled next to the executable.
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "docs")
        candidates.append(Path(sys.executable).resolve().parent / "docs")
    # 3) Data shipped inside the package itself.
    candidates.append(here.parent / "docs")
    for cand in candidates:
        if (cand / "guide" / "index.md").is_file():
            return cand
    return None


class HelpWindow(QWidget):
    """A two-pane Markdown guide browser (contents list + rendered page)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PartyHams Logger — User Guide")
        self.resize(900, 640)
        self._docs_dir = find_docs_dir()
        self._guide_dir = self._docs_dir / "guide" if self._docs_dir else None

        self._contents = QListWidget()
        self._contents.setMaximumWidth(200)
        self._contents.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        # Resolve relative image/link paths (../screenshots/x.png) against docs/.
        if self._docs_dir is not None:
            self._browser.setSearchPaths([str(self._docs_dir), str(self._guide_dir)])

        layout = QHBoxLayout(self)
        layout.addWidget(self._contents)
        layout.addWidget(self._browser, stretch=1)

        if self._guide_dir is None:
            self._browser.setMarkdown(
                "# User Guide unavailable\n\nThe bundled documentation could not "
                "be found in this build. See the project repository for the guide."
            )
            return

        for filename, label in _PAGES:
            if (self._guide_dir / filename).is_file():
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, filename)
                self._contents.addItem(item)
        self._contents.currentRowChanged.connect(self._on_row_changed)
        if self._contents.count():
            self._contents.setCurrentRow(0)

    def _on_row_changed(self, row: int) -> None:
        item = self._contents.item(row)
        if item is None or self._guide_dir is None:
            return
        filename = item.data(Qt.ItemDataRole.UserRole)
        self._load_page(self._guide_dir / filename)

    def _load_page(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            self._browser.setMarkdown(f"# Not found\n\nCould not read `{path.name}`.")
            return
        # Rewrite ../screenshots/x.png to absolute file paths so images load
        # regardless of the browser's current base URL.
        if self._docs_dir is not None:
            shots = (self._docs_dir / "screenshots").resolve()
            text = text.replace("../screenshots/", f"{shots.as_posix()}/")
            # WSJTX.md lives one level up from guide/, in docs/.
            text = text.replace(
                "../WSJTX.md", (self._docs_dir / "WSJTX.md").resolve().as_uri()
            )
        self._browser.setMarkdown(text)
        self._browser.moveCursor(self._browser.textCursor().MoveOperation.Start)
