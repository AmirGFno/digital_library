"""
Preview of the names that will be stored for imported files.

Cleaning a file name (removing ``@channel``, site addresses and advertising
words) must never happen silently: before anything is written to the database
the user sees the old and the new title and can turn the cleaning off.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ui import layout as layout_tools
from utils.text_cleaner import clean_file_stem

PREVIEW_LIMIT = 300


class NamePreviewDialog(QDialog):
    """Show how the imported titles will look, and let the user opt out."""

    def __init__(self, files: Iterable[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Names before import")
        self._preferred_size = QSize(820, 540)
        self.files: List[str] = [str(path) for path in files]
        self._build_ui()
        layout_tools.finish_dialog(self, self._preferred_size, QSize(560, 420))
        self.refresh_preview()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("These titles will be saved in the library")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Advertising text such as channel IDs and site addresses is removed "
            "from the file names. Nothing has been saved yet."
        )
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.clean_check = QCheckBox("Remove advertising text from names")
        self.clean_check.setChecked(True)
        self.clean_check.toggled.connect(self.refresh_preview)
        layout.addWidget(self.clean_check)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["File", "Title after import", "Changed"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(32)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("SubtitleLabel")
        self.summary_label.setStyleSheet("color: #ffd79a; font-size: 12px;")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        buttons = QDialogButtonBox()
        self.import_button = QPushButton("Import")
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.setDefault(True)
        self.import_button.setMinimumWidth(140)
        self.import_button.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("GhostButton")
        buttons.addButton(self.import_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    @property
    def use_clean_names(self) -> bool:
        return self.clean_check.isChecked()

    def _title_for(self, filepath: str) -> str:
        if self.clean_check.isChecked():
            return clean_file_stem(filepath)
        return Path(filepath).stem

    def changed_count(self) -> int:
        return sum(
            1 for filepath in self.files if self._title_for(filepath) != Path(filepath).stem
        )

    def refresh_preview(self):
        self.table.setRowCount(0)
        for filepath in self.files[:PREVIEW_LIMIT]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            original = Path(filepath).stem
            new_title = self._title_for(filepath)

            self.table.setItem(row, 0, QTableWidgetItem(Path(filepath).name))
            self.table.setItem(row, 1, QTableWidgetItem(new_title))

            changed = QTableWidgetItem("yes" if new_title != original else "")
            changed.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, changed)

        changed = self.changed_count()
        dropped = len(self.files) - PREVIEW_LIMIT
        text = (
            f"{len(self.files)} file(s); {changed} name(s) will change."
            if self.clean_check.isChecked()
            else f"{len(self.files)} file(s); names are imported unchanged."
        )
        if dropped > 0:
            text += f" Showing the first {PREVIEW_LIMIT}."
        self.summary_label.setText(text)


def preview_when_needed(files: Iterable[str], parent=None):
    """Return a NamePreviewDialog when cleaning changes something, else None."""
    files = [str(path) for path in files]
    dialog = NamePreviewDialog(files, parent)
    if dialog.changed_count() == 0:
        dialog.deleteLater()
        return None
    return dialog
