"""
Design system.

Everything visual lives here: the palette, the global stylesheet and small
helpers for shadows and gradients, so the whole application can be restyled from
one place.

The look follows Windows 11: compact command bars, flat menus, one-pixel
borders, small corner radii and a neutral surface with the brand orange as the
single accent. Both a light and a dark palette exist; the default follows the
Windows colour mode and the View menu can pin one of them.

All colour names are module-level strings on purpose: widgets build their small
inline styles from ``theme.TEXT`` and friends, so ``set_mode()`` can repaint the
whole program by swapping the values and re-applying the stylesheet.
"""
from __future__ import annotations

import weakref

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPalette,
    QPixmap,
)
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QWidget,
)

from config import ASSETS_DIR, BRAND_FONT_NAME, FONTS_DIR


def _asset_url(name: str) -> str:
    """Forward-slashed path usable inside a Qt stylesheet (Windows-safe)."""
    path = ASSETS_DIR / name
    return path.as_posix() if path.exists() else ""


CHEVRON = _asset_url("chevron.png")
CHECKMARK = _asset_url("check.png")
RADIO_DOT = _asset_url("radio_dot.png")


# ---------------------------------------------------------------- palettes
# Windows 11 dark: window #202020, cards #2b2b2b, hairline borders.
DARK = {
    "MODE": "dark",
    "BG": "#202020",
    "BG_ELEVATED": "#272727",
    "SURFACE": "#2b2b2b",
    "SURFACE_HOVER": "#323232",
    "SURFACE_ACTIVE": "#3a3a3a",
    "BORDER": "#3a3a3a",
    "BORDER_SOFT": "#313131",
    "BORDER_STRONG": "#4a4a4a",
    "TEXT": "#ffffff",
    "TEXT_MUTED": "#c9c9c9",
    "TEXT_DIM": "#9a9a9a",
    "ACCENT": "#ff6a3d",
    "ACCENT_HOVER": "#ff8059",
    "ACCENT_PRESSED": "#e0552d",
    "ACCENT_SOFT": "#3a241d",
    "ACCENT_GLOW": "#ffa285",
    "ACCENT_TINT": "rgba(255, 106, 61, 46)",
    "SELECTION": "#33241f",
    "GOLD": "#f2c14e",
    "GREEN": "#4cc38a",
    "BLUE": "#4fa3f7",
    "VIOLET": "#9b8cf7",
    "VIOLET_SOFT": "#2a2540",
    "SCROLL_HANDLE": "#4f4f4f",
    "SCROLL_HANDLE_HOVER": "#6a6a6a",
    "OVERLAY": "rgba(16, 16, 16, 205)",
    "COVER_BG": "#232323",
    "MENU_SELECTED": "#3a3a3a",
    "SHADOW_ALPHA": 190,
}

# Windows 11 light: the default of a fresh Windows installation.
LIGHT = {
    "MODE": "light",
    "BG": "#f3f3f3",
    "BG_ELEVATED": "#f9f9f9",
    "SURFACE": "#ffffff",
    "SURFACE_HOVER": "#f4f4f4",
    "SURFACE_ACTIVE": "#e9e9e9",
    "BORDER": "#e1e1e1",
    "BORDER_SOFT": "#ececec",
    "BORDER_STRONG": "#d2d2d2",
    "TEXT": "#1a1a1a",
    "TEXT_MUTED": "#585858",
    "TEXT_DIM": "#8a8a8a",
    "ACCENT": "#e8552d",
    "ACCENT_HOVER": "#f26a44",
    "ACCENT_PRESSED": "#cf4522",
    "ACCENT_SOFT": "#fdeae4",
    "ACCENT_GLOW": "#b93d18",
    "ACCENT_TINT": "rgba(232, 85, 45, 32)",
    "SELECTION": "#f6e3dc",
    "GOLD": "#a9741a",
    "GREEN": "#107c41",
    "BLUE": "#0f6cbd",
    "VIOLET": "#6b4fd8",
    "VIOLET_SOFT": "#efeafd",
    "SCROLL_HANDLE": "#c3c3c3",
    "SCROLL_HANDLE_HOVER": "#a4a4a4",
    "OVERLAY": "rgba(20, 20, 20, 210)",
    "COVER_BG": "#f0f0f0",
    "MENU_SELECTED": "#e9e9e9",
    "SHADOW_ALPHA": 90,
}

