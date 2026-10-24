"""
Design system.

Everything visual lives here: the palette, the global stylesheet and small
helpers for shadows and gradients, so the whole application can be restyled from
one place.

The look is a dark "midnight" surface with warm ember accents, soft glass panels
and generous rounding. Gradients are used sparingly (hero header, selection bar,
cover overlays) because Qt stylesheets cannot animate them.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPalette,
    QPixmap,
)
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from config import ASSETS_DIR


def _asset_url(name: str) -> str:
    """Forward-slashed path usable inside a Qt stylesheet (Windows-safe)."""
    path = ASSETS_DIR / name
    return path.as_posix() if path.exists() else ""


CHEVRON = _asset_url("chevron.png")
CHECKMARK = _asset_url("check.png")
RADIO_DOT = _asset_url("radio_dot.png")

# ---------------------------------------------------------------- palette
BG = "#0a0c10"
BG_ELEVATED = "#0f1218"
SURFACE = "#141822"
SURFACE_HOVER = "#1a1f2b"
SURFACE_ACTIVE = "#202634"
BORDER = "#232a38"
BORDER_SOFT = "#1b2130"
BORDER_STRONG = "#2f3949"
TEXT = "#eef1f7"
TEXT_MUTED = "#9aa4b8"
TEXT_DIM = "#6b7588"

ACCENT = "#ff5b3d"
ACCENT_HOVER = "#ff7357"
ACCENT_PRESSED = "#e0462a"
ACCENT_SOFT = "#3a1d17"
ACCENT_GLOW = "#ff8a70"

VIOLET = "#8b5cf6"
VIOLET_SOFT = "#241b3d"
GOLD = "#f5b544"
GREEN = "#34d399"
BLUE = "#4aa8ff"

# Kept for backwards compatibility with older modules.
SECONDARY = VIOLET

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", sans-serif'
DISPLAY_STACK = '"Segoe UI Variable Display", "Segoe UI Semibold", "Inter", "Noto Sans", sans-serif'
MONO_STACK = '"Cascadia Code", "JetBrains Mono", "Consolas", monospace'


DARK_STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: {FONT_STACK};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {BG};
}}
QToolTip {{
    background-color: {SURFACE_ACTIVE};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 6px 9px;
}}

/* ------------------------------------------------------------ typography */
QLabel {{
    background: transparent;
}}
QLabel#TitleLabel {{
    font-family: {DISPLAY_STACK};
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
}}
QLabel#HeroTitle {{
    font-family: {DISPLAY_STACK};
    font-size: 19px;
    font-weight: 700;
    color: #ffffff;
}}
QLabel#SubtitleLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#MutedLabel {{
    color: {TEXT_DIM};
    font-size: 11px;
}}
QLabel#SectionLabel {{
    color: {TEXT_DIM};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#QuestionLabel {{
    color: #ffd79a;
    background-color: rgba(245, 181, 68, 26);
    border: 1px solid rgba(245, 181, 68, 76);
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 13px;
    font-weight: 600;
}}

/* ------------------------------------------------------------ chrome */
QMenuBar {{
    background-color: {BG_ELEVATED};
    border-bottom: 1px solid {BORDER_SOFT};
    padding: 2px 8px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 11px;
    border-radius: 7px;
    color: {TEXT_MUTED};
}}
QMenuBar::item:selected {{
    background-color: {SURFACE_HOVER};
    color: {TEXT};
}}
QMenu {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 12px;
    padding: 8px;
}}
QMenu::item {{
    padding: 8px 28px 8px 14px;
    border-radius: 7px;
    color: {TEXT};
}}
QMenu::item:selected {{
    background-color: {ACCENT};
    color: #ffffff;
}}
QMenu::item:disabled {{
    color: {TEXT_DIM};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 6px 10px;
}}
QMenu::icon {{
    padding-left: 8px;
}}

QToolBar {{
    background-color: {BG};
    border: none;
    border-bottom: 1px solid {BORDER_SOFT};
    padding: 10px 14px;
    spacing: 10px;
}}
QToolBar::separator {{
    background: {BORDER};
    width: 1px;
    margin: 6px 4px;
}}

QStatusBar {{
    background-color: {BG_ELEVATED};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER_SOFT};
    padding: 2px 12px;
}}
QStatusBar::item {{
    border: none;
}}

/* ------------------------------------------------------------ inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 7px 11px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{
    border-color: {BORDER_STRONG};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
    background-color: {SURFACE_HOVER};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    color: {TEXT_DIM};
    background-color: {BG_ELEVATED};
}}
QLineEdit#SearchInput {{
    border-radius: 12px;
    padding: 8px 14px;
    font-size: 13px;
    background-color: {SURFACE};
}}
QLineEdit#SearchInput:focus {{
    background-color: {SURFACE_HOVER};
    border: 1px solid {ACCENT};
}}
QComboBox {{
    padding-right: 24px;
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox::down-arrow {{
    image: url("{CHEVRON}");
    width: 12px;
    height: 8px;
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 10px;
    padding: 6px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 16px;
    background: transparent;
    border: none;
}}

/* ------------------------------------------------------------ buttons */
QPushButton {{
    background-color: {SURFACE_ACTIVE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 16px;
    color: {TEXT};
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: #262d3c;
    border-color: {BORDER_STRONG};
}}
QPushButton:pressed {{
    background-color: {SURFACE};
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER_SOFT};
    background-color: {BG_ELEVATED};
}}
QPushButton#PrimaryButton {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
    font-weight: 700;
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
    border: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}
QPushButton#GhostButton:hover {{
    color: {TEXT};
    border-color: {BORDER_STRONG};
    background-color: {SURFACE_HOVER};
}}
QPushButton#DangerButton {{
    background-color: transparent;
    border: 1px solid #7a2c1c;
    color: #ff9b83;
}}
QPushButton#DangerButton:hover {{
    background-color: rgba(255, 91, 61, 24);
}}

QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 6px 10px;
    color: {TEXT_MUTED};
}}
QToolButton:hover {{
    background-color: {SURFACE_HOVER};
    color: {TEXT};
}}
QToolButton:checked {{
    background-color: {ACCENT_SOFT};
    color: {ACCENT_GLOW};
    border: 1px solid rgba(255, 91, 61, 90);
}}
QToolButton#IconButton {{
    padding: 6px;
    border-radius: 10px;
}}

/* ------------------------------------------------------------ toggles */
QCheckBox, QRadioButton {{
    spacing: 9px;
    background: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1px solid {BORDER_STRONG};
    background-color: {SURFACE};
}}
QRadioButton::indicator {{
    border-radius: 9px;
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

/* ------------------------------------------------------------ containers */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 14px;
    margin-top: 16px;
    padding: 18px 14px 12px 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    left: 14px;
    color: {TEXT};
    font-size: 12px;
    font-weight: 700;
}}

QFrame#HeroBar {{
    background-color: {BG_ELEVATED};
    border-bottom: 1px solid {BORDER_SOFT};
}}
QWidget#ContentArea, QWidget#LibraryGrid, QWidget#GridHost {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #0e121b, stop:0.5 {BG}, stop:1 #07090d);
}}
QWidget#LibraryGrid, QWidget#GridHost {{
    background: transparent;
}}
QScrollArea#GridViewport {{
    background: transparent;
}}
QScrollArea#GridViewport > QWidget > QWidget {{
    background: transparent;
}}
QFrame#CommandBar {{
    background-color: {BG_ELEVATED};
    border-bottom: 1px solid {BORDER_SOFT};
}}
QToolButton#FilterChip {{
    background-color: {SURFACE};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QToolButton#FilterChip:hover {{
    background-color: {SURFACE_HOVER};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
}}
QToolButton#FilterChip:checked {{
    background-color: rgba(245, 181, 68, 34);
    color: {GOLD};
    border: 1px solid rgba(245, 181, 68, 110);
}}
QFrame#AccentLine {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {ACCENT}, stop:0.35 {ACCENT_GLOW},
                                stop:0.75 rgba(255, 138, 112, 40),
                                stop:1 rgba(255, 138, 112, 0));
    border: none;
}}
QFrame#SidebarPanel {{
    background-color: {BG_ELEVATED};
    border-right: 1px solid {BORDER_SOFT};
}}
QFrame#SelectionBar {{
    background-color: {SURFACE_ACTIVE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 16px;
}}
QFrame#Toast {{
    background-color: {SURFACE_ACTIVE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 12px;
}}
QFrame#Chip {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#CoverFrame {{
    background-color: {BG_ELEVATED};
    border: none;
    border-radius: 12px;
}}
QFrame#Divider {{
    background-color: {BORDER_SOFT};
    max-height: 1px;
    border: none;
}}

/* ------------------------------------------------------------ lists */
QListWidget, QTreeWidget, QTableWidget {{
    background-color: transparent;
    border: none;
    outline: none;
    alternate-background-color: transparent;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 6px 8px;
    border-radius: 9px;
    color: {TEXT_MUTED};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {SURFACE_HOVER};
    color: {TEXT};
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {SURFACE_ACTIVE};
    color: {TEXT};
}}
QListWidget#SeriesList::item {{
    padding: 2px;
    margin: 2px 0;
    border-radius: 10px;
    color: {TEXT};
}}
QListWidget#SeriesList::item:selected {{
    background-color: {SURFACE_ACTIVE};
}}
QTableWidget {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    gridline-color: {BORDER_SOFT};
    selection-background-color: {SURFACE_ACTIVE};
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background-color: {BG_ELEVATED};
    font-size: 11px;
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 8px 10px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background-color: {BG_ELEVATED};
    border: none;
}}

/* ------------------------------------------------------------ scroll */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 3px 2px;
}}
QScrollBar::handle:vertical {{
    background: #2b3342;
    border-radius: 5px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: #3a4457;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
    margin: 2px 3px;
}}
QScrollBar::handle:horizontal {{
    background: #2b3342;
    border-radius: 5px;
    min-width: 32px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0;
    background: transparent;
}}
QSplitter::handle {{
    background-color: {BORDER_SOFT};
    width: 1px;
}}

/* ------------------------------------------------------------ progress */
QProgressBar {{
    background-color: {SURFACE};
    border: none;
    border-radius: 5px;
    text-align: center;
    height: 8px;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 5px;
}}
QProgressDialog {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 14px;
}}

/* ------------------------------------------------------------ tabs */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 12px;
    top: -1px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 14px;
    background-color: {BG_ELEVATED};
    padding: 10px;
}}
QTabBar::tab {{
    background-color: {SURFACE};
    color: {TEXT_MUTED};
    padding: 8px 18px;
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-right: 6px;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {TEXT};
    background: {SURFACE_HOVER};
}}
QTabBar::tab:selected {{
    background: {SURFACE_ACTIVE};
    color: {TEXT};
}}
"""


