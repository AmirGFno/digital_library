"""The word "Glib" is drawn with the font that ships with the program.

A bundled font is invisible to Qt until the file is registered, and a title in
a font that is not there silently falls back to the system one. These tests
pin both halves: the file is in the repository and packaged, and the app bar
really uses it — at a size the header has room for.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _font_file():
    from config import ASSETS_DIR, BRAND_FONT_NAME, FONTS_DIR

    for folder in (ASSETS_DIR, FONTS_DIR):
        path = folder / BRAND_FONT_NAME
        if path.is_file():
            return path
    pytest.skip("the bundled font is not in the checkout")


def test_the_font_file_ships_with_the_program():
    from build_config import DATAS

    path = _font_file()
    # A real TrueType/OpenType file starts with one of these four tags.
    with path.open("rb") as handle:
        signature = handle.read(4)
    assert signature in (b"\x00\x01\x00\x00", b"true", b"OTTO", b"ttcf"), signature

    packed = dict(DATAS)
    relative = str(path.relative_to(ROOT))
    assert relative in packed, "the font is not packaged"
    # ... and it lands next to the other assets, where config looks for it.
    assert "assets" in packed[relative].replace("\\", "/")


def test_the_font_is_registered_with_qt(qt_app):
    from PyQt6.QtGui import QFontDatabase

    from ui import theme

    _font_file()
    family = theme.register_fonts()
    assert family, "the bundled font did not load"
    assert family in QFontDatabase.families()
    assert theme.brand_family() == family


def test_the_app_bar_draws_the_name_in_the_bundled_font(qt_app, monkeypatch):
    from PyQt6.QtCore import QSize

    from ui import layout, theme

    _font_file()
    theme.apply_theme(qt_app)
    family = theme.brand_family()
    assert family

    monkeypatch.setattr(layout, "screen_size", lambda widget=None: QSize(1400, 900))

    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    window.show()
    for _ in range(4):
        qt_app.processEvents()

    title = window.app_title
    title.ensurePolished()
    assert title.font().family() == family
    # 18 pt is what the user asked for; count points, not pixels.
    assert round(title.font().pointSizeF()) == theme.BRAND_TITLE_PT

    # The bigger word must fit in the bar, or its bottom would be clipped.
    needed = theme.text_height(title)
    assert title.height() >= needed, (title.height(), needed)
    bottom = title.mapTo(window.hero, title.rect().bottomLeft()).y()
    assert bottom <= window.hero.height()
    assert window.hero.height() >= needed
    window.close()


def test_the_title_still_works_without_the_bundled_font(qt_app, monkeypatch, tmp_path):
    """A checkout without the asset must not crash or lose the title."""
    from ui import theme

    monkeypatch.setattr(theme, "_FONT_DIRS", (tmp_path,))
    monkeypatch.setattr(theme, "_FONTS_LOADED", False)
    monkeypatch.setattr(theme, "_BRAND_FAMILY", "")

    assert theme.register_fonts() == ""
    assert theme.brand_family() == ""
    # Without the family name the stylesheet falls back to the system stack.
    assert theme._brand_stack() == theme.DISPLAY_STACK

    theme.apply_theme(qt_app)
    monkeypatch.undo()
    theme.register_fonts(force=True)