PALETTES = {"dark": DARK, "light": LIGHT}
MODE = "light"

# The live palette values. ``set_mode()`` below replaces them with the
# contents of the chosen palette; declaring them here keeps linters and
# type checkers aware of the names, which the widgets import directly.
BG: str = LIGHT["BG"]
BG_ELEVATED: str = LIGHT["BG_ELEVATED"]
SURFACE: str = LIGHT["SURFACE"]
SURFACE_HOVER: str = LIGHT["SURFACE_HOVER"]
SURFACE_ACTIVE: str = LIGHT["SURFACE_ACTIVE"]
BORDER: str = LIGHT["BORDER"]
BORDER_SOFT: str = LIGHT["BORDER_SOFT"]
BORDER_STRONG: str = LIGHT["BORDER_STRONG"]
TEXT: str = LIGHT["TEXT"]
TEXT_MUTED: str = LIGHT["TEXT_MUTED"]
TEXT_DIM: str = LIGHT["TEXT_DIM"]
ACCENT: str = LIGHT["ACCENT"]
ACCENT_HOVER: str = LIGHT["ACCENT_HOVER"]
ACCENT_PRESSED: str = LIGHT["ACCENT_PRESSED"]
ACCENT_SOFT: str = LIGHT["ACCENT_SOFT"]
ACCENT_GLOW: str = LIGHT["ACCENT_GLOW"]
ACCENT_TINT: str = LIGHT["ACCENT_TINT"]
SELECTION: str = LIGHT["SELECTION"]
GOLD: str = LIGHT["GOLD"]
GREEN: str = LIGHT["GREEN"]
BLUE: str = LIGHT["BLUE"]
VIOLET: str = LIGHT["VIOLET"]
VIOLET_SOFT: str = LIGHT["VIOLET_SOFT"]
SCROLL_HANDLE: str = LIGHT["SCROLL_HANDLE"]
SCROLL_HANDLE_HOVER: str = LIGHT["SCROLL_HANDLE_HOVER"]
OVERLAY: str = LIGHT["OVERLAY"]
COVER_BG: str = LIGHT["COVER_BG"]
MENU_SELECTED: str = LIGHT["MENU_SELECTED"]
SHADOW_ALPHA: int = LIGHT["SHADOW_ALPHA"]

FONT_STACK = (
    '"Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", '
    '"DejaVu Sans", sans-serif'
)
DISPLAY_STACK = (
    '"Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", "Inter", '
    '"Noto Sans", sans-serif'
)
MONO_STACK = '"Cascadia Mono", "Cascadia Code", "Consolas", monospace'

# The word "Glib" is drawn with the font that ships in assets/fonts. Its family
# name is read back from the file, so renaming the file never breaks the title.
# Size of the "Glib" word in the app bar, in points: noticeably larger than the
# 10.5 pt the title used before, but still one line of the bar.
BRAND_TITLE_PT = 22
_BRAND_FAMILY = ""
_FONTS_LOADED = False
_FONT_DIRS = (FONTS_DIR, ASSETS_DIR)


def register_fonts(force: bool = False) -> str:
    """Load the bundled font files and return the display family name.

    Qt only knows fonts installed on the system, so a font that travels with
    the program has to be registered once per process. Nothing happens (and
    the normal display stack is used) when the file is missing, which keeps a
    fresh checkout without the asset working.
    """
    global _BRAND_FAMILY, _FONTS_LOADED
    if _FONTS_LOADED and not force:
        return _BRAND_FAMILY
    _FONTS_LOADED = True

    families = []
    candidates = []
    for folder in _FONT_DIRS:
        candidates.append(folder / BRAND_FONT_NAME)
    for folder in _FONT_DIRS:
        if folder.is_dir():
            candidates.extend(sorted(folder.glob("*.ttf")))
            candidates.extend(sorted(folder.glob("*.otf")))
    seen = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family and family not in families:
                families.append(family)
        if families:
            break
    _BRAND_FAMILY = families[0] if families else ""
    return _BRAND_FAMILY


def brand_family() -> str:
    """The family of the bundled brand font, or "" when it is not there."""
    if not _FONTS_LOADED:
        register_fonts()
    return _BRAND_FAMILY


def _brand_stack() -> str:
    family = brand_family()
    return f'"{family}", {DISPLAY_STACK}' if family else DISPLAY_STACK


def _brand_weight() -> int:
    """600 for a system face that has a semibold, 400 for the bundled one."""
    return 400 if brand_family() else 600


