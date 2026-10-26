"""
Navigation pane: shelves and series.

The left side of the window follows the Windows navigation pane: a short list of
shelves (All books, Unread, Reading now, Favorites) and then every series with
its counters. Series can be renamed, deleted (with a restore history) and
re-imported from their folder.

The pane holds nothing else: the library folder lives in the Library menu and
the format and read filters live in the command bar above the books, so the
navigation list gets every pixel of height it can use.
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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from database import db
from ui import theme
from ui.widgets import Divider, ElidedLabel, IconButton

# Minimum heights. Every row asks its own labels how tall they are, so the
# Windows text scale (125 %, 150 %...) can never clip a counter in half.
ROW_HEIGHT = 34
NAV_ROW_HEIGHT = 28
ROW_PADDING = 8


def _row_height(row: QWidget, minimum: int) -> int:
    """The height a navigation row really needs for its current font."""
    row.ensurePolished()
    return max(minimum, row.sizeHint().height() + ROW_PADDING)

# value, label, glyph
SHELVES = (
    ("all", "All books", "▦"),
    ("unread", "Unread", "●"),
    ("started", "Reading now", "◔"),
    ("favorites", "Favorites", "★"),
)

def _initial_pixmap(text: str, color: str = "") -> QPixmap:
    """Rounded tile with the first letter of a series.

    Windows navigation panes keep these tiles neutral, so the argument is only
    kept for callers that want to tint a single row (a brand colour, say).
    """
    size = 22
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color or theme.SURFACE_ACTIVE))
    painter.drawRoundedRect(0, 0, size, size, 4, 4)
    painter.setPen(QColor(theme.TEXT_MUTED))
    font = QFont()
    font.setPointSize(8)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text[:1].upper() or "?")
    painter.end()
    return pixmap


class SeriesRow(QWidget):
    """One row of the navigation pane: badge, name and counters."""

    def __init__(self, name: str, total: int, unread: int, color: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(8)

        badge = QLabel()
        badge.setFixedSize(22, 22)
        badge.setPixmap(_initial_pixmap(name))
        layout.addWidget(badge)

        # A long series name is shortened with “…” instead of being cut in
        # the middle of a letter (the full name is in the tooltip).
        title = ElidedLabel(name)
        title.setStyleSheet(f"color: {theme.TEXT}; font-size: 9pt;")
        layout.addWidget(title, 1)

        counter = QLabel(str(total))
        counter.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 9pt;")
        counter.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(counter)

        if unread:
            dot = QLabel("●")
            dot.setToolTip(f"{unread} unread")
            dot.setStyleSheet(f"color: {theme.ACCENT}; font-size: 8pt;")
            layout.addWidget(dot)


class SeriesPanel(QWidget):
    """Navigation pane for shelves and series."""

    series_selected = pyqtSignal(object)  # series_id, "unsorted" or None
    series_changed = pyqtSignal()
    import_folder_requested = pyqtSignal(str)
    restore_requested = pyqtSignal()
    quick_filter_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarPanel")
        self._active_shelf = "all"
        self._setup_ui()
        theme.register_restyle(self)
        self.refresh_series()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 4, 10, 2)
        header_layout.setSpacing(6)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("LIBRARY")
        title.setObjectName("SectionLabel")
        self.subtitle = QLabel("All books")
        self.subtitle.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 10.5pt; font-weight: 600;"
        )
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header_layout.addLayout(title_box, 1)

        self.add_btn = IconButton("+", "Create a new series")
        self._style_add_button()
        # The button is square, and it is measured: a fixed 26 px box cut the
        # "+" in half as soon as Windows scaled the text up.
        self.add_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.add_btn.setMinimumSize(26, 26)
        self.add_btn.setMaximumHeight(26)
        self.add_btn.clicked.connect(self._add_series)
        header_layout.addWidget(self.add_btn)
        layout.addWidget(header)

        # ---- shelves -------------------------------------------------
        self.quick_list = QListWidget()
        self.quick_list.setObjectName("NavList")
        self.quick_list.setFrameShape(QFrame.Shape.NoFrame)
        self.quick_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.quick_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.quick_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.quick_list.itemClicked.connect(self._on_shelf_clicked)
        self.quick_list.setFixedHeight(len(SHELVES) * NAV_ROW_HEIGHT + 4)
        layout.addWidget(self.quick_list)

        # ---- series --------------------------------------------------
        series_header = QWidget()
        series_header_layout = QHBoxLayout(series_header)
        series_header_layout.setContentsMargins(14, 6, 10, 0)
        series_caption = QLabel("SERIES")
        series_caption.setObjectName("SectionLabel")
        series_header_layout.addWidget(series_caption, 1)
        self.series_count_label = QLabel("")
        self.series_count_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 8pt;"
        )
        series_header_layout.addWidget(self.series_count_label)
        layout.addWidget(series_header)

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

        self.trash_button = QPushButton("↺  Restore deleted series")
        self.trash_button.setObjectName("GhostButton")
        self.trash_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.trash_button.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent;"
            f" color: {theme.TEXT_MUTED}; padding: 4px 8px; font-size: 8.5pt;"
            " text-align: left; }"
            f"QPushButton:hover {{ background: {theme.SURFACE_HOVER};"
            f" color: {theme.TEXT}; }}"
        )
        self.trash_button.setVisible(False)
        self.trash_button.clicked.connect(self.restore_requested.emit)
        layout.addWidget(self.trash_button)

        layout.addWidget(Divider())

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def refresh_series(self):
        current = self._current_series_id()
        self.series_list.clear()

        stats = db.get_statistics()
        self._update_shelves(stats)

        unsorted_count = len(db.get_books_without_series())
        if unsorted_count:
            self._add_entry("Unsorted", "unsorted", unsorted_count, theme.GOLD, "◌")

        series_list = db.get_all_series_with_counts()
        self.series_count_label.setText(str(len(series_list)) if series_list else "")
        palette = [theme.ACCENT, theme.VIOLET, theme.BLUE, theme.GREEN,
                   theme.GOLD, "#e06fa8", "#2ba8c4"]
        for index, series in enumerate(series_list):
            unread = series.get("unread_count", 0) or 0
            total = series.get("book_count", 0) or 0
            color = palette[index % len(palette)]
            self._add_series_row(series["id"], series["name"], total, unread, color)

        self._update_trash_button()

        if not self._select_series(current):
            self.series_list.setCurrentRow(-1)

    def _update_shelves(self, stats):
        self.quick_list.clear()
        counts = {
            "all": stats.get("total", 0),
            "unread": stats.get("unread_count", 0),
            "started": stats.get("started_count", 0),
            "favorites": stats.get("favorites", 0),
        }
        active = self._active_shelf or "all"
        total_height = 4
        for row, (value, label, glyph) in enumerate(SHELVES):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, value)
            widget = self._shelf_row(label, counts[value], glyph)
            height = _row_height(widget, NAV_ROW_HEIGHT)
            item.setSizeHint(QSize(10, height))
            total_height += height
            self.quick_list.addItem(item)
            self.quick_list.setItemWidget(item, widget)
            if value == active:
                self.quick_list.setCurrentRow(row)
        # The list never scrolls: its height is the sum of its own rows.
        self.quick_list.setFixedHeight(total_height)

    def _shelf_row(self, label: str, count: int, glyph: str) -> QWidget:
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)

        icon = QLabel(glyph)
        icon.setFixedWidth(16)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")
        layout.addWidget(icon)

        text = QLabel(label)
        text.setStyleSheet(f"color: {theme.TEXT}; font-size: 9pt;")
        layout.addWidget(text, 1)

        # A zero is a number too: leaving it out made "Reading now" look like
        # a row whose counter had been cut off.
        counter = QLabel(str(count))
        counter.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 9pt;")
        counter.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(counter)
        return row

    def _add_entry(self, name: str, value, count: int, color: str, glyph: str):
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)

        icon = QLabel(glyph)
        icon.setFixedWidth(16)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"color: {color}; font-size: 9pt;")
        layout.addWidget(icon)

        label = ElidedLabel(name)
        label.setStyleSheet(f"color: {theme.TEXT}; font-size: 9pt;")
        layout.addWidget(label, 1)

        counter = QLabel(str(count))
        counter.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 9pt;")
        counter.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(counter)

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, value)
        item.setData(Qt.ItemDataRole.UserRole + 1, name)
        item.setSizeHint(QSize(10, _row_height(row, NAV_ROW_HEIGHT)))
        item.setToolTip(name)
        self.series_list.addItem(item)
        self.series_list.setItemWidget(item, row)

    def _add_series_row(self, series_id: int, name: str, total: int, unread: int,
                        color: str):
        row = SeriesRow(name, total, unread, color)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, series_id)
        item.setData(Qt.ItemDataRole.UserRole + 1, name)
        item.setSizeHint(QSize(10, _row_height(row, ROW_HEIGHT)))
        item.setToolTip(f"{name} — {total} books, {unread} unread")
        self.series_list.addItem(item)
        self.series_list.setItemWidget(item, row)

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

    def _on_shelf_clicked(self, item: QListWidgetItem):
        kind = item.data(Qt.ItemDataRole.UserRole)
        self.series_list.clearSelection()
        self.series_list.setCurrentRow(-1)
        for row in range(self.quick_list.count()):
            self.quick_list.item(row).setSelected(
                self.quick_list.item(row) is item
            )
        self._active_shelf = kind
        self.subtitle.setText(dict((value, label) for value, label, _ in SHELVES)[kind])
        self.quick_filter_selected.emit(kind)

    def _style_add_button(self) -> None:
        self.add_btn.setStyleSheet(
            f"QToolButton {{ color: {theme.ACCENT}; background: {theme.ACCENT_SOFT};"
            " border: 1px solid transparent; border-radius: 4px; padding: 0px;"
            " font-size: 11pt; font-weight: 600; }"
            f"QToolButton:hover {{ background: {theme.ACCENT_TINT};"
            f" border-color: {theme.ACCENT}; }}"
        )

    def restyle(self) -> None:
        """Re-apply the inline colours, then rebuild the rows with new ones."""
        self.subtitle.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 10.5pt; font-weight: 600;"
        )
        self._style_add_button()
        self.series_count_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 8pt;"
        )
        self.trash_button.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent;"
            f" color: {theme.TEXT_MUTED}; padding: 4px 8px; font-size: 8.5pt;"
            " text-align: left; }"
            f"QPushButton:hover {{ background: {theme.SURFACE_HOVER};"
            f" color: {theme.TEXT}; }}"
        )
        self.series_count_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 8pt;"
        )
        self.refresh_series()

    def activate_shelf(self, kind: str):
        """Select a shelf from outside the pane (stat cards, menu)."""
        for row in range(self.quick_list.count()):
            item = self.quick_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == kind:
                self.quick_list.setCurrentRow(row)
                self._on_shelf_clicked(item)
                return

    def set_active_shelf(self, kind: str):
        """Mark a shelf as current without emitting a filter change."""
        self._active_shelf = kind or "all"
        for row in range(self.quick_list.count()):
            item = self.quick_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == kind:
                self.quick_list.setCurrentRow(row)
                return
        self.quick_list.setCurrentRow(-1)

    def clear_shelves(self):
        """Drop the shelf highlight when a series is picked instead."""
        self.quick_list.clearSelection()
        self.quick_list.setCurrentRow(-1)

    def _on_series_clicked(self, item: QListWidgetItem):
        series_id = item.data(Qt.ItemDataRole.UserRole)
        if series_id == "__separator__" or not (
            item.flags() & Qt.ItemFlag.ItemIsSelectable
        ):
            return
        label = item.data(Qt.ItemDataRole.UserRole + 1) or ""
        self.clear_shelves()
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

    def _restore_series(self, trash_id: int):
        series_id = db.restore_deleted_series(trash_id)
        self.refresh_series()
        self.series_changed.emit()
        if series_id:
            self._select_series(series_id)
            self.series_selected.emit(series_id)