# Card state accents (dynamic properties set by BookCard)
CARD_STATE_STYLESHEET = f"""
QFrame#BookCard {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 16px;
}}
QFrame#BookCard:hover {{
    background-color: {SURFACE_HOVER};
    border: 1px solid {BORDER_STRONG};
}}
QFrame#BookCard[selected="true"] {{
    border: 2px solid {ACCENT};
    background-color: {SURFACE_ACTIVE};
}}
QFrame#BookCard[isRead="true"] {{
    background-color: {BG_ELEVATED};
}}
QFrame#BookCard[favorite="true"] {{
    border: 1px solid rgba(245, 181, 68, 110);
}}
QFrame#BookCard[favorite="true"]:hover {{
    border: 1px solid {GOLD};
}}
"""


def build_palette() -> QPalette:
    """Dark palette; keeps native widgets (dialogs, arrows, menus) consistent."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_HOVER))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE_ACTIVE))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(ACCENT_GLOW))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT_GLOW))
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
            return rounded_pixmap(scaled, size // 3).scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    return gradient_pixmap(size, size, ACCENT, "#ff9f68", max(8, size // 3))


def apply_theme(app):
    """Apply the dark theme to the whole application."""
    app.setStyle("Fusion")
    app.setPalette(build_palette())
    app.setStyleSheet(DARK_STYLESHEET + CARD_STATE_STYLESHEET)


# ---------------------------------------------------------------- helpers
def add_shadow(widget: QWidget, blur: int = 26, y_offset: int = 8,
               color: str = "#000000", alpha: int = 170) -> QGraphicsDropShadowEffect:
    """Attach a soft drop shadow (used on floating panels, not on every card)."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    shadow_color = QColor(color)
    shadow_color.setAlpha(alpha)
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