def _apply_palette(values: dict) -> None:
    """Copy one palette into the module namespace."""
    globals().update({key: value for key, value in values.items() if key != "MODE"})


# Start with the light palette so the names exist even before apply_theme().
_apply_palette(LIGHT)


def current_mode() -> str:
    return MODE


def set_mode(mode: str | None = None) -> str:
    """Switch the palette. ``None``/``system`` follows the Windows colour mode."""
    global MODE
    if mode in (None, "", "system"):
        mode = _system_mode()
    mode = "dark" if str(mode).lower() == "dark" else "light"
    MODE = mode
    _apply_palette(PALETTES[mode])
    return mode


def _system_mode() -> str:
    """Ask Windows whether the user runs a dark or a light theme."""
    try:
        app = QApplication.instance()
        if app is not None and hasattr(app.styleHints(), "colorScheme"):
            scheme = app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return "dark"
    except Exception:
        pass
    return "light"


def build_stylesheet() -> str:
    """The Windows-style stylesheet for the palette that is active now."""
    return f"""
/* ------------------------------------------------------------- window */
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: {FONT_STACK};
    font-size: 9pt;
}}
QMainWindow, QDialog {{
    background-color: {BG};
}}
QToolTip {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 4px 8px;
}}
QWidget#ContentArea, QWidget#LibraryGrid, QWidget#GridHost {{
    background-color: {BG};
}}
QWidget#LibraryGrid, QWidget#GridHost {{
    background: transparent;
}}
QWidget#Chip {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}
QWidget#Chip:hover {{
    background-color: {SURFACE_HOVER};
    border-color: {BORDER_STRONG};
}}
QScrollArea#GridViewport {{
    background: transparent;
    border: none;
}}
QScrollArea#GridViewport > QWidget > QWidget {{
    background: transparent;
}}

/* ------------------------------------------------------------- typography */
QLabel {{
    background: transparent;
}}
QLabel#TitleLabel {{
    font-family: {DISPLAY_STACK};
    font-size: 15pt;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#HeroTitle {{
    font-family: {_brand_stack()};
    font-size: {BRAND_TITLE_PT}pt;
    /* The bundled face has one weight. A 600 request would be faked with a
       smeared outline, so the title uses the letterform as it was drawn. */
    font-weight: {_brand_weight()};
    color: {TEXT};
}}
QLabel#WelcomeTitle {{
    font-family: {_brand_stack()};
    font-size: 19pt;
    font-weight: 600;
    color: {TEXT};
    letter-spacing: -0.2px;
}}
QLabel#SubtitleLabel {{
    color: {TEXT_MUTED};
    font-size: 9pt;
}}
QLabel#MutedLabel {{
    color: {TEXT_DIM};
    font-size: 8pt;
}}
QLabel#SectionLabel {{
    color: {TEXT_DIM};
    font-size: 7.5pt;
    font-weight: 600;
    letter-spacing: 0.4px;
}}
QLabel#QuestionLabel {{
    color: {TEXT};
    background-color: {ACCENT_SOFT};
    border: 1px solid {BORDER};
    border-left: 3px solid {ACCENT};
    border-radius: 4px;
    padding: 8px 10px;
    font-size: 9pt;
}}

/* ------------------------------------------------------------- menu bar */
QMenuBar {{
    background-color: {SURFACE};
    border: none;
    padding: 2px 6px;
    color: {TEXT};
}}
QMenuBar::item {{
    background: transparent;
    padding: 3px 9px;
    border-radius: 4px;
    color: {TEXT};
}}
QMenuBar::item:selected {{
    background-color: {SURFACE_HOVER};
}}
QMenuBar::item:pressed {{
    background-color: {SURFACE_ACTIVE};
}}
QMenu {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: 4px;
    color: {TEXT};
}}
QMenu::item:selected {{
    background-color: {MENU_SELECTED};
    color: {TEXT};
}}
QMenu::item:disabled {{
    color: {TEXT_DIM};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}
QMenu::icon {{
    padding-left: 8px;
}}

/* ------------------------------------------------------------- bars */
QToolBar {{
    background-color: {BG_ELEVATED};
    border: none;
    border-bottom: 1px solid {BORDER_SOFT};
    padding: 3px 8px;
    spacing: 4px;
}}
QToolBar::separator {{
    background: {BORDER};
    width: 1px;
    margin: 5px 4px;
}}
QFrame#AppBar {{
    background-color: {BG_ELEVATED};
    border-bottom: 1px solid {BORDER};
}}
QFrame#CommandBar {{
    background-color: {BG_ELEVATED};
    border-bottom: 1px solid {BORDER_SOFT};
}}
QFrame#PageHeader {{
    background: transparent;
}}
QFrame#AccentLine {{
    background-color: {ACCENT};
    border: none;
    max-height: 2px;
}}
QFrame#SidebarPanel {{
    background-color: {BG_ELEVATED};
    border: none;
    border-right: 1px solid {BORDER};
}}
QFrame#ViewBar {{
    background: transparent;
}}

QStatusBar {{
    background-color: {BG_ELEVATED};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER_SOFT};
    padding: 1px 10px;
}}
QStatusBar::item {{
    border: none;
}}

/* ------------------------------------------------------------- inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 4px 8px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
    min-height: 20px;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{
    background-color: {SURFACE_HOVER};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
    background-color: {SURFACE};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    color: {TEXT_DIM};
    background-color: {BG_ELEVATED};
}}
QLineEdit#SearchInput {{
    border-radius: 4px;
    padding: 4px 10px;
    background-color: {SURFACE};
}}
QLineEdit#SearchInput:focus {{
    background-color: {SURFACE};
    border: 1px solid {ACCENT};
}}
QComboBox {{
    padding-right: 22px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox::down-arrow {{
    image: url("{CHEVRON}");
    width: 10px;
    height: 6px;
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 3px;
    selection-background-color: {SURFACE_ACTIVE};
    selection-color: {TEXT};
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 14px;
    background: transparent;
    border: none;
}}

/* ------------------------------------------------------------- buttons */
QPushButton {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 4px 12px;
    color: {TEXT};
    font-weight: 400;
    min-height: 20px;
}}
QPushButton:hover {{
    background-color: {SURFACE_HOVER};
}}
QPushButton:pressed {{
    background-color: {SURFACE_ACTIVE};
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
    background-color: {BG_ELEVATED};
}}
QPushButton#PrimaryButton {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#PrimaryButton:pressed {{
    background-color: {ACCENT_PRESSED};
}}
QPushButton#GhostButton {{
    background: transparent;
    border: 1px solid transparent;
    color: {TEXT};
}}
QPushButton#GhostButton:hover {{
    background-color: {SURFACE_HOVER};
    border-color: {BORDER_SOFT};
}}
QPushButton#DangerButton {{
    background-color: transparent;
    border: 1px solid {BORDER_STRONG};
    color: {ACCENT_GLOW};
}}
QPushButton#DangerButton:hover {{
    background-color: {ACCENT_SOFT};
    border-color: {ACCENT};
}}

QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 3px 7px;
    color: {TEXT};
}}
QToolButton:hover {{
    background-color: {SURFACE_HOVER};
    border-color: {BORDER_SOFT};
}}
QToolButton:pressed {{
    background-color: {SURFACE_ACTIVE};
}}
QToolButton:checked {{
    background-color: {SURFACE_ACTIVE};
    border: 1px solid {BORDER_STRONG};
    color: {TEXT};
}}
QToolButton#IconButton {{
    padding: 3px;
    border-radius: 4px;
}}
QToolButton#FilterChip {{
    background-color: {SURFACE};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 9pt;
}}
QToolButton#FilterChip:hover {{
    background-color: {SURFACE_HOVER};
    color: {TEXT};
}}
QToolButton#FilterChip:checked {{
    background-color: {ACCENT_SOFT};
    color: {ACCENT_GLOW};
    border: 1px solid {ACCENT};
}}
QToolButton#ViewButton {{
    padding: 4px 9px;
    color: {TEXT_MUTED};
}}
QToolButton#ViewButton:checked {{
    background-color: {SURFACE_ACTIVE};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
}}
QToolButton#ToolBarButton {{
    padding: 4px 9px;
    border-radius: 4px;
    color: {TEXT};
}}

/* ------------------------------------------------------------- toggles */
QCheckBox, QRadioButton {{
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 3px;
    border: 1px solid {BORDER_STRONG};
    background-color: {SURFACE};
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    image: url("{CHECKMARK}");
}}
QRadioButton::indicator:checked {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    image: url("{RADIO_DOT}");
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {ACCENT};
}}

/* ------------------------------------------------------------- containers */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 16px 12px 10px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
    color: {TEXT};
    font-size: 9pt;
    font-weight: 600;
}}
QFrame#SelectionBar {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
}}
QFrame#Toast {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
}}
QFrame#Chip {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QFrame#CoverFrame {{
    background-color: {COVER_BG};
    border: none;
    border-radius: 4px;
}}
QFrame#Divider {{
    background-color: {BORDER};
    border: none;
}}
QFrame#Divider[orientation="horizontal"] {{
    max-height: 1px;
}}
QFrame#Divider[orientation="vertical"] {{
    max-width: 1px;
}}
QFrame#HeroBar {{
    background-color: {BG_ELEVATED};
    border-bottom: 1px solid {BORDER_SOFT};
}}
QFrame#ToastBar[kind="info"] {{ background-color: {BLUE}; }}
QFrame#ToastBar[kind="success"] {{ background-color: {GREEN}; }}
QFrame#ToastBar[kind="warning"] {{ background-color: {GOLD}; }}
QFrame#ToastBar[kind="error"] {{ background-color: {ACCENT}; }}
QLabel#ToastText {{
    color: {TEXT};
    font-size: 12px;
    background: transparent;
}}
QLabel#SelectionCount {{
    color: {TEXT};
    font-weight: 700;
    font-size: 13px;
    background: transparent;
}}
QPushButton#SelectionAction {{
    background: transparent;
    border: 1px solid transparent;
    color: {TEXT_MUTED};
    padding: 6px 11px;
    border-radius: 4px;
}}
QPushButton#SelectionAction:hover {{
    background-color: {SURFACE_HOVER};
    color: {TEXT};
}}
QToolButton#SelectionClose {{
    border: none;
    color: {TEXT_DIM};
    font-size: 14px;
    padding: 4px;
}}
QToolButton#SelectionClose:hover {{
    color: {TEXT};
}}
QFrame#EmptyState {{
    background: transparent;
}}

/* ------------------------------------------------------------- lists */
QListWidget, QTreeWidget, QTableWidget, QTableView {{
    background-color: transparent;
    border: none;
    outline: none;
    alternate-background-color: transparent;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 5px 8px;
    border-radius: 4px;
    color: {TEXT};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {SURFACE_HOVER};
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {SURFACE_ACTIVE};
    color: {TEXT};
}}
QListWidget#SeriesList::item {{
    padding: 1px;
    margin: 1px 4px;
    border-radius: 4px;
    border-left: 3px solid transparent;
}}
QListWidget#SeriesList::item:hover {{
    background-color: {SURFACE_HOVER};
}}
QListWidget#SeriesList::item:selected {{
    background-color: {SELECTION};
    border-left: 3px solid {ACCENT};
}}
QListWidget#NavList {{
    background: transparent;
}}
QListWidget#NavList::item {{
    padding: 1px;
    margin: 1px 6px;
    border-radius: 4px;
    border-left: 3px solid transparent;
}}
QListWidget#NavList::item:selected {{
    background-color: {SELECTION};
    border-left: 3px solid {ACCENT};
}}
QTableView#BooksTable {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    gridline-color: transparent;
    selection-background-color: {SELECTION};
    selection-color: {TEXT};
    alternate-background-color: {BG_ELEVATED};
}}
QHeaderView::section {{
    background-color: {BG_ELEVATED};
    font-size: 8.5pt;
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid transparent;
    padding: 5px 8px;
    font-weight: 600;
}}
QHeaderView::section:hover {{
    background-color: {SURFACE_HOVER};
    color: {TEXT};
}}
QTableCornerButton::section {{
    background-color: {BG_ELEVATED};
    border: none;
}}

/* ------------------------------------------------------------- scroll */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {SCROLL_HANDLE};
    border-radius: 3px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {SCROLL_HANDLE_HOVER};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {SCROLL_HANDLE};
    border-radius: 3px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {SCROLL_HANDLE_HOVER};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0;
    background: transparent;
}}
QSplitter::handle {{
    background-color: {BORDER};
    width: 1px;
}}

/* ------------------------------------------------------------- progress */
QProgressBar {{
    background-color: {SURFACE_ACTIVE};
    border: none;
    border-radius: 3px;
    text-align: center;
    height: 6px;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 3px;
}}
QProgressDialog {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
}}

/* ------------------------------------------------------------- tabs */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background-color: {BG_ELEVATED};
    padding: 8px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {TEXT_MUTED};
    padding: 5px 12px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
}}
QTabBar::tab:hover {{
    color: {TEXT};
    background: {SURFACE_HOVER};
}}
QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}
"""


