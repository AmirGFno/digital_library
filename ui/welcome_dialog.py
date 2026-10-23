"""
First-run welcome dialog.

The library owner asked for a *default folder*: choose it once, and everything
that appears in it later is added automatically on every start.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox,
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
        self.setMinimumWidth(620)
        self.folder: Optional[str] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        title = QLabel("Choose your comics folder")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        body = QLabel(
            "Pick the folder where you keep your comics. Every comic inside it — "
            "including new ones you download later — is added to the library "
            "automatically each time the app starts.\n\n"
            "Each subfolder becomes its own series, duplicate files are skipped and "
            "volume numbers are taken from the file names."
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        row = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("e.g. D:\\Comics")
        row.addWidget(self.folder_input, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)

        self.sync_check = QCheckBox("Add every comic already in this folder now")
        self.sync_check.setChecked(True)
        layout.addWidget(self.sync_check)

        self.auto_check = QCheckBox("Check this folder automatically on every start")
        self.auto_check.setChecked(True)
        layout.addWidget(self.auto_check)

        skip_hint = QLabel(
            "You can change or disable this later from the Library menu."
        )
        skip_hint.setObjectName("SubtitleLabel")
        skip_hint.setWordWrap(True)
        layout.addWidget(skip_hint)

        layout.addStretch()

        buttons = QDialogButtonBox()
        self.start_button = QPushButton("Start with this folder")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self._accept)
        skip_button = QPushButton("Skip for now")
        buttons.addButton(self.start_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(skip_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
