"""
First-run welcome dialog.

The library owner asked for a *default folder*: choose it once, and everything
that appears in it later is added automatically on every start.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSize, Qt
from config import APP_NAME, APP_VERSION
from ui import layout as layout_tools
from ui import theme
from PyQt6.QtWidgets import (
    QWidget,
    QCheckBox,
    QFrame,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)



class WelcomeDialog(QDialog):
    """Ask for the library folder the first time the app runs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Digital Library")
        self._preferred_size = QSize(660, 620)
        self.folder: Optional[str] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- hero banner ------------------------------------------------
        hero = QFrame()
        hero.setObjectName("WelcomeHero")
        hero.setFixedHeight(148)
        hero.setStyleSheet(
            "QFrame#WelcomeHero {"
            " background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 {theme.ACCENT_SOFT}, stop:0.5 #1a1220, stop:1 {theme.BG_ELEVATED});"
            f" border-bottom: 2px solid {theme.ACCENT};"
            "}"
        )
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(28, 22, 28, 22)
        hero_layout.setSpacing(18)

        logo = QLabel()
        logo.setFixedSize(76, 76)
        logo.setPixmap(theme.gradient_pixmap(76, 76, theme.ACCENT, "#ff9f68", 22))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(logo)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(2)
        name = QLabel(APP_NAME)
        name.setStyleSheet(
            "color: #ffffff; font-size: 26px; font-weight: 800;"
        )
        tagline = QLabel("Your comics, beautifully organised.")
        tagline.setStyleSheet(f"color: {theme.ACCENT_GLOW}; font-size: 13px;")
        version = QLabel(f"version {APP_VERSION}")
        version.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        hero_text.addWidget(name)
        hero_text.addWidget(tagline)
        hero_text.addWidget(version)
        hero_layout.addLayout(hero_text)
        hero_layout.addStretch(1)
        layout.addWidget(hero)

        # ---- body -------------------------------------------------------
        body_widget = QWidget()
        body = QVBoxLayout(body_widget)
        body.setContentsMargins(28, 22, 28, 20)
        body.setSpacing(12)
        layout.addWidget(body_widget, 1)

        title = QLabel("Choose your comics folder")
        title.setObjectName("TitleLabel")
        body.addWidget(title)

        intro = QLabel(
            "Pick the folder where you keep your comics. Every comic inside it — "
            "including new ones you download later — is added to the library "
            "automatically each time the app starts."
        )
        intro.setWordWrap(True)
        intro.setObjectName("SubtitleLabel")
        body.addWidget(intro)

        folder_card = QFrame()
        folder_card.setObjectName("Chip")
        folder_card.setStyleSheet(
            f"QFrame#Chip {{ background-color: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER}; border-radius: 14px; }}"
        )
        folder_layout = QHBoxLayout(folder_card)
        folder_layout.setContentsMargins(10, 10, 10, 10)
        folder_layout.setSpacing(8)
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("e.g. D:\\Comics")
        self.folder_input.setStyleSheet("border: none; background: transparent;")
        folder_layout.addWidget(self.folder_input, 1)
        browse = QPushButton("Browse...")
        browse.setObjectName("GhostButton")
        browse.clicked.connect(self._browse)
        folder_layout.addWidget(browse)
        body.addWidget(folder_card)

        self.sync_check = QCheckBox("Add every comic already in this folder now")
        self.sync_check.setChecked(True)
        body.addWidget(self.sync_check)

        self.auto_check = QCheckBox("Check this folder automatically on every start")
        self.auto_check.setChecked(True)
        body.addWidget(self.auto_check)

        facts = QLabel(
            "Each subfolder becomes its own series, duplicate files are skipped and "
            "volume numbers are taken from the file names. You can change all of "
            "this later from the Library menu."
        )
        facts.setObjectName("SubtitleLabel")
        facts.setWordWrap(True)
        body.addWidget(facts)

        body.addStretch()

        buttons = QDialogButtonBox()
        self.start_button = QPushButton("Start with this folder")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.setDefault(True)
        self.start_button.setMinimumWidth(200)
        self.start_button.clicked.connect(self._accept)
        skip_button = QPushButton("Skip for now")
        skip_button.setObjectName("GhostButton")
        buttons.addButton(self.start_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(skip_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)
        # The welcome window is the first thing a new user sees; it must not be
        # taller than the screen either.
        layout_tools.finish_dialog(
            self, QSize(660, 620), QSize(460, 380), keep_first=1, keep_last=0
        )

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select your comics folder", self.folder_input.text().strip()
        )
        if folder:
            self.folder_input.setText(folder)

    def _accept(self):
        folder = self.folder_input.text().strip()
        if not folder:
            QMessageBox.warning(
                self,
                "Choose a folder",
                "Pick the folder that holds your comics, or press “Skip for now”.",
            )
            return
        if not Path(folder).is_dir():
            QMessageBox.warning(
                self,
                "Folder not found",
                f"This folder does not exist:\n{folder}\n\nChoose another one.",
            )
            return
        self.folder = folder
        self.accept()

    # ------------------------------------------------------------------
    @property
    def import_now(self) -> bool:
        return self.sync_check.isChecked()

    @property
    def auto_sync(self) -> bool:
        return self.auto_check.isChecked()