def card_stylesheet() -> str:
    """Card state rules; dynamic properties are set by BookCard."""
    return f"""
QFrame#BookCard {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QFrame#BookCard:hover {{
    background-color: {SURFACE_HOVER};
    border: 1px solid {BORDER_STRONG};
}}
QFrame#BookCard[selected="true"] {{
    border: 2px solid {ACCENT};
    background-color: {ACCENT_SOFT};
}}
QFrame#BookCard[isRead="true"] {{
    background-color: {BG_ELEVATED};
}}
QFrame#BookCard[favorite="true"] {{
    border: 1px solid {BORDER};
}}
QFrame#BookCard[favorite="true"]:hover {{
    border: 1px solid {BORDER_STRONG};
}}

/* Card children. They used to carry their own stylesheets, which meant a
   hundred style recomputations per screenful of cards; the rules live here
   now and the card only toggles dynamic properties. */
QLabel#CardCover {{
    color: {TEXT_DIM};
    font-size: 8pt;
    background: transparent;
}}
QLabel#CardTitle {{
    color: {TEXT};
    font-size: 9pt;
    font-weight: 600;
    background: transparent;
}}
QFrame#BookCard[isRead="true"] QLabel#CardTitle {{
    color: {TEXT_MUTED};
}}
QLabel#CardInfo {{
    color: {TEXT_MUTED};
    font-size: 8pt;
    background: transparent;
}}
QLabel#CardRating {{
    color: {GOLD};
    font-size: 8pt;
    background: transparent;
}}
QLabel#CardStatusDot {{
    color: {TEXT_DIM};
    font-size: 7pt;
    background: transparent;
}}
QLabel#CardStatus {{
    color: {TEXT_DIM};
    font-size: 8pt;
    background: transparent;
}}
QFrame#BookCard[isRead="true"] QLabel#CardStatusDot,
QFrame#BookCard[isRead="true"] QLabel#CardStatus {{
    color: {GREEN};
}}
QLabel#CardFormatBadge {{
    color: #ffffff;
    font-size: 7pt;
    font-weight: 700;
    background: rgba(16, 16, 16, 150);
    border-radius: 3px;
    padding: 1px 5px;
}}
QLabel#CardFormatBadge[format="cbz"] {{
    color: #8fc7ff;
}}
QLabel#CardFormatBadge[format="cbr"] {{
    color: #ffb199;
}}
QLabel#CardFormatBadge[format="cb7"] {{
    color: #c8b6ff;
}}
QLabel#CardFormatBadge[format="cbt"] {{
    color: #ffd98a;
}}
QLabel#CardFormatBadge[format="pdf"] {{
    color: #ff9d9d;
}}
QLabel#CardFavoriteBadge {{
    color: #f5c451;
    font-size: 10pt;
    background: {OVERLAY};
    border-radius: 9px;
}}
QWidget#CardQuickBar {{
    background: {OVERLAY};
    border-radius: 4px;
}}
QToolButton#CardQuickButton {{
    border: none;
    background: transparent;
    color: #ffffff;
    font-size: 9pt;
    border-radius: 4px;
}}
QToolButton#CardQuickButton:hover {{
    background: {ACCENT};
    color: #ffffff;
}}
"""


