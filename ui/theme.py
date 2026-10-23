"""
Application theme.

One central stylesheet keeps every window (main window, dialogs, menus) visually
consistent, including the native-ish scroll bars and tables.
"""

ACCENT = "#e8552d"
ACCENT_HOVER = "#ff6a3f"
ACCENT_PRESSED = "#c94522"
SECONDARY = "#7c4dff"

DARK_STYLESHEET = f"""
QWidget {{
    background-color: #14161a;
    color: #e8eaed;
    font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: #14161a;
}}
QLabel {{
    background: transparent;
}}
QLabel#TitleLabel {{
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
}}
QLabel#SubtitleLabel {{
    color: #9aa3ad;
    font-size: 12px;
}}
QLabel#QuestionLabel {{
    color: #e7c46a;
    background-color: #24211a;
    border: 1px solid #3a3427;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
    font-weight: 600;
}}
QLabel#SectionLabel {{
    color: #9aa3ad;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
}}
QMenuBar {{
    background-color: #1a1d22;
    border-bottom: 1px solid #2a2f37;
    padding: 3px 6px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 10px;
    border-radius: 6px;
}}
QMenuBar::item:selected {{
    background-color: #2a2f37;
}}
QMenu {{
    background-color: #1d2026;
    border: 1px solid #343a43;
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 14px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background-color: {ACCENT};
    color: #ffffff;
}}
QMenu::separator {{
    height: 1px;
    background: #343a43;
    margin: 5px 8px;
}}
QToolBar {{
    background-color: #1a1d22;
    border: none;
    border-bottom: 1px solid #2a2f37;
    padding: 6px;
    spacing: 8px;
}}
QToolBar QLabel {{
    color: #9aa3ad;
    font-size: 12px;
}}
QStatusBar {{
    background-color: #1a1d22;
    color: #9aa3ad;
    border-top: 1px solid #2a2f37;
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: #1d2026;
    border: 1px solid #343a43;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: #5c646e;
    background-color: #191c21;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: #1d2026;
    border: 1px solid #343a43;
    selection-background-color: {ACCENT};
    outline: none;
}}
QPushButton {{
    background-color: #262b33;
    border: 1px solid #343a43;
    border-radius: 6px;
    padding: 7px 16px;
    color: #e8eaed;
}}
QPushButton:hover {{
    background-color: #2f3540;
    border-color: #3f4753;
}}
QPushButton:pressed {{
    background-color: #1f242b;
}}
QPushButton:disabled {{
    color: #5c646e;
    border-color: #2a2f37;
}}
QPushButton#PrimaryButton {{
    background-color: {ACCENT};
    border: none;
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#PrimaryButton:pressed {{
    background-color: {ACCENT_PRESSED};
}}
QPushButton#DangerButton {{
    background-color: transparent;
    border: 1px solid #7a2c1c;
    color: #ff8a70;
}}
QToolButton {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 5px;
}}
QToolButton:hover {{
    background-color: #2a2f37;
}}
QToolButton:checked {{
    background-color: {ACCENT};
}}
QCheckBox, QRadioButton {{
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
}}
QGroupBox {{
    border: 1px solid #2a2f37;
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 12px;
    color: #c9ced6;
}}
QListWidget, QTreeWidget, QTableWidget {{
    background-color: #1a1d22;
    border: 1px solid #2a2f37;
    border-radius: 8px;
    outline: none;
    alternate-background-color: #1e2228;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 7px 8px;
    border-radius: 6px;
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: #333944;
    color: #ffffff;
}}
QListWidget#SeriesList::item {{
    padding: 8px 10px;
    margin: 1px 4px;
    color: #c9ced6;
}}
QListWidget#SeriesList::item:selected {{
    background-color: {ACCENT};
    color: #ffffff;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #3a414b;
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: #4a525e;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #3a414b;
    border-radius: 5px;
    min-width: 28px;
}}
QSplitter::handle {{
    background-color: #23272e;
    width: 2px;
}}
QFrame#BookCard {{
    background-color: #1a1d22;
    border: 1px solid #262b33;
    border-radius: 10px;
}}
QFrame#BookCard:hover {{
    border: 1px solid {ACCENT};
    background-color: #1e2228;
}}
QFrame#Sidebar {{
    background-color: #16191e;
    border-right: 1px solid #23272e;
}}
QProgressBar {{
    background-color: #1d2026;
    border: 1px solid #2a2f37;
    border-radius: 6px;
    text-align: center;
    height: 8px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 5px;
}}
QTabWidget::pane {{
    border: 1px solid #2a2f37;
    border-radius: 8px;
}}
QTabBar::tab {{
    background: #1a1d22;
    padding: 7px 14px;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}}
QTabBar::tab:selected {{
    background: {ACCENT};
}}
QToolTip {{
    background-color: #24282f;
    color: #e8eaed;
    border: 1px solid #343a43;
    padding: 5px;
    border-radius: 4px;
}}
"""


def apply_theme(app):
    """Apply the dark theme to the whole application."""
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET + CARD_STATE_STYLESHEET)


# Card state accents (dynamic properties set by BookCard)
CARD_STATE_STYLESHEET = """
QFrame#BookCard[selected="true"] {
    border: 2px solid #e8552d;
    background-color: #23262d;
}
QFrame#BookCard[isRead="true"] {
    border: 1px solid #2b5f3f;
}
QFrame#BookCard[favorite="true"] {
    border: 1px solid #8a6300;
}
QFrame#BookCard[favorite="true"]:hover,
QFrame#BookCard[isRead="true"]:hover {
    border: 1px solid #e8552d;
}
"""
