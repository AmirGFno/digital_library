"""
Sidebar with library sections and series.

Pseudo entries "All books" and "Unsorted" are always present; every series is
listed with its unread/total counter and can be renamed or deleted from the
context menu.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from database import db


class SeriesPanel(QWidget):
    """Panel for displaying and managing series."""

    series_selected = pyqtSignal(object)  # series_id, "unsorted" or None
    series_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.refresh_series()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(6)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("LIBRARY")
        title.setObjectName("SectionLabel")
        self.subtitle = QLabel("All books")
        self.subtitle.setObjectName("SubtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(30, 30)
        self.add_btn.setObjectName("PrimaryButton")
        self.add_btn.setToolTip("Add a new series")
        self.add_btn.clicked.connect(self._add_series)
        header.addWidget(self.add_btn)

        layout.addLayout(header)

        self.series_list = QListWidget()
        self.series_list.setObjectName("SeriesList")
        self.series_list.setFrameShape(QFrame.Shape.NoFrame)
        self.series_list.setSpacing(1)
        self.series_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.series_list.itemClicked.connect(self._on_series_clicked)
        self.series_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.series_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.series_list, 1)

        footer = QLabel("Right-click a series to rename or delete it.")
        footer.setObjectName("SubtitleLabel")
        footer.setWordWrap(True)
        layout.addWidget(footer)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def refresh_series(self):
        current = self._current_series_id()
        self.series_list.clear()

        total_books = db.get_total_book_count()
        all_item = QListWidgetItem(f"All books   ({total_books})")
        all_item.setData(Qt.ItemDataRole.UserRole, None)
        self.series_list.addItem(all_item)

        unsorted_count = len(db.get_books_without_series())
        if unsorted_count:
            unsorted_item = QListWidgetItem(f"Unsorted   ({unsorted_count})")
            unsorted_item.setData(Qt.ItemDataRole.UserRole, "unsorted")
            self.series_list.addItem(unsorted_item)

        series_list = db.get_all_series_with_counts()
        if series_list:
            separator = QListWidgetItem("SERIES")
            separator.setFlags(Qt.ItemFlag.NoItemFlags)
            separator.setForeground(QColor("#6b7280"))
            separator.setData(Qt.ItemDataRole.UserRole, "__separator__")
            self.series_list.addItem(separator)

        for series in series_list:
            unread = series.get("unread_count", 0) or 0
            total = series.get("book_count", 0) or 0
            label = series["name"]
            if total:
                label = f"{series['name']}   ({unread}/{total})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, series["id"])
            item.setToolTip(f"{series['name']} — {total} books, {unread} unread")
            self.series_list.addItem(item)

        # Restore the previous selection when possible.
        if not self._select_series(current):
            self.series_list.setCurrentRow(0)

    def _current_series_id(self):
        item = self.series_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _select_series(self, series_id) -> bool:
        for row in range(self.series_list.count()):
            item = self.series_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == series_id:
                self.series_list.setCurrentRow(row)
                return True
        return False

    def _on_series_clicked(self, item: QListWidgetItem):
        series_id = item.data(Qt.ItemDataRole.UserRole)
        if series_id == "__separator__" or not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            return
        self.subtitle.setText(item.text().split("   ")[0])
        self.series_selected.emit(series_id)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _add_series(self):
        from ui.dialogs import AddSeriesDialog

        dialog = AddSeriesDialog(self)
        if dialog.exec():
            self.refresh_series()
            self.series_changed.emit()

    def _show_context_menu(self, pos):
        item = self.series_list.itemAt(pos)
        if not item:
            return
        series_id = item.data(Qt.ItemDataRole.UserRole)
        if series_id is None or isinstance(series_id, str):
            return

        menu = QMenu(self)
        edit_action = QAction("Rename...", self)
        edit_action.triggered.connect(lambda: self._edit_series(series_id))
        menu.addAction(edit_action)
        delete_action = QAction("Delete series...", self)
        delete_action.triggered.connect(lambda: self._delete_series(series_id))
        menu.addAction(delete_action)
        menu.exec(self.series_list.mapToGlobal(pos))

    def _edit_series(self, series_id: int):
        from ui.dialogs import EditSeriesDialog

        series = db.get_series(series_id)
        if not series:
            return
        dialog = EditSeriesDialog(series_id, series["name"], self)
        if dialog.exec():
            self.refresh_series()
            self.series_changed.emit()

    def _delete_series(self, series_id: int):
        from ui.dialogs import ConfirmDialog

        series = db.get_series(series_id)
        if not series:
            return
        dialog = ConfirmDialog(
            "Delete series",
            f"Delete '{series['name']}'?\nThe books in it will become unsorted.",
            parent=self,
        )
        if dialog.exec():
            db.delete_series(series_id)
            self.refresh_series()
            self.series_changed.emit()
