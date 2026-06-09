"""Sections worked/needed window — a per-band multiplier grid (N1MM-style).

All ARRL/RAC sections, grouped into columns by call district (0–9, VE, DX). Each
section shows a small coloured pip per band (160→6 m): green = worked on that band,
dim = needed. The Mode filter scopes it (Any / CW / Phone / Digital), giving the
band, mode, and band+mode views; the section name is green if worked on any band.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from partyhams.app.session import LogSession
from partyhams.contest.sections import SECTION_GROUPS
from partyhams.ui import style

# Bands shown as pips, left→right. (Sections worked on other bands still count as
# worked; these are just the columns drawn.)
_BAND_ORDER = ["160m", "80m", "40m", "20m", "15m", "10m", "6m"]
_COLUMNS = 6  # district blocks per row


class SectionsWindow(QWidget):
    def __init__(self, session: LogSession) -> None:
        super().__init__()
        self.session = session
        self.setWindowTitle("PartyHams Logger — Sections")
        self.resize(900, 540)

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
        session.add_listener(self.refresh)
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
