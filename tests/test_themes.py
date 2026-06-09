"""The built-in theme catalog (data layer — no QApplication needed)."""

from __future__ import annotations

from partyhams.ui import style


def test_six_themes_three_dark_three_light():
    names = style.theme_names()
    assert len(names) == 6
    darks = [n for n, dark in names if dark]
    lights = [n for n, dark in names if not dark]
    assert len(darks) == 3
    assert len(lights) == 3
    # Dark themes are listed first (the menu groups them).
    assert all(dark for _n, dark in names[:3])
    assert not any(dark for _n, dark in names[3:])


def test_defaults_exist_and_match_brightness():
    assert style.DEFAULT_DARK in style.THEMES
    assert style.DEFAULT_LIGHT in style.THEMES
    assert style.THEMES[style.DEFAULT_DARK].dark is True
    assert style.THEMES[style.DEFAULT_LIGHT].dark is False


def test_build_qss_uses_palette_colors():
    p = style.THEMES[style.DEFAULT_LIGHT]
    qss = style.build_qss(p)
    assert p.accent in qss
    assert p.bg in qss
    assert p.on_accent in qss  # button text color is palette-driven
