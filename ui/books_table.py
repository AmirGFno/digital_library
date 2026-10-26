"""
The "Details" view: the library as a sortable Windows-style list.

The grid is pleasant for browsing covers, but a real desktop library also needs
the Explorer-like list: one row per book, sortable by every column, multi-select
with Ctrl/Shift, double-click to open and the same right-click menu as a card.
The list does not load any cover, so a library with thousands of books opens
instantly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPoint,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableView,
)

from ui import theme
from utils.helpers import format_file_size

BOOK_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 1
SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 2

# name, natural width, stretch weight. The list shares the window instead of
# scrolling sideways: the two text columns take the extra space, and every
# other column keeps at least its own header width so a value is never
# squeezed into "Deep Fie…".
COLUMNS = (
    ("Title", 300, 3),
    ("Series", 190, 2),
    ("Volume", 78, 0),
    ("Year", 62, 0),
    ("Format", 74, 0),
    ("Size", 88, 0),
    ("Pages", 66, 0),
    ("Status", 84, 0),
    ("★", 34, 0),
)
NUMERIC_COLUMNS = {5, 6}


def _text(value) -> str:
    return "" if value is None else str(value)


class BooksModel(QAbstractTableModel):
    """One row per book; cheap to rebuild and never loads a cover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._books: List[Dict] = []

    # ------------------------------------------------------------------
    def set_books(self, books: List[Dict]) -> None:
        self.beginResetModel()
        self._books = list(books or [])
        self.endResetModel()

    def books(self) -> List[Dict]:
        return self._books

    def book_at(self, row: int) -> Optional[Dict]:
        if 0 <= row < len(self._books):
            return self._books[row]
        return None

    # ------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._books)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section][0]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        book = self._books[index.row()]
        column = index.column()

        if role == BOOK_ID_ROLE:
            return book.get("id")
        if role == SORT_ROLE:
            return self._sort_value(book, column)
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(book, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return _text(book.get("filepath"))
        if role == Qt.ItemDataRole.TextAlignmentRole and column in NUMERIC_COLUMNS:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            if column == 4:
                return QColor(self._format_color(book))
            if column == 7:
                if book.get("is_read"):
                    return QColor(theme.GREEN)
                if book.get("last_opened_at"):
                    return QColor(theme.ACCENT_GLOW)
            if column == 8 and book.get("favorite"):
                return QColor(theme.GOLD)
        return None

    # ------------------------------------------------------------------
    @staticmethod
    def _suffix(book: Dict) -> str:
        return Path(str(book.get("filepath", ""))).suffix.upper().lstrip(".")

    def _display(self, book: Dict, column: int) -> str:
        if column == 0:
            return _text(book.get("title") or Path(str(book.get("filepath", ""))).stem)
        if column == 1:
            return _text(book.get("series_name") or "—")
        if column == 2:
            return _text(book.get("volume"))
        if column == 3:
            return _text(book.get("year"))
        if column == 4:
            return self._suffix(book)
        if column == 5:
            return format_file_size(int(book.get("file_size") or 0))
        if column == 6:
            pages = book.get("page_count") or 0
            return str(pages) if pages else "—"
        if column == 7:
            if book.get("is_read"):
                return "Read"
            if book.get("last_opened_at"):
                return "Reading"
            return "Unread"
        if column == 8:
            return "★" if book.get("favorite") else ""
        return ""

    def _sort_value(self, book: Dict, column: int):
        if column == 0:
            return self._display(book, 0).lower()
        if column == 1:
            return (_text(book.get("series_name")) or "~").lower()
        if column == 2:
            return self._volume_number(book.get("volume"))
        if column == 3:
            try:
                return int(book.get("year") or 0)
            except (TypeError, ValueError):
                return 0
        if column == 4:
            return self._suffix(book)
        if column == 5:
            try:
                return int(book.get("file_size") or 0)
            except (TypeError, ValueError):
                return 0
        if column == 6:
            try:
                return int(book.get("page_count") or 0)
            except (TypeError, ValueError):
                return 0
        if column == 7:
            if book.get("is_read"):
                return 2
            if book.get("last_opened_at"):
                return 1
            return 0
        if column == 8:
            return 1 if book.get("favorite") else 0
        return ""

    @staticmethod
    def _volume_number(value) -> float:
        import re

        match = re.search(r"\d+(?:\.\d+)?", _text(value))
        return float(match.group(0)) if match else 0.0

    @staticmethod
    def _format_color(book: Dict) -> str:
        return {
            "CBZ": theme.BLUE,
            "CBR": theme.ACCENT,
            "CB7": theme.VIOLET,
            "CBT": theme.GOLD,
            "PDF": "#e05252",
        }.get(BooksModel._suffix(book), theme.TEXT_MUTED)


class BooksTable(QTableView):
    """Sortable, multi-select list of books."""

    open_requested = pyqtSignal(int)
    selection_changed = pyqtSignal(list)      # book ids
    book_menu_requested = pyqtSignal(int, QPoint)  # book id, global position

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BooksTable")
        self._model = BooksModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(SORT_ROLE)
        self._proxy.setDynamicSortFilter(False)
        self.setModel(self._proxy)

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setAlternatingRowColors(False)
        self.setCornerButtonEnabled(False)
        self.setSortingEnabled(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.setMinimumSectionSize(34)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        for index, (_name, width, weight) in enumerate(COLUMNS):
            if weight:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(index, width)
        header.sectionClicked.connect(self._on_header_clicked)

        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(26)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)

        self.doubleClicked.connect(self._on_double_clicked)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._sort_column: Optional[int] = None
        self._sort_ascending = True

    # ------------------------------------------------------------------
    def set_books(self, books: List[Dict]) -> None:
        selected = set(self.selected_ids())
        self._model.set_books(books)
        if selected:
            self.select_ids(selected)

    def set_books_keep_selection(self, books: List[Dict]) -> None:
        self.set_books(books)

    def books(self) -> List[Dict]:
        return self._model.books()

    def book_count(self) -> int:
        return len(self._model.books())

    def book_id(self, row: int) -> Optional[int]:
        index = self._proxy.index(row, 0)
        if not index.isValid():
            return None
        source = self._proxy.mapToSource(index)
        return self._model.data(source, BOOK_ID_ROLE)

    def selected_ids(self) -> List[int]:
        ids = []
        for index in self.selectionModel().selectedRows():
            source = self._proxy.mapToSource(index)
            value = self._model.data(source, BOOK_ID_ROLE)
            if value is not None:
                ids.append(int(value))
        return ids

    def select_ids(self, ids) -> None:
        wanted = {int(value) for value in ids}
        selection = self.selectionModel()
        selection.blockSignals(True)
        selection.clearSelection()
        first = None
        for row in range(self._proxy.rowCount()):
            index = self._proxy.index(row, 0)
            source = self._proxy.mapToSource(index)
            if int(self._model.data(source, BOOK_ID_ROLE) or -1) in wanted:
                selection.select(
                    index,
                    self.selectionModel().SelectionFlag.Select
                    | self.selectionModel().SelectionFlag.Rows,
                )
                if first is None:
                    first = index
        if first is not None:
            self.scrollTo(first)
        selection.blockSignals(False)

    def select_all_books(self) -> None:
        self.selectAll()

    # ------------------------------------------------------------------
    def _on_selection_changed(self, *_args) -> None:
        self.selection_changed.emit(self.selected_ids())

    def _on_double_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        source = self._proxy.mapToSource(index)
        book_id = self._model.data(source, BOOK_ID_ROLE)
        if book_id is not None:
            self.open_requested.emit(int(book_id))

    def _on_context_menu(self, position: QPoint) -> None:
        index = self.indexAt(position)
        if not index.isValid():
            return
        if not self.selectionModel().isRowSelected(index.row(), index.parent()):
            self.selectRow(index.row())
        source = self._proxy.mapToSource(index)
        book_id = self._model.data(source, BOOK_ID_ROLE)
        if book_id is not None:
            self.book_menu_requested.emit(int(book_id), self.viewport().mapToGlobal(position))

    def _on_header_clicked(self, column: int) -> None:
        if self._sort_column == column:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_column = column
            self._sort_ascending = True
        header = self.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(
            column,
            Qt.SortOrder.AscendingOrder
            if self._sort_ascending
            else Qt.SortOrder.DescendingOrder,
        )
        self._proxy.sort(
            column,
            Qt.SortOrder.AscendingOrder
            if self._sort_ascending
            else Qt.SortOrder.DescendingOrder,
        )

    def clear_sort(self) -> None:
        self._sort_column = None
        self._sort_ascending = True
        header = self.horizontalHeader()
        header.setSortIndicatorShown(False)
        self._proxy.sort(-1, Qt.SortOrder.AscendingOrder)
