"""
Ask what to do with folders that appeared inside the comics folder.

The user asked for this behaviour explicitly: when a new folder shows up in the
library root, the application must ask whether it should become a series instead
of silently guessing. Each row can be imported as its own series, imported
without a series, or ignored — and the answer is remembered so the question is
asked only once per folder.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


ACTIONS = [
    ("سری بساز / Create a series", "series"),
    ("بدون سری / Import without a series", "files"),
    ("نادیده بگیر / Ignore", "ignore"),
]


class NewFolderDialog(QDialog):
    """List of new folders with a per-folder decision."""

    def __init__(self, folders: Sequence[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("New folders found")
        self.setMinimumSize(760, 460)
        self.folders: List[str] = [str(folder) for folder in folders]
        self._build_ui()
        self._fill_table()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("New folders in your comics folder")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        question = QLabel(
            "این پوشه‌ها تازه اضافه شده‌اند. هر کدام به‌عنوان سری اضافه شود؟"
            "   —   Should each folder become a series?"
        )
        question.setObjectName("QuestionLabel")
        question.setWordWrap(True)
        layout.addWidget(question)

        subtitle = QLabel(
            "A series keeps the folder's name, gets its own volume numbers and is "
            "watched for new issues. Choosing “Import without a series” only adds "
            "the files."
        )
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Folder", "Series name", "Action"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.remember_check = QCheckBox(
            "Do not ask about these folders again (you can still import them later)"
        )
        self.remember_check.setChecked(True)
        layout.addWidget(self.remember_check)

        layout.addWidget(QLabel(""))

        buttons = QDialogButtonBox()
        self.apply_button = QPushButton("Apply")
        self.apply_button.setObjectName("PrimaryButton")
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self.accept)
        skip = QPushButton("Ask me later")
        skip.setObjectName("GhostButton")
        buttons.addButton(self.apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(skip, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _fill_table(self):
        self.table.setRowCount(0)
        self._combos: Dict[str, QComboBox] = {}
        self._names: Dict[str, QLineEdit] = {}

        for folder in self.folders:
            row = self.table.rowCount()
            self.table.insertRow(row)

            folder_item = QTableWidgetItem(Path(folder).name)
            folder_item.setFlags(folder_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            folder_item.setToolTip(folder)
            self.table.setItem(row, 0, folder_item)

            name_edit = QLineEdit(Path(folder).name)
            name_edit.setPlaceholderText("Series name")
            self.table.setCellWidget(row, 1, name_edit)
            self._names[folder] = name_edit

            combo = QComboBox()
            for label, value in ACTIONS:
                combo.addItem(label, value)
            self.table.setCellWidget(row, 2, combo)
            self._combos[folder] = combo

        self.table.resizeRowsToContents()

    # ------------------------------------------------------------------
    def decisions(self) -> Dict[str, Dict[str, str]]:
        """folder -> {"action": series|files|ignore, "name": str}"""
        result: Dict[str, Dict[str, str]] = {}
        for folder in self.folders:
            combo = self._combos.get(folder)
            name_edit = self._names.get(folder)
            action = combo.currentData() if combo else "series"
            name = (name_edit.text().strip() if name_edit else "") or Path(folder).name
            result[folder] = {"action": action, "name": name}
        return result

    @property
    def remember(self) -> bool:
        return self.remember_check.isChecked()


def ask_about_new_folders(folders: Sequence[str], parent=None):
    """Show the dialog and return (decisions, remember) or (None, False)."""
    dialog = NewFolderDialog(folders, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None, False
    return dialog.decisions(), dialog.remember
