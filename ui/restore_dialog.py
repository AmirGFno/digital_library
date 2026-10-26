"""
Bring back a deleted series.

Deleting a series never destroys the books: they become unsorted and the series
is remembered with the list of its books and its folder. This dialog lists those
records and restores one of them exactly as it was.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ui import layout as layout_tools
from database import db


class RestoreSeriesDialog(QDialog):
    """List of deleted series with a restore button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restore a deleted series")
        self._preferred_size = QSize(640, 500)
        self.restored_id = None
        self._build_ui()
        layout_tools.finish_dialog(self, self._preferred_size, QSize(480, 380))
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("Deleted series")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Restoring a series puts its books back and reconnects the folder it "
            "was imported from. Book files are never touched."
        )
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._restore())
        layout.addWidget(self.list_widget, 1)

        self.empty_label = QLabel("Nothing to restore.")
        self.empty_label.setObjectName("SubtitleLabel")
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)

        row = QHBoxLayout()
        self.forget_button = QPushButton("Forget")
        self.forget_button.setObjectName("GhostButton")
        self.forget_button.clicked.connect(self._forget)
        row.addWidget(self.forget_button)
        row.addStretch()

        buttons = QDialogButtonBox()
        self.restore_button = QPushButton("Restore series")
        self.restore_button.setObjectName("PrimaryButton")
        self.restore_button.setDefault(True)
        self.restore_button.clicked.connect(self._restore)
        close = QPushButton("Close")
        close.setObjectName("GhostButton")
        buttons.addButton(self.restore_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(close, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

    def _load(self):
        self.list_widget.clear()
        records = db.get_deleted_series()
        for record in records:
            folder = record.get("folder") or "no folder"
            item = QListWidgetItem(
                f"{record['name']}   ·   {record['book_count']} books   ·   "
                f"{Path(folder).name if folder != 'no folder' else folder}   ·   "
                f"{record.get('deleted_at') or ''}"
            )
            item.setData(Qt.ItemDataRole.UserRole, record["id"])
            item.setToolTip(folder)
            self.list_widget.addItem(item)

        empty = not records
        self.empty_label.setVisible(empty)
        self.restore_button.setEnabled(not empty)
        self.forget_button.setEnabled(not empty)
        if records:
            self.list_widget.setCurrentRow(0)

    def _current_id(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _restore(self):
        trash_id = self._current_id()
        if trash_id is None:
            return
        self.restored_id = db.restore_deleted_series(trash_id)
        self.accept()

    def _forget(self):
        trash_id = self._current_id()
        if trash_id is None:
            return
        db.forget_deleted_series(trash_id)
        self._load()
