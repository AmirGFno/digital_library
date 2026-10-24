"""
Sidebar with library sections and series.

Pseudo entries "All books" and "Unsorted" are always present; every series is
listed as a custom row with a coloured initial, its book counter and an unread
badge. Series can be renamed, deleted (with a restore history) and re-imported
from their folder.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QPainter, QPixmap
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
from ui import theme
from ui.widgets import Divider, IconButton

ROW_HEIGHT = 50


def _initial_pixmap(text: str, color: str) -> QPixmap:
    """Rounded square with the first letter of a series."""
    size = 30
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(0, 0, size, size, 9, 9)
    painter.setPen(QColor("#ffffff"))
    font = QFont()
    font.setPointSize(11)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text[:1].upper() or "?")
    painter.end()
    return pixmap


class SeriesRow(QWidget):
    """One row of the sidebar: badge, name and counters."""

    def __init__(self, name: str, total: int, unread: int, color: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 10, 4)
        layout.setSpacing(9)

        badge = QLabel()
        badge.setFixedSize(30, 30)
        badge.setPixmap(_initial_pixmap(name, color))
        layout.addWidget(badge)

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        text_box.setContentsMargins(0, 0, 0, 0)
        title = QLabel(name)
        title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 12px; font-weight: 600;"
        )
        subtitle = QLabel(f"{total} books")
        subtitle.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        for label in (title, subtitle):
            label.setFixedHeight(15)
        text_box.addWidget(title)
        text_box.addWidget(subtitle)
        layout.addLayout(text_box, 1)

        if unread:
            counter = QLabel(str(unread))
            counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
            counter.setStyleSheet(
                f"color: {theme.ACCENT_GLOW}; background: {theme.ACCENT_SOFT};"
                " border-radius: 8px; padding: 1px 6px; font-size: 10px;"
                " font-weight: 700;"
            )
            layout.addWidget(counter)


class SeriesPanel(QWidget):
    """Panel for displaying and managing series."""

    series_selected = pyqtSignal(object)  # series_id, "unsorted" or None
    series_changed = pyqtSignal()
    import_folder_requested = pyqtSignal(str)
    library_folder_requested = pyqtSignal()
    restore_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarPanel")
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
        title_box.setSpacing(1)
        title = QLabel("LIBRARY")
        title.setObjectName("SectionLabel")
        self.subtitle = QLabel("All books")
        self.subtitle.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 15px; font-weight: 700;"
        )
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.add_btn = IconButton("＋", "Create a new series")
        self.add_btn.setStyleSheet(
            f"QToolButton {{ color: #ffffff; background: {theme.ACCENT};"
            " border-radius: 10px; font-size: 16px; font-weight: 700; }"
            f"QToolButton:hover {{ background: {theme.ACCENT_HOVER}; }}"
        )
        self.add_btn.clicked.connect(self._add_series)
        header.addWidget(self.add_btn)
        layout.addLayout(header)

        self.series_list = QListWidget()
        self.series_list.setObjectName("SeriesList")
        self.series_list.setFrameShape(QFrame.Shape.NoFrame)
        self.series_list.setSpacing(0)
        self.series_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.series_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.series_list.itemClicked.connect(self._on_series_clicked)
        self.series_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.series_list, 1)

        self.trash_button = QPushButton("↺  Deleted series")
        self.trash_button.setObjectName("GhostButton")
        self.trash_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.trash_button.setStyleSheet(
            "QPushButton { background: transparent;"
            f" border: 1px dashed {theme.BORDER}; border-radius: 10px;"
            f" color: {theme.TEXT_MUTED}; padding: 7px 10px; font-size: 11px;"
            " text-align: left; }"
            f"QPushButton:hover {{ color: {theme.GOLD};"
            f" border-color: {theme.GOLD}; }}"
        )
        self.trash_button.setVisible(False)
        self.trash_button.clicked.connect(self.restore_requested.emit)
        layout.addWidget(self.trash_button)

        layout.addWidget(Divider())

        footer = QFrame()
        footer.setObjectName("Chip")
        footer.setStyleSheet(
            f"QFrame#Chip {{ background: {theme.SURFACE}; border: 1px solid"
            f" {theme.BORDER_SOFT}; border-radius: 12px; }}"
        )
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(11, 9, 11, 9)
        footer_layout.setSpacing(2)

        self.folder_caption = QLabel("LIBRARY FOLDER")
        self.folder_caption.setObjectName("SectionLabel")
        self.folder_path = QLabel("Not set")
        self.folder_path.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        self.folder_path.setWordWrap(False)
        footer_layout.addWidget(self.folder_caption)
        footer_layout.addWidget(self.folder_path)

        self.folder_button = QPushButton("Choose folder")
        self.folder_button.setObjectName("GhostButton")
        self.folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_button.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; padding: 4px 0;"
            f" color: {theme.ACCENT_GLOW}; font-size: 11px; text-align: left; }}"
            f"QPushButton:hover {{ color: {theme.ACCENT_HOVER}; }}"
        )
        self.folder_button.clicked.connect(self.library_folder_requested.emit)
        footer_layout.addWidget(self.folder_button)
        layout.addWidget(footer)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def refresh_series(self):
        current = self._current_series_id()
        self.series_list.clear()

        total_books = db.get_total_book_count()
        self._add_entry("All books", None, total_books, theme.TEXT, "▦", total_books)
        unsorted_count = len(db.get_books_without_series())
        if unsorted_count:
            self._add_entry("Unsorted", "unsorted", unsorted_count, theme.GOLD, "◌",
                            unsorted_count)

        series_list = db.get_all_series_with_counts()
        if series_list:
            separator = QListWidgetItem("SERIES")
            separator.setFlags(Qt.ItemFlag.NoItemFlags)
            separator.setForeground(QColor(theme.TEXT_DIM))
            separator.setData(Qt.ItemDataRole.UserRole, "__separator__")
            separator.setSizeHint(QSize(10, 26))
            self.series_list.addItem(separator)

        palette = [theme.ACCENT, theme.VIOLET, theme.BLUE, theme.GREEN,
                   theme.GOLD, "#f472b6", "#22d3ee"]
        for index, series in enumerate(series_list):
            unread = series.get("unread_count", 0) or 0
            total = series.get("book_count", 0) or 0
            color = palette[index % len(palette)]
            self._add_series_row(series["id"], series["name"], total, unread, color)

        self._update_folder_label()
        self._update_trash_button()

        if not self._select_series(current):
            self.series_list.setCurrentRow(0)

    def _add_entry(self, name: str, value, count: int, color: str, glyph: str,
                   total: int):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, value)
        item.setSizeHint(QSize(10, 40))
        self.series_list.addItem(item)

        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(9)

        icon = QLabel(glyph)
        icon.setFixedSize(22, 22)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"color: {color}; font-size: 13px;")
        layout.addWidget(icon)

        label = QLabel(name)
        label.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; font-weight: 600;")
        layout.addWidget(label, 1)

        counter = QLabel(str(count))
        counter.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        layout.addWidget(counter)

        self.series_list.setItemWidget(item, row)

    def _add_series_row(self, series_id: int, name: str, total: int, unread: int,
                        color: str):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, series_id)
        item.setSizeHint(QSize(10, ROW_HEIGHT))
        item.setToolTip(f"{name} — {total} books, {unread} unread")
        self.series_list.addItem(item)
        self.series_list.setItemWidget(item, SeriesRow(name, total, unread, color))

    def _update_trash_button(self):
        """Only show the restore shortcut when there is something to restore."""
        if not hasattr(self, "trash_button"):
            return
        try:
            deleted = db.get_deleted_series()
        except Exception:
            deleted = []
        self.trash_button.setVisible(bool(deleted))
        if deleted:
            self.trash_button.setText(f"↺  Restore deleted series ({len(deleted)})")

    def _update_folder_label(self):
        from utils.settings import settings

        folder = settings.get_library_root()
        if folder:
            self.folder_path.setText(self._shorten(folder, 30))
            self.folder_path.setToolTip(folder)
            self.folder_button.setText("Sync now")
        else:
            self.folder_path.setText("Not set")
            self.folder_button.setText("Choose folder")

    @staticmethod
    def _shorten(path: str, limit: int) -> str:
        if len(path) <= limit:
            return path
        return "…" + path[-(limit - 1):]

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
        if series_id == "__separator__" or not (
            item.flags() & Qt.ItemFlag.ItemIsSelectable
        ):
            return
        label = item.text() if item.text() else ""
        self.subtitle.setText(label or "All books")
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

        series = db.get_series(series_id)
        if not series:
            return

        menu = QMenu(self)
        edit_action = QAction("Rename…", self)
        edit_action.triggered.connect(lambda: self._edit_series(series_id))
        menu.addAction(edit_action)

        folder = series.get("folder")
        if folder and Path(folder).is_dir():
            import_action = QAction("Import this folder again", self)
            import_action.triggered.connect(
                lambda: self.import_folder_requested.emit(str(folder))
            )
            menu.addAction(import_action)

        restore_menu = menu.addMenu("Deleted series")
        deleted = db.get_deleted_series()
        if deleted:
            for record in deleted[:10]:
                action = QAction(
                    f"Restore “{record['name']}” ({record['book_count']} books)", self
                )
                action.triggered.connect(
                    lambda _checked=False, trash_id=record["id"]: self._restore_series(
                        trash_id
                    )
                )
                restore_menu.addAction(action)
        else:
            empty = restore_menu.addAction("Nothing to restore")
            empty.setEnabled(False)

        menu.addSeparator()
        delete_action = QAction("Delete series…", self)
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
            f"Delete “{series['name']}”?\n\n"
            "The books stay in the library (as unsorted) and the series can be "
            "restored later from the right-click menu.",
            parent=self,
            danger=True,
        )
        dialog.confirm_button.setText("Delete series")
        if dialog.exec():
            db.delete_series(series_id)
            self.refresh_series()
            self.series_changed.emit()
            self.series_restored = None

    def _restore_series(self, trash_id: int):
        series_id = db.restore_deleted_series(trash_id)
        self.refresh_series()
        self.series_changed.emit()
        if series_id:
            self._select_series(series_id)
            self.series_selected.emit(series_id)
