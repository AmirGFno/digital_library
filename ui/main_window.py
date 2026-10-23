"""
Main window of the Digital Library application.

Features: series sidebar, search, read/favorite/format filters, multiple sort
orders, drag & drop import, reader integration ("Open with" for every detected
comic reader), details editor, statistics and persisted layout.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QByteArray, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config import (
    APP_NAME,
    APP_VERSION,
    ASSETS_DIR,
    CARD_WIDTH,
    DEFAULT_COLUMNS,
)
from cover_extractor import cover_extractor
from database import db
from importer import importer, scan_folder
from utils.helpers import (
    format_file_size,
    open_containing_folder,
    sort_books_naturally,
)
from utils.logger import logger
from utils.reader_manager import reader_manager
from utils.settings import settings
from ui.book_card import BookCard
from ui.details_dialog import DetailsDialog
from ui.dialogs import (
    AddBookDialog,
    AddSeriesDialog,
    BulkImportDialog,
    ConfirmDialog,
    EditVolumeDialog,
    SetCustomCoverDialog,
)
from ui.reader_settings_dialog import ReaderSettingsDialog
from ui.series_panel import SeriesPanel

SORT_OPTIONS = [
    ("Series && volume", "series"),
    ("Title (A-Z)", "title"),
    ("Recently added", "added"),
    ("Recently read", "opened"),
    ("Rating (high to low)", "rating"),
    ("File size (large first)", "size"),
]

FORMAT_OPTIONS = [
    ("All formats", "all"),
    ("Comics (CBZ/CBR)", "comic"),
    ("PDF", "pdf"),
    ("Images", "image"),
    ("Archives", "archive"),
]


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.current_series_filter = None  # None = all books, "unsorted", or series id
        self.current_search = ""
        self.columns = settings.get_columns()
        self.book_cards: List[BookCard] = []
        self.books: List[Dict] = []

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.refresh_books)

        self.setAcceptDrops(True)
        self._setup_ui()
        self._setup_actions()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._restore_window_state()
        self.refresh_books()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _setup_ui(self):
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumSize(1040, 700)
        self.resize(1280, 820)

        icon_path = ASSETS_DIR / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        self.series_panel = SeriesPanel()
        self.series_panel.setObjectName("Sidebar")
        self.series_panel.setMinimumWidth(210)
        self.series_panel.setMaximumWidth(340)
        self.series_panel.series_selected.connect(self._on_series_selected)
        self.series_panel.series_changed.connect(self._on_series_changed)
        self.splitter.addWidget(self.series_panel)

        books_container = QWidget()
        books_layout = QVBoxLayout(books_container)
        books_layout.setContentsMargins(14, 12, 14, 8)
        books_layout.setSpacing(8)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(14)
        self.grid_layout.setContentsMargins(6, 6, 6, 6)
        self.grid_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.scroll_area.setWidget(self.grid_container)
        books_layout.addWidget(self.scroll_area)

        self.splitter.addWidget(books_container)
        self.splitter.setSizes([230, 1050])
        self.splitter.setStretchFactor(1, 1)

    def _setup_actions(self):
        self.add_action = QAction("Add books...", self)
        self.add_action.setShortcut(QKeySequence.StandardKey.Open)
        self.add_action.triggered.connect(self._add_book)

        self.import_folder_action = QAction("Import folder...", self)
        self.import_folder_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.import_folder_action.triggered.connect(self._bulk_import)

        self.focus_search_action = QAction("Focus search", self)
        self.focus_search_action.setShortcut(QKeySequence.StandardKey.Find)
        self.focus_search_action.triggered.connect(self._focus_search)

        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut(QKeySequence("F5"))
        self.refresh_action.triggered.connect(self.refresh_books)

        self.reader_settings_action = QAction("Reader settings...", self)
        self.reader_settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.reader_settings_action.triggered.connect(self._show_reader_settings)

        self.stats_action = QAction("Library statistics...", self)
        self.stats_action.setShortcut(QKeySequence("Ctrl+I"))
        self.stats_action.triggered.connect(self._show_statistics)

        self.favorites_action = QAction("Show favorites", self)
        self.favorites_action.setShortcut(QKeySequence("Ctrl+D"))
        self.favorites_action.setCheckable(True)
        self.favorites_action.triggered.connect(self._toggle_favorites_filter)

        self.clear_cache_action = QAction("Clear cover cache", self)
        self.clear_cache_action.triggered.connect(self._clear_cache)

        self.exit_action = QAction("Exit", self)
        self.exit_action.setShortcut(QKeySequence("Alt+F4"))
        self.exit_action.triggered.connect(self.close)

        self.about_action = QAction("About", self)
        self.about_action.triggered.connect(self._show_about)

        self.shortcuts_action = QAction("Keyboard shortcuts", self)
        self.shortcuts_action.triggered.connect(self._show_shortcuts)

    def _setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.add_action)
        file_menu.addAction(self.import_folder_action)
        file_menu.addSeparator()
        file_menu.addAction(self.focus_search_action)
        file_menu.addAction(self.reader_settings_action)
        file_menu.addSeparator()
        file_menu.addAction(self.refresh_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        library_menu = menubar.addMenu("&Library")
        library_menu.addAction(self.favorites_action)
        library_menu.addAction(self.stats_action)
        library_menu.addSeparator()
        clear_cache = library_menu.addAction("Clear cover cache")
        clear_cache.triggered.connect(self._clear_cache)

        series_menu = menubar.addMenu("&Series")
        add_series = series_menu.addAction("Add series...")
        add_series.triggered.connect(self._add_series)

        view_menu = menubar.addMenu("&View")
        zoom_in = view_menu.addAction("More columns")
        zoom_in.setShortcut(QKeySequence("Ctrl++"))
        zoom_in.triggered.connect(lambda: self._change_columns(1))
        zoom_out = view_menu.addAction("Fewer columns")
        zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        zoom_out.triggered.connect(lambda: self._change_columns(-1))
        reset_view = view_menu.addAction("Reset layout")
        reset_view.triggered.connect(self._reset_view)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(self.shortcuts_action)
        help_menu.addSeparator()
        help_menu.addAction(self.about_action)

    def _setup_toolbar(self):
        toolbar = QToolBar("Main toolbar", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search title, series, writer, publisher...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(280)
        self.search_input.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.search_input)

        toolbar.addSeparator()

        self.read_filter_combo = QComboBox()
        self.read_filter_combo.addItem("All books", "all")
        self.read_filter_combo.addItem("Unread", "unread")
        self.read_filter_combo.addItem("Read", "read")
        self.read_filter_combo.addItem("Started", "started")
        self.read_filter_combo.currentIndexChanged.connect(self.refresh_books)
        toolbar.addWidget(self.read_filter_combo)

        self.format_combo = QComboBox()
        for label, value in FORMAT_OPTIONS:
            self.format_combo.addItem(label, value)
        self.format_combo.currentIndexChanged.connect(self.refresh_books)
        toolbar.addWidget(self.format_combo)

        self.sort_combo = QComboBox()
        for label, value in SORT_OPTIONS:
            self.sort_combo.addItem(label, value)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        toolbar.addWidget(self.sort_combo)

        self.favorites_button = QToolButton()
        self.favorites_button.setText("★ Favorites")
        self.favorites_button.setCheckable(True)
        self.favorites_button.setToolTip("Show only favorites (Ctrl+D)")
        self.favorites_button.toggled.connect(self._on_favorites_toggled)
        toolbar.addWidget(self.favorites_button)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        toolbar.addWidget(QLabel("Columns:"))
        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(2, 10)
        self.columns_spin.setValue(self.columns)
        self.columns_spin.valueChanged.connect(self._on_columns_changed)
        toolbar.addWidget(self.columns_spin)

        self._restore_view_controls()

    def _setup_statusbar(self):
        statusbar = QStatusBar()
        self.setStatusBar(statusbar)
        self.shown_label = QLabel()
        self.stats_label = QLabel()
        self.stats_label.setObjectName("SubtitleLabel")
        statusbar.addWidget(self.shown_label, 1)
        statusbar.addPermanentWidget(self.stats_label)
        self._update_statusbar()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _restore_view_controls(self):
        for widget in (self.sort_combo, self.read_filter_combo, self.format_combo,
                       self.favorites_button, self.columns_spin):
            widget.blockSignals(True)
        sort_value = settings.get_view("sort", "series")
        index = self.sort_combo.findData(sort_value)
        self.sort_combo.setCurrentIndex(index if index >= 0 else 0)

        filter_value = settings.get_view("filter", "all")
        index = self.read_filter_combo.findData(filter_value)
        self.read_filter_combo.setCurrentIndex(index if index >= 0 else 0)

        format_value = settings.get_view("format", "all")
        index = self.format_combo.findData(format_value)
        self.format_combo.setCurrentIndex(index if index >= 0 else 0)

        favorites_only = bool(settings.get_view("favorites_only", False))
        self.favorites_action.setChecked(favorites_only)
        self.favorites_button.setChecked(favorites_only)

        for widget in (self.sort_combo, self.read_filter_combo, self.format_combo,
                       self.favorites_button, self.columns_spin):
            widget.blockSignals(False)

    def _restore_window_state(self):
        geometry = settings.get_view("window_geometry", "")
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except Exception:
                logger.debug("Could not restore window geometry")
        splitter_state = settings.get_view("splitter_state", "")
        if splitter_state:
            try:
                self.splitter.restoreState(
                    QByteArray.fromBase64(splitter_state.encode("ascii"))
                )
            except Exception:
                logger.debug("Could not restore splitter state")

    def _save_state(self):
        try:
            geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            splitter = bytes(self.splitter.saveState().toBase64()).decode("ascii")
            settings.set_many_view(
                {
                    "window_geometry": geometry,
                    "splitter_state": splitter,
                    "columns": self.columns,
                    "sort": self.sort_combo.currentData(),
                    "filter": self.read_filter_combo.currentData(),
                    "format": self.format_combo.currentData(),
                    "favorites_only": self.favorites_button.isChecked(),
                }
            )
        except Exception as exc:
            logger.warning(f"Could not save window state: {exc}")

    def closeEvent(self, event):
        self._save_state()
        logger.info("Application window closing")
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def refresh_books(self):
        """Reload the grid using the current filters and sort order."""
        # Clear cards and grid
        for card in self.book_cards:
            card.setParent(None)
            card.deleteLater()
        self.book_cards.clear()
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        books = self._load_books()
        self.books = books

        if not books:
            self._show_empty_state()
        else:
            for index, book in enumerate(books):
                card = self._create_card(book)
                row, column = divmod(index, self.columns)
                self.grid_layout.addWidget(card, row, column)
                self.book_cards.append(card)

        self._update_statusbar()

    def _load_books(self) -> List[Dict]:
        if self.current_search:
            books = db.search_books(self.current_search)
        elif self.current_series_filter == "unsorted":
            books = db.get_books_without_series()
        elif self.current_series_filter is not None:
            books = db.get_all_books(series_id=self.current_series_filter)
        else:
            books = db.get_all_books()

        # Read-state filter
        read_filter = self.read_filter_combo.currentData()
        if read_filter == "unread":
            books = [book for book in books if not book.get("is_read")]
        elif read_filter == "read":
            books = [book for book in books if book.get("is_read")]
        elif read_filter == "started":
            books = [book for book in books if book.get("last_opened_at")]

        # Favorites filter
        if self.favorites_button.isChecked():
            books = [book for book in books if book.get("favorite")]

        # Format filter
        format_filter = self.format_combo.currentData()
        if format_filter != "all":
            books = [book for book in books if self._format_group(book) == format_filter]

        return self._apply_sort(books)

    @staticmethod
    def _format_group(book: Dict) -> str:
        path = str(book.get("filepath", "")).lower()
        if path.endswith((".cbz", ".cbr", ".cb7", ".cbt")):
            return "comic"
        if path.endswith(".pdf"):
            return "pdf"
        if path.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff")):
            return "image"
        return "archive"

    def _apply_sort(self, books: List[Dict]) -> List[Dict]:
        sort_mode = self.sort_combo.currentData() if hasattr(self, "sort_combo") else "series"
        try:
            if sort_mode == "title":
                return sorted(
                    books,
                    key=lambda book: str(book.get("title") or book.get("filepath", "")).lower(),
                )
            if sort_mode == "added":
                return sorted(
                    books,
                    key=lambda book: str(book.get("created_at") or ""),
                    reverse=True,
                )
            if sort_mode == "opened":
                return sorted(
                    books,
                    key=lambda book: str(book.get("last_opened_at") or ""),
                    reverse=True,
                )
            if sort_mode == "rating":
                return sorted(
                    sort_books_naturally(books),
                    key=lambda book: int(book.get("rating") or 0),
                    reverse=True,
                )
            if sort_mode == "size":
                return sorted(
                    books,
                    key=lambda book: int(book.get("file_size") or 0),
                    reverse=True,
                )
            return sort_books_naturally(books)
        except Exception as exc:
            logger.warning(f"Sorting failed ({sort_mode}): {exc}")
            return books

    def _create_card(self, book: Dict) -> BookCard:
        card = BookCard(book)
        card.open_requested.connect(self._open_book)
        card.open_with_requested.connect(self._open_book_with)
        card.details_requested.connect(self._show_details)
        card.toggle_read_requested.connect(self._toggle_read)
        card.favorite_requested.connect(self._toggle_favorite)
        card.edit_volume_requested.connect(self._edit_volume)
        card.edit_series_requested.connect(self._change_series)
        card.delete_requested.connect(self._delete_book)
        card.set_custom_cover_requested.connect(self._set_custom_cover)
        card.remove_custom_cover_requested.connect(self._remove_custom_cover)
        card.open_folder_requested.connect(self._open_folder)
        return card

    def _show_empty_state(self):
        empty = QWidget()
        empty.setMinimumHeight(320)
        layout = QVBoxLayout(empty)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("No books here")
        title.setObjectName("TitleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel(
            "Drop CBZ / CBR / CB7 / PDF files anywhere on this window,\n"
            "or use File → Add books... / Import folder..."
        )
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title)
        layout.addSpacing(6)
        layout.addWidget(subtitle)

        self.grid_layout.addWidget(empty, 0, 0)

    def _update_statusbar(self):
        stats = db.get_statistics()
        self.shown_label.setText(
            f"Showing {len(self.book_cards)} of {stats['total']} books"
        )
        unread = stats.get("unread_count", 0)
        favorites = stats.get("favorites", 0)
        size = format_file_size(stats.get("total_size") or 0)
        self.stats_label.setText(
            f"Read {stats.get('read_count', 0)}  •  Unread {unread}  •  "
            f"★ {favorites}  •  {stats.get('series_count', 0)} series  •  {size}"
        )

    def _refresh_card(self, book_id: int):
        book = db.get_book(book_id)
        if not book:
            self.refresh_books()
            return
        for card in self.book_cards:
            if card.book_id == book_id:
                card.update_data(book)
                break
        self._update_statusbar()

    # ------------------------------------------------------------------
    # Filters and toolbar handlers
    # ------------------------------------------------------------------
    def _focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _on_series_selected(self, series_id):
        self.current_series_filter = series_id
        self.refresh_books()

    def _on_series_changed(self):
        self.series_panel.refresh_series()
        self.refresh_books()

    def _on_search_changed(self, text: str):
        self.current_search = text.strip()
        self._search_timer.start()

    def _on_columns_changed(self, value: int):
        self.columns = int(value)
        settings.set_columns(self.columns)
        self.refresh_books()

    def _change_columns(self, delta: int):
        value = max(2, min(10, self.columns + delta))
        self.columns_spin.setValue(value)

    def _on_sort_changed(self):
        settings.set_view("sort", self.sort_combo.currentData())
        self.refresh_books()

    def _on_favorites_toggled(self, checked: bool):
        if self.favorites_action.isChecked() != checked:
            self.favorites_action.setChecked(checked)
        settings.set_view("favorites_only", checked)
        self.refresh_books()

    def _toggle_favorites_filter(self, checked: bool):
        self.favorites_button.setChecked(checked)

    def _reset_view(self):
        self.columns_spin.setValue(DEFAULT_COLUMNS)
        self.sort_combo.setCurrentIndex(0)
        self.read_filter_combo.setCurrentIndex(0)
        self.format_combo.setCurrentIndex(0)
        self.favorites_button.setChecked(False)
        self.resize(1280, 820)
        self.splitter.setSizes([230, 1050])
        self.refresh_books()

    # ------------------------------------------------------------------
    # Book operations
    # ------------------------------------------------------------------
    def _add_book(self):
        dialog = AddBookDialog(self)
        if dialog.exec():
            self.refresh_books()
            self.series_panel.refresh_series()

    def _bulk_import(self):
        dialog = BulkImportDialog(self)
        if dialog.exec():
            self.refresh_books()
            self.series_panel.refresh_series()

    def _add_series(self):
        dialog = AddSeriesDialog(self)
        if dialog.exec():
            self.series_panel.refresh_series()

    def _show_reader_settings(self):
        dialog = ReaderSettingsDialog(self)
        dialog.exec()

    def _show_details(self, book_id: int):
        dialog = DetailsDialog(book_id, self)
        dialog.exec()
        if dialog.updated:
            self._refresh_card(book_id)
            self.series_panel.refresh_series()

    def _open_book(self, book_id: int):
        self._launch(book_id, reader_id=None)

    def _open_book_with(self, book_id: int, reader_id: str):
        self._launch(book_id, reader_id=reader_id)

    def _launch(self, book_id: int, reader_id: Optional[str]):
        book = db.get_book(book_id)
        if not book:
            return
        filepath = book["filepath"]
        if not Path(filepath).exists():
            QMessageBox.warning(
                self,
                "File not found",
                f"The file no longer exists:\n{filepath}\n\n"
                "It was moved or deleted outside the library.",
            )
            return

        if reader_id is None:
            ok, message = reader_manager.open_file(filepath)
        else:
            ok, message = reader_manager.open_with(reader_id, filepath)

        if not ok:
            QMessageBox.warning(self, "Could not open book", message)
            return

        db.mark_book_opened(book_id, mark_read=settings.get_view("mark_read_on_open", True))
        self._refresh_card(book_id)

    def _toggle_read(self, book_id: int):
        new_status = db.toggle_book_read(book_id)
        if new_status is not None:
            self._refresh_card(book_id)

    def _toggle_favorite(self, book_id: int):
        db.toggle_favorite(book_id)
        self._refresh_card(book_id)
        if self.favorites_button.isChecked():
            self.refresh_books()

    def _edit_volume(self, book_id: int, current_volume: str):
        dialog = EditVolumeDialog(current_volume, self)
        if dialog.exec():
            db.update_book(book_id, volume=dialog.get_volume())
            self._refresh_card(book_id)

    def _change_series(self, book_id: int):
        dialog = QDialog(self)
        dialog.setWindowTitle("Change series")
        dialog.setMinimumWidth(340)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Series:"))
        combo = QComboBox()
        combo.addItem("None (unsorted)", None)
        for series in db.get_all_series():
            combo.addItem(series["name"], series["id"])

        book = db.get_book(book_id)
        if book and book.get("series_id"):
            index = combo.findData(book["series_id"])
            if index >= 0:
                combo.setCurrentIndex(index)
        layout.addWidget(combo)

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        save = QPushButton("Save")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(dialog.accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        if dialog.exec():
            db.update_book(book_id, series_id=combo.currentData())
            self._refresh_card(book_id)
            self.series_panel.refresh_series()

    def _set_custom_cover(self, book_id: int):
        book = db.get_book(book_id)
        if not book:
            return
        dialog = SetCustomCoverDialog(book_id, book.get("title") or "Untitled", self)
        if dialog.exec():
            self._refresh_card(book_id)

    def _remove_custom_cover(self, book_id: int):
        dialog = ConfirmDialog(
            "Remove custom cover",
            "Remove the custom cover and use the automatically extracted one?",
            parent=self,
        )
        if not dialog.exec():
            return
        book = db.get_book(book_id)
        if book and book.get("custom_cover"):
            path = book["custom_cover"]
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as exc:
                    logger.error(f"Failed to delete custom cover: {exc}")
        db.remove_custom_cover(book_id)
        self._refresh_card(book_id)

    def _open_folder(self, book_id: int):
        book = db.get_book(book_id)
        if book:
            open_containing_folder(book["filepath"])

    def _delete_book(self, book_id: int):
        book = db.get_book(book_id)
        if not book:
            return

        dialog = ConfirmDialog(
            "Delete book",
            f"Remove this book from the library?\n\n{Path(book['filepath']).name}",
            checkbox_text="Also delete the file from disk",
            parent=self,
        )
        if not dialog.exec():
            return

        cover_extractor.clear_cache(book["filepath"])
        if book.get("custom_cover") and os.path.exists(book["custom_cover"]):
            try:
                os.remove(book["custom_cover"])
            except OSError as exc:
                logger.error(f"Failed to delete custom cover: {exc}")

        if dialog.is_checkbox_checked() and os.path.exists(book["filepath"]):
            try:
                os.remove(book["filepath"])
                logger.info(f"Deleted file: {book['filepath']}")
            except OSError as exc:
                logger.error(f"Failed to delete file: {exc}")
                QMessageBox.warning(self, "Delete file", f"The file could not be deleted:\n{exc}")

        db.delete_book(book_id)
        self.refresh_books()
        self.series_panel.refresh_series()

    def _clear_cache(self):
        dialog = ConfirmDialog(
            "Clear cover cache",
            "Clear all cached cover images? They will be extracted again when needed.",
            parent=self,
        )
        if dialog.exec():
            cover_extractor.clear_cache()
            self.refresh_books()
            QMessageBox.information(self, "Cache", "Cover cache cleared.")

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths: List[str] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            path = Path(local)
            if path.is_dir():
                paths.extend(scan_folder(str(path), recursive=True))
            elif path.is_file():
                paths.append(str(path))

        if not paths:
            QMessageBox.information(
                self, "Import", "No supported comic or book files were found."
            )
            return

        progress = QProgressDialog("Importing dropped files...", None, 0, len(paths), self)
        progress.setWindowTitle("Import")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        def on_progress(index, total, filepath):
            progress.setMaximum(total)
            progress.setValue(index - 1)
            progress.setLabelText(f"Importing {Path(filepath).name}...")
            QApplication.processEvents()

        result = importer.import_files(paths, progress=on_progress)
        progress.setValue(len(paths))

        self.refresh_books()
        self.series_panel.refresh_series()
        QMessageBox.information(self, "Import finished", result.summary())

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------
    def _show_statistics(self):
        stats = db.get_statistics()
        formats = stats.get("formats", {})
        format_lines = "".join(
            f"<tr><td>{label}</td><td align='right'>{formats.get(key, 0)}</td></tr>"
            for key, label in (
                ("comic", "Comics (CBZ/CBR/CB7/CBT)"),
                ("pdf", "PDF"),
                ("image", "Images"),
                ("archive", "Archives"),
                ("other", "Other"),
            )
        )
        resume = 0
        if stats["total"]:
            resume = round(100 * stats["read_count"] / stats["total"])

        QMessageBox.information(
            self,
            "Library statistics",
            f"<h3>Library statistics</h3>"
            f"<table cellpadding='3'>"
            f"<tr><td>Books</td><td align='right'><b>{stats['total']}</b></td></tr>"
            f"<tr><td>Series</td><td align='right'>{stats['series_count']}</td></tr>"
            f"<tr><td>Read</td><td align='right'>{stats['read_count']} ({resume}%)</td></tr>"
            f"<tr><td>Unread</td><td align='right'>{stats['unread_count']}</td></tr>"
            f"<tr><td>Favorites</td><td align='right'>{stats['favorites']}</td></tr>"
            f"<tr><td>Started</td><td align='right'>{stats['started_count']}</td></tr>"
            f"<tr><td>Pages known</td><td align='right'>{stats['total_pages']}</td></tr>"
            f"<tr><td>Total size</td><td align='right'>{format_file_size(stats['total_size'])}</td></tr>"
            f"</table>"
            f"<h4>Formats</h4>"
            f"<table cellpadding='3'>{format_lines}</table>",
        )

    def _show_shortcuts(self):
        QMessageBox.information(
            self,
            "Keyboard shortcuts",
            "<b>Ctrl+O</b> — Add books<br>"
            "<b>Ctrl+Shift+O</b> — Import folder<br>"
            "<b>Ctrl+F</b> — Focus search<br>"
            "<b>Ctrl+D</b> — Toggle favorites<br>"
            "<b>Ctrl+,</b> — Reader settings<br>"
            "<b>Ctrl+I</b> — Library statistics<br>"
            "<b>Ctrl++ / Ctrl+-</b> — Columns<br>"
            "<b>F5</b> — Refresh<br>"
            "<b>Double-click</b> — Open comic<br>"
            "<b>Right-click</b> — Context menu / open with",
        )

    def _show_about(self):
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h2>{APP_NAME} {APP_VERSION}</h2>"
            "<p>A comic &amp; digital library manager for Windows, Linux and macOS.</p>"
            "<ul>"
            "<li>CBZ, CBR, CB7, CBT, ZIP, RAR, 7z, TAR, PDF and image support</li>"
            "<li>ComicInfo.xml metadata import</li>"
            "<li>Detects CDisplayEx, YACReader, ComicRack, MComix, SumatraPDF and more</li>"
            "<li>Series, volumes, favorites, ratings, reading history</li>"
            "<li>Automatic cover extraction</li>"
            "</ul>"
            "<p>Built with Python, PyQt6 and SQLite.</p>",
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "book_cards"):
            for card in self.book_cards:
                card.favorite_badge.move(CARD_WIDTH - 36, 12)