def build_palette() -> QPalette:
    """Native palette, so dialogs and arrows match the stylesheet."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_HOVER))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(ACCENT_GLOW))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_DIM))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_DIM))
    return palette


def logo_pixmap(size: int = 46) -> QPixmap:
    """The application icon, rounded and scaled for the header."""
    icon_path = ASSETS_DIR / "icon.png"
    if icon_path.exists():
        source = QPixmap(str(icon_path))
        if not source.isNull():
            scaled = source.scaled(
                size * 2,
                size * 2,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            return rounded_pixmap(scaled, size // 4).scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    return gradient_pixmap(size, size, ACCENT, ACCENT_HOVER, max(4, size // 4))


class _WindowsStyle(QProxyStyle):
    """Fusion, minus the permanently underlined menu accelerators.

    Windows 11 only underlines the Alt accelerators while Alt is held down;
    Qt draws them all the time, which is what makes a menu bar look old. The
    letters still work, they are just not printed with a rule under them.
    """

    def styleHint(self, hint, option=None, widget=None, return_data=None):  # noqa: N802
        if hint == QStyle.StyleHint.SH_UnderlineShortcut:
            return 0
        return super().styleHint(hint, option, widget, return_data)


# Widgets that paint a few of their colours inline (they are created once and
# live for the whole session) register here; a palette change calls their
# ``restyle()`` so switching light/dark is instant instead of rebuilding the
# window. Weak references keep closed windows out of the list.
_restylers: "list[weakref.ReferenceType]" = []


def register_restyle(widget) -> None:
    """Call ``widget.restyle()`` whenever the colour mode changes."""
    if getattr(widget, "restyle", None) is None:
        return
    _restylers.append(weakref.ref(widget))


def _run_restylers() -> None:
    alive = []
    for reference in _restylers:
        widget = reference()
        if widget is None:
            continue
        alive.append(reference)
        try:
            widget.restyle()
        except RuntimeError:  # the C++ object is already gone
            continue
    _restylers[:] = alive


# The proxy style and its base stay alive for the whole process. Letting the
# base be collected while Qt still points at it is a dangling pointer, and
# replacing the application style on every repaint is an easy way to crash.
_STYLE: "tuple[QProxyStyle, QStyle] | None" = None


def _install_style(app) -> None:
    global _STYLE
    if _STYLE is not None:
        return
    base = QStyleFactory.create("Fusion")
    if base is None:
        base = app.style()
    proxy = _WindowsStyle(base)
    _STYLE = (proxy, base)
    app.setStyle(proxy)


def apply_theme(app, mode: str | None = None):
    """Apply the palette to the whole application.

    ``mode`` is ``light``, ``dark`` or ``system`` (the default). It is stored
    with the other view settings so the choice survives a restart.
    """
    if mode is None:
        try:
            from utils.settings import settings

            mode = settings.get_view("theme", "system")
        except Exception:
            mode = "system"
    set_mode(mode)
    _install_style(app)
    # The brand font has to exist in Qt's database before the stylesheet that
    # names it is parsed, otherwise the title falls back for this session.
    register_fonts()
    app.setPalette(build_palette())
    app.setStyleSheet(build_stylesheet() + card_stylesheet())
    _run_restylers()
    return MODE


# ---------------------------------------------------------------- helpers
def text_height(widget, extra: int = 0) -> int:
    """The height ``widget`` needs to draw its current font without clipping.

    Qt stylesheets set the font at polish time, so a label created before the
    application stylesheet exists still reports the old font. Polishing it
    first and then asking its font metrics is what keeps a title or a counter
    from being cut in half on a 125 % Windows display.
    """
    try:
        widget.ensurePolished()
        return widget.fontMetrics().height() + extra
    except AttributeError:  # not a widget (an icon size, say)
        return extra


def add_shadow(widget: QWidget, blur: int = 26, y_offset: int = 8,
               color: str = "#000000", alpha: int | None = None) -> QGraphicsDropShadowEffect:
    """Attach a soft drop shadow (used on floating panels, not on every card)."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    shadow_color = QColor(color)
    shadow_color.setAlpha(SHADOW_ALPHA if alpha is None else alpha)
    effect.setColor(shadow_color)
    widget.setGraphicsEffect(effect)
    return effect


def gradient_pixmap(width: int, height: int, start: str, end: str,
                    radius: int = 0, diagonal: bool = True) -> QPixmap:
    """A small gradient tile used for logo tiles and banners."""
    pixmap = QPixmap(max(1, width), max(1, height))
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    gradient = QLinearGradient(0, 0, width if diagonal else 0, height)
    gradient.setColorAt(0.0, QColor(start))
    gradient.setColorAt(1.0, QColor(end))
    if radius:
        from PyQt6.QtGui import QPainterPath

        path = QPainterPath()
        path.addRoundedRect(0, 0, width, height, radius, radius)
        painter.fillPath(path, gradient)
    else:
        painter.fillRect(0, 0, width, height, gradient)
    painter.end()
    return pixmap


def rounded_pixmap(pixmap: QPixmap, radius: int = 12) -> QPixmap:
    """Clip a cover image to rounded corners (QSS cannot do it for pixmaps)."""
    from PyQt6.QtGui import QPainterPath

    if pixmap.isNull():
        return pixmap
    rounded = QPixmap(pixmap.size())
    rounded.fill(QColor(0, 0, 0, 0))
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return rounded
