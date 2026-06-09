"""Sections worked/needed window — a tabbed view over all ARRL/RAC sections.

Tab 1 (Grid): a per-band multiplier grid (N1MM-style). Sections are grouped into
columns by call district (0–9, VE, DX); each shows a small coloured pip per band
(160→6 m): green = worked on that band, dim = needed. The Mode filter scopes it
(Any / CW / Phone / Digital); a section name is green if worked on any band.

Tab 2 (Map): a SCHEMATIC section map. A pixel-accurate geographic vector map of
all ~85 ARRL/RAC sections is impractical to hand-digitize, so cells are laid out
on a grid arranged to roughly mirror US/Canada geography (west coast left, east
coast right, Canada along the top) — see ``SECTION_MAP_LAYOUT`` in
``partyhams.contest.sections``, which is data-driven so the layout can be refined
later. Worked sections are shaded; clicking a cell shows who worked it and on
which bands/modes (``session.section_detail``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from partyhams.app.session import LogSession
from partyhams.contest.sections import SECTION_GROUPS, SECTION_MAP_LAYOUT
from partyhams.ui import style

# Bands shown as pips, left→right. (Sections worked on other bands still count as
# worked; these are just the columns drawn.)
_BAND_ORDER = ["160m", "80m", "40m", "20m", "15m", "10m", "6m"]
_COLUMNS = 6  # district blocks per row


class SectionsGrid(QWidget):
    """The original per-band multiplier grid (Tab 1)."""

    def __init__(self, session: LogSession) -> None:
        super().__init__()
        self.session = session

        self._mode = QComboBox()
        for label, value in (
            ("Any mode", None),
            ("CW", "CW"),
            ("Phone", "PHONE"),
            ("Digital", "DIGITAL"),
        ):
            self._mode.addItem(label, value)
        self._counter = QLabel()
        legend = QLabel(
            f"bands L→R: {' '.join(b.replace('m', '') for b in _BAND_ORDER)} &nbsp;·&nbsp; "
            f"<span style='color:{style.MULT}'>■</span> worked &nbsp; "
            f"<span style='color:{style.BORDER}'>■</span> needed"
        )
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setStyleSheet(f"color: {style.TEXT_DIM};")

        top = QHBoxLayout()
        top.addWidget(QLabel("Mode"))
        top.addWidget(self._mode)
        top.addWidget(legend)
        top.addStretch(1)
        top.addWidget(self._counter)

        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("monospace")

        content = QWidget()
        grid = QGridLayout(content)
        grid.setHorizontalSpacing(18)
        self._rows: dict[str, tuple[QLabel, QLabel]] = {}
        for idx, (dist, sections) in enumerate(SECTION_GROUPS.items()):
            block = QWidget()
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(0, 0, 0, 0)
            block_layout.setSpacing(1)
            header = QLabel(f"<b style='color:{style.ACCENT}'>{dist}</b>")
            block_layout.addWidget(header)
            for section in sections:
                name = QLabel()
                name.setFixedWidth(40)
                name.setFont(mono)
                pips = QLabel()
                pips.setFont(mono)
                self._rows[section] = (name, pips)
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(2)
                row.addWidget(name)
                row.addWidget(pips)
                row.addStretch(1)
                block_layout.addLayout(row)
            block_layout.addStretch(1)
            grid.addWidget(block, idx // _COLUMNS, idx % _COLUMNS, Qt.AlignmentFlag.AlignTop)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(scroll)

        self._mode.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        mode = self._mode.currentData()
        status = self.session.section_status()
        worked_count = 0
        for section, (name_label, pips_label) in self._rows.items():
            slots = status.get(section, set())
            bands_worked = {band for band, slot_mode in slots if mode is None or slot_mode == mode}
            worked = bool(bands_worked)
            if worked:
                worked_count += 1
            name_label.setText(
                f"<span style='color:{style.MULT if worked else style.TEXT_DIM}'>{section}</span>"
            )
            name_label.setToolTip(
                ", ".join(sorted(f"{b} {m}" for b, m in slots)) if slots else "not worked"
            )
            pips = "".join(
                f"<span style='color:{style.MULT if band in bands_worked else style.BORDER}'>"
                "■</span>"
                for band in _BAND_ORDER
            )
            pips_label.setText(pips)
        self._counter.setText(
            f"<b style='color:{style.TEXT}'>{worked_count}</b> / {len(self._rows)} worked"
        )


class _SectionCell(QPushButton):
    """A single clickable section cell on the schematic map."""

    def __init__(self, section: str) -> None:
        super().__init__(section)
        self.section = section
        self.setFixedSize(46, 30)
        self.setCheckable(False)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_worked(self, worked: bool, selected: bool) -> None:
        if worked:
            bg, fg, border = style.MULT_BG, style.MULT, style.MULT
        else:
            bg, fg, border = style.BG_INPUT, style.TEXT_DIM, style.BORDER
        width = 2 if selected else 1
        outline = style.ACCENT if selected else border
        self.setStyleSheet(
            f"QPushButton {{ background-color: {bg}; color: {fg};"
            f" border: {width}px solid {outline}; border-radius: 4px;"
            f" font-weight: 600; font-size: 11px; padding: 0; }}"
            f"QPushButton:hover {{ border: 2px solid {style.ACCENT}; }}"
        )


class SectionsMap(QWidget):
    """Schematic, clickable section map (Tab 2) with a who-worked-it detail panel.

    The map is NOT geographically exact — see the module docstring and
    ``SECTION_MAP_LAYOUT``. Cells are placed on a grid that roughly mirrors
    US/Canada geography and shaded when worked.
    """

    def __init__(self, session: LogSession) -> None:
        super().__init__()
        self.session = session
        self._selected: str | None = None
        self._cells: dict[str, _SectionCell] = {}

        # --- map grid ---------------------------------------------------- #
        map_widget = QWidget()
        grid = QGridLayout(map_widget)
        grid.setHorizontalSpacing(3)
        grid.setVerticalSpacing(3)
        for section, (row, col) in SECTION_MAP_LAYOUT.items():
            cell = _SectionCell(section)
            cell.clicked.connect(lambda _=False, s=section: self._select(s))
            self._cells[section] = cell
            grid.addWidget(cell, row, col)
        map_scroll = QScrollArea()
        map_scroll.setWidget(map_widget)
        map_scroll.setWidgetResizable(True)

        note = QLabel(
            "Schematic map (not geographically exact): cells are arranged to roughly "
            "mirror US/Canada geography. Click a section to see who worked it."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {style.TEXT_DIM}; font-size: 11px;")

        left = QVBoxLayout()
        left.addWidget(map_scroll, 1)
        left.addWidget(note)

        # --- detail panel ------------------------------------------------ #
        self._detail_title = QLabel("Select a section")
        self._detail_title.setStyleSheet(
            f"color: {style.ACCENT}; font-weight: 700; font-size: 14px;"
        )
        self._detail_body = QLabel()
        self._detail_body.setTextFormat(Qt.TextFormat.RichText)
        self._detail_body.setWordWrap(True)
        self._detail_body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._detail_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        clear = QPushButton("Clear selection")
        clear.clicked.connect(lambda: self._select(None))

        detail_scroll = QScrollArea()
        detail_inner = QWidget()
        di = QVBoxLayout(detail_inner)
        di.setContentsMargins(0, 0, 0, 0)
        di.addWidget(self._detail_title)
        di.addWidget(self._detail_body, 1)
        di.addStretch(1)
        detail_scroll.setWidget(detail_inner)
        detail_scroll.setWidgetResizable(True)

        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(320)
        panel.setStyleSheet(
            f"QFrame {{ background-color: {style.BG_PANEL};"
            f" border: 1px solid {style.BORDER}; border-radius: 6px; }}"
        )
        pv = QVBoxLayout(panel)
        pv.addWidget(detail_scroll, 1)
        pv.addWidget(clear)

        body = QHBoxLayout(self)
        body.addLayout(left, 1)
        body.addWidget(panel)

        self.refresh()

    def _select(self, section: str | None) -> None:
        self._selected = section
        self.refresh()

    def refresh(self) -> None:
        status = self.session.section_status()
        for section, cell in self._cells.items():
            worked = bool(status.get(section))
            cell.set_worked(worked, selected=(section == self._selected))
        self._render_detail()

    def _render_detail(self) -> None:
        section = self._selected
        if not section:
            self._detail_title.setText("Select a section")
            self._detail_body.setText(
                f"<span style='color:{style.TEXT_DIM}'>"
                "Click a section cell to see who worked it and on which "
                "bands and modes.</span>"
            )
            return
        rows = self.session.section_detail(section)
        worked = "worked" if rows else "not worked yet"
        self._detail_title.setText(f"{section} — {worked}")
        if not rows:
            self._detail_body.setText(
                f"<span style='color:{style.TEXT_DIM}'>No QSOs with {section}.</span>"
            )
            return
        parts: list[str] = []
        for row in rows:
            calls = ", ".join(row["calls"])
            bands = ", ".join(b.replace("m", "") for b in row["bands"])
            modes = ", ".join(row["modes"])
            parts.append(
                f"<div style='margin-bottom:6px;'>"
                f"<b style='color:{style.TEXT}'>{row['operator'] or '(unknown)'}</b> "
                f"<span style='color:{style.TEXT_DIM}'>×{row['count']}</span><br>"
                f"<span style='color:{style.TEXT_DIM}'>worked:</span> {calls}<br>"
                f"<span style='color:{style.MULT}'>bands:</span> {bands} m &nbsp; "
                f"<span style='color:{style.ACCENT}'>modes:</span> {modes}"
                f"</div>"
            )
        self._detail_body.setText("".join(parts))


class SectionsWindow(QWidget):
    def __init__(self, session: LogSession) -> None:
        super().__init__()
        self.session = session
        self.setWindowTitle("PartyHams Logger — Sections")
        self.resize(960, 560)

        self._grid = SectionsGrid(session)
        self._map = SectionsMap(session)

        tabs = QTabWidget()
        tabs.addTab(self._grid, "Grid")
        tabs.addTab(self._map, "Map")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        session.add_listener(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._grid.refresh()
        self._map.refresh()
