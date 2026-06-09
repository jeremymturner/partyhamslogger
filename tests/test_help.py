"""Documentation + in-app Help viewer integrity.

Asserts the guide pages exist, that ``index.md`` links resolve to real files,
that every embedded screenshot path resolves (after regenerating the PNGs), and
that the screenshot generator's screen builders run headless without error.

Qt usage is minimal and forced offscreen so this runs in CI without a display.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDE_DIR = REPO_ROOT / "docs" / "guide"
SHOTS_DIR = REPO_ROOT / "docs" / "screenshots"

EXPECTED_PAGES = [
    "index.md",
    "main-window.md",
    "network-panel.md",
    "sections.md",
    "new-log.md",
    "open-log.md",
    "radio.md",
    "macros.md",
    "wsjtx.md",
    "dx-cluster.md",
    "themes-fonts.md",
    "reference-data.md",
    "qrz.md",
    "auto-export.md",
    "pota.md",
    "about.md",
    "shortcuts.md",
]

_LINK_RE = re.compile(r"\]\(([^)]+\.md)\)")
_IMG_RE = re.compile(r"!\[[^\]]*\]\((\.\./screenshots/[^)]+)\)")


def _load_screenshots_module():
    """Import scripts/screenshots.py as a module (it isn't a package)."""
    path = REPO_ROOT / "scripts" / "screenshots.py"
    spec = importlib.util.spec_from_file_location("screenshots", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- guide files exist ----------------------------------------------------- #
def test_all_guide_pages_exist():
    for name in EXPECTED_PAGES:
        assert (GUIDE_DIR / name).is_file(), f"missing guide page: {name}"


def test_index_links_resolve_to_real_files():
    text = (GUIDE_DIR / "index.md").read_text(encoding="utf-8")
    targets = _LINK_RE.findall(text)
    assert targets, "index.md should link to guide pages"
    for target in targets:
        assert (GUIDE_DIR / target).is_file(), f"broken index link: {target}"


def test_index_links_cover_every_page():
    text = (GUIDE_DIR / "index.md").read_text(encoding="utf-8")
    linked = set(_LINK_RE.findall(text))
    for name in EXPECTED_PAGES:
        if name == "index.md":
            continue
        assert name in linked, f"index.md does not link {name}"


# --- screenshot generator + doc-image integrity ---------------------------- #
def test_generator_imports_and_builders_run_headless():
    module = _load_screenshots_module()
    from PySide6.QtWidgets import QApplication, QWidget

    QApplication.instance() or QApplication([])
    session = module.make_sample_session()

    main = module.build_main_window(session)
    assert isinstance(main, QWidget)
    panel = module.build_network_panel(session)
    assert isinstance(panel, QWidget)
    sections = module.build_sections_window(session)
    assert isinstance(sections, QWidget)
    wsjtx = module.build_wsjtx_panel()
    assert isinstance(wsjtx, QWidget)


def test_embedded_screenshots_exist_after_generation():
    module = _load_screenshots_module()
    module.generate_all()  # idempotent; regenerates the PNGs

    referenced: set[str] = set()
    for page in GUIDE_DIR.glob("*.md"):
        text = page.read_text(encoding="utf-8")
        for rel in _IMG_RE.findall(text):
            referenced.add(rel)
            resolved = (GUIDE_DIR / rel).resolve()
            assert resolved.is_file(), f"{page.name} references missing image {rel}"
    assert referenced, "expected at least one embedded screenshot"


# --- help window resolution ------------------------------------------------ #
def test_help_window_finds_docs_and_lists_pages():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from partyhams.ui.help_window import HelpWindow, find_docs_dir

    docs = find_docs_dir()
    assert docs is not None and (docs / "guide" / "index.md").is_file()

    win = HelpWindow()
    assert win._contents.count() == len(EXPECTED_PAGES)


@pytest.mark.parametrize("name", EXPECTED_PAGES)
def test_each_page_is_nonempty(name):
    assert (GUIDE_DIR / name).read_text(encoding="utf-8").strip()
