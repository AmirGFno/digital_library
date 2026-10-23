"""
Main window of the Digital Library application.

Contains the series sidebar, the book grid (with multi-selection), search,
filters, sorting, drag & drop import, the library folder that is synced on every
start and the reader integration.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import (
    QByteArray,
    QFileSystemWatcher,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QCursor, QDragEnterEvent, QDropEvent, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
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
    DEFAULT_COLUMNS,
)
from cover_extractor import cover_extractor
from database import db
from importer import ImportResult, importer
from ui.book_card import BookCard
from ui.details_dialog import DetailsDialog
from ui.dialogs import (
    AddBookDialog,
    AddSeriesDialog,
    ConfirmDialog,
    EditVolumeDialog,
    SetCustomCoverDialog,
)
from ui.folder_import_dialog import FolderImportDialog
from ui.library_grid import LibraryGrid
from ui.reader_settings_dialog import ReaderSettingsDialog
from ui.series_panel import SeriesPanel
from ui.name_preview_dialog import preview_when_needed
from ui.welcome_dialog import WelcomeDialog
from utils.helpers import (
    format_file_size,
    open_containing_folder,
    sort_books_naturally,
)
from utils.logger import logger
from utils.reader_manager import SYSTEM_READER_ID, reader_manager
from utils.settings import settings

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


class SyncWorker(QThread):
    """Import new files from the library folder without freezing the UI."""

    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        self.folder = folder

    def run(self):
        try:
            result = importer.sync_library_folder(self.folder)
            self.finished_ok.emit(result)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Library folder sync failed")
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, run_startup: bool = True):
        super().__init__()
        self._run_startup = run_startup
        self.current_series_filter = None  # None, "unsorted" or a series id
        self.current_search = ""
        self.columns = settings.get_columns()
        self.book_cards: List[BookCard] = []
        self.books: List[Dict] = []
        self.selected_ids: set[int] = set()
        self._anchor_id: Optional[int] = None
        self._sync_worker: Optional[SyncWorker] = None
        self._syncing = False
        # Watches the library folder so freshly downloaded comics appear by
        # themselves while the app is open (the folder is also synced on start).
        self._watcher: Optional[QFileSystemWatcher] = None
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(4000)
        self._watch_timer.timeout.connect(self._on_watch_timeout)

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

        if self._run_startup:
            QTimer.singleShot(120, self._startup_tasks)

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

        self.library_grid = LibraryGrid()
        self.library_grid.empty_area_clicked.connect(self.clear_selection)
        self.library_grid.rubber_band_finished.connect(self._on_rubber_band)
        self.grid_layout = self.library_grid.grid_layout
        self.scroll_area.setWidget(self.library_grid)
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

        self.library_folder_action = QAction("Set library folder...", self)
        self.library_folder_action.triggered.connect(self._choose_library_folder)

        self.sync_action = QAction("Sync library folder now", self)
        self.sync_action.setShortcut(QKeySequence("Ctrl+R"))
        self.sync_action.triggered.connect(self._sync_library_folder)

        self.auto_sync_action = QAction("Sync on startup", self)
        self.auto_sync_action.setCheckable(True)
        self.auto_sync_action.setChecked(settings.get_auto_sync())
        self.auto_sync_action.toggled.connect(self._on_auto_sync_toggled)

        self.clean_names_action = QAction("Clean names on import", self)
        self.clean_names_action.setCheckable(True)
        self.clean_names_action.setChecked(settings.get_clean_names())
        self.clean_names_action.toggled.connect(self._on_clean_names_toggled)

        self.stats_action = QAction("Library statistics...", self)
        self.stats_action.setShortcut(QKeySequence("Ctrl+I"))
        self.stats_action.triggered.connect(self._show_statistics)

        self.favorites_action = QAction("Show favorites", self)
        self.favorites_action.setShortcut(QKeySequence("Ctrl+D"))
        self.favorites_action.setCheckable(True)
        self.favorites_action.triggered.connect(self._toggle_favorites_filter)

        self.select_all_action = QAction("Select all", self)
        self.select_all_action.setShortcut(QKeySequence.StandardKey.SelectAll)
        self.select_all_action.triggered.connect(self.select_all)

        self.clear_selection_action = QAction("Clear selection", self)
        self.clear_selection_action.setShortcut(QKeySequence("Esc"))
        self.clear_selection_action.triggered.connect(self.clear_selection)

        self.delete_selection_action = QAction("Delete selected...", self)
        self.delete_selection_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.delete_selection_action.triggered.connect(self._delete_selection)

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
        library_menu.addAction(self.library_folder_action)
        library_menu.addAction(self.sync_action)
        library_menu.addAction(self.auto_sync_action)
        library_menu.addSeparator()
        library_menu.addAction(self.clean_names_action)
        library_menu.addAction(self.favorites_action)
        library_menu.addAction(self.stats_action)
        library_menu.addSeparator()
        clear_cache = library_menu.addAction("Clear cover cache")
        clear_cache.triggered.connect(self._clear_cache)

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.select_all_action)
        edit_menu.addAction(self.clear_selection_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.delete_selection_action)

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
        self.search_input.setMinimumWidth(270)
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
        self.statusbar = statusbar
        self.setStatusBar(statusbar)
        self.shown_label = QLabel()
        self.selection_label = QLabel()
        self.selection_label.setObjectName("SubtitleLabel")
        self.stats_label = QLabel()
        self.stats_label.setObjectName("SubtitleLabel")
        statusbar.addWidget(self.shown_label, 1)
        statusbar.addPermanentWidget(self.selection_label)
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

    # ------------------------------------------------------------------
    # Folder watcher
    # ------------------------------------------------------------------
    def _refresh_watcher(self):
        """Watch the library root and its subfolders for new comics."""
        if self._watcher is None:
            self._watcher = QFileSystemWatcher(self)
            self._watcher.directoryChanged.connect(self._on_watch_changed)

        wanted = []
        root = settings.get_library_root()
        if root and Path(root).is_dir():
            wanted.append(root)
            try:
                for child in sorted(Path(root).iterdir()):
                    if child.is_dir():
                        wanted.append(str(child))
            except OSError:
                pass

        current = self._watcher.directories()
        stale = [path for path in current if path not in wanted]
        if stale:
            self._watcher.removePaths(stale)
        fresh = [path for path in wanted if path not in current]
        if fresh:
            self._watcher.addPaths(fresh)

    def _on_watch_changed(self, _path: str):
        if self._syncing:
            return
        self._refresh_watcher()
        # Wait until copying has finished before touching the files.
        self._watch_timer.start()

    def _on_watch_timeout(self):
        if self._syncing:
            self._watch_timer.start()
            return
        if settings.get_auto_sync() and settings.has_library_root():
            self._start_sync(quiet=True)

    def closeEvent(self, event):
        self._save_state()
        if self._watch_timer.isActive():
            self._watch_timer.stop()
        if self._sync_worker and self._sync_worker.isRunning():
            self._sync_worker.wait(3000)
        # Let running cover loaders finish so they never touch deleted widgets.
        BookCard.thread_pool.clear()
        BookCard.thread_pool.waitForDone(3000)
        logger.info("Application window closing")
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Startup: first-run folder + automatic sync
    # ------------------------------------------------------------------
    def _startup_tasks(self):
        if settings.is_first_run():
            self._show_welcome()
            return
        if settings.get_auto_sync() and settings.has_library_root():
            self._start_sync(quiet=True)

    def _show_welcome(self):
        dialog = WelcomeDialog(self)
        accepted = dialog.exec()
        settings.mark_first_run_done()
        if not accepted or not dialog.folder:
            self.statusbar.showMessage(
                "No library folder selected — you can add one from Library → Set library folder."
            )
            return

        settings.set_library_root(dialog.folder)
        settings.set_auto_sync(dialog.auto_sync)
        self.auto_sync_action.setChecked(dialog.auto_sync)
        self._refresh_watcher()

        if dialog.import_now:
            self._open_folder_import(dialog.folder)
        else:
            self.statusbar.showMessage(f"Library folder set to {dialog.folder}")

    def _choose_library_folder(self):
        from PyQt6.QtWidgets import QFileDialog

        start = settings.get_library_root() or settings.get_last_import_folder()
        folder = QFileDialog.getExistingDirectory(self, "Select your comics folder", start)
        if not folder:
            return
        settings.set_library_root(folder)
        settings.set_last_import_folder(folder)
        settings.mark_first_run_done()
        self.statusbar.showMessage(f"Library folder: {folder}")
        self._refresh_watcher()
        self._start_sync(quiet=False)

    def _sync_library_folder(self):
        if not settings.has_library_root():
            QMessageBox.information(
                self,
                "No library folder",
                "Choose a library folder first (Library → Set library folder...).",
            )
            return
        self._start_sync(quiet=False)

    def _start_sync(self, quiet: bool):
        if self._syncing:
            return
        folder = settings.get_library_root()
        if not folder:
            return

        self._syncing = True
        self.sync_action.setEnabled(False)
        self.statusbar.showMessage(f"Checking {folder} for new comics...")

        self._sync_worker = SyncWorker(folder, self)
        self._sync_worker.finished_ok.connect(
            lambda result: self._on_sync_finished(result, quiet)
        )
        self._sync_worker.failed.connect(self._on_sync_failed)
        self._sync_worker.start()

    def _on_sync_finished(self, result: ImportResult, quiet: bool):
        self._syncing = False
        self.sync_action.setEnabled(True)
        self._sync_worker = None
        self._refresh_watcher()

        if result.added:
            self.refresh_books()
            self.series_panel.refresh_series()
            self.statusbar.showMessage(f"Library updated — {result.summary()}", 8000)
            if not quiet:
                QMessageBox.information(self, "Library sync", result.summary())
        else:
            self.statusbar.showMessage(
                f"Library is up to date ({result.skipped} already known)", 5000
            )
            if not quiet:
                QMessageBox.information(
                    self,
                    "Library sync",
                    "No new comics were found in the library folder.",
                )

    def _on_sync_failed(self, message: str):
        self._syncing = False
        self.sync_action.setEnabled(True)
        self._sync_worker = None
        self.statusbar.showMessage("Library sync failed", 5000)
        if message:
            logger.error(f"Sync failed: {message}")

    def _on_auto_sync_toggled(self, checked: bool):
        settings.set_auto_sync(checked)

    def _on_clean_names_toggled(self, checked: bool):
        settings.set_clean_names(checked)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def refresh_books(self):
        """Reload the grid using the current filters and sort order."""
        for card in self.book_cards:
            card.setParent(None)
            card.deleteLater()
        self.book_cards.clear()
        self.library_grid.clear()

        books = self._load_books()
        self.books = books

        valid_ids = {book["id"] for book in books}
        self.selected_ids &= valid_ids

        if not books:
            self._show_empty_state()
        else:
            for index, book in enumerate(books):
                card = self._create_card(book)
                row, column = divmod(index, self.columns)
                self.library_grid.add_card(card, row, column)
                self.book_cards.append(card)

        self._update_card_selection()
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

        read_filter = self.read_filter_combo.currentData()
        if read_filter == "unread":
            books = [book for book in books if not book.get("is_read")]
        elif read_filter == "read":
            books = [book for book in books if book.get("is_read")]
        elif read_filter == "started":
            books = [book for book in books if book.get("last_opened_at")]

        if self.favorites_button.isChecked():
            books = [book for book in books if book.get("favorite")]

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
                    books, key=lambda book: str(book.get("created_at") or ""), reverse=True
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
                    books, key=lambda book: int(book.get("file_size") or 0), reverse=True
                )
            return sort_books_naturally(books)
        except Exception as exc:
            logger.warning(f"Sorting failed ({sort_mode}): {exc}")
            return books

    def _create_card(self, book: Dict) -> BookCard:
        card = BookCard(book)
        card.clicked.connect(self._on_card_clicked)
        card.bulk_context_requested.connect(self._show_bulk_menu)
        card.context_opened.connect(self._on_card_context)
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
            "Drop CBZ / CBR / CB7 / PDF files or a whole folder on this window,\n"
            "or use File → Add books... / Import folder..."
        )
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title)
        layout.addSpacing(6)
        layout.addWidget(subtitle)

        self.library_grid.add_card(empty, 0, 0)

    def _update_statusbar(self):
        stats = db.get_statistics()
        self.shown_label.setText(f"Showing {len(self.book_cards)} of {stats['total']} books")
        self.stats_label.setText(
            f"Read {stats.get('read_count', 0)}  •  "
            f"Unread {stats.get('unread_count', 0)}  •  "
            f"★ {stats.get('favorites', 0)}  •  "
            f"{stats.get('series_count', 0)} series  •  "
            f"{format_file_size(stats.get('total_size') or 0)}"
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
    # Selection
    # ------------------------------------------------------------------
    def _on_card_clicked(self, book_id: int, modifiers):
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if ctrl:
            if book_id in self.selected_ids:
                self.selected_ids.discard(book_id)
            else:
                self.selected_ids.add(book_id)
        elif shift and self._anchor_id is not None:
            order = [book["id"] for book in self.books]
            if self._anchor_id in order and book_id in order:
                start = order.index(self._anchor_id)
                end = order.index(book_id)
                low, high = sorted((start, end))
                self.selected_ids = set(order[low:high + 1])
            else:
                self.selected_ids = {book_id}
        else:
            self.selected_ids = {book_id}

        self._anchor_id = book_id
        self._update_card_selection()

    def _on_card_context(self, book_id: int):
        if book_id not in self.selected_ids:
            self.selected_ids = {book_id}
            self._anchor_id = book_id
            self._update_card_selection()

    def _on_rubber_band(self, book_ids: List[int], additive: bool):
        if additive:
            self.selected_ids |= set(book_ids)
        else:
            self.selected_ids = set(book_ids)
        self._update_card_selection()

    def select_all(self):
        self.selected_ids = {book["id"] for book in self.books}
        self._update_card_selection()

    def clear_selection(self):
        if not self.selected_ids:
            return
        self.selected_ids.clear()
        self._update_card_selection()

    def _update_card_selection(self):
        multi = len(self.selected_ids) > 1
        for card in self.book_cards:
            selected = card.book_id in self.selected_ids
            card.set_selected(selected)
            card.set_multi_selected(selected and multi)
        self.update_selection_bars()

    def update_selection_bars(self):
        count = len(self.selected_ids)
        self.selection_label.setText(f"{count} selected" if count else "")
        self.delete_selection_action.setEnabled(count > 0)

    # ------------------------------------------------------------------
    # Filters and toolbar handlers
    # ------------------------------------------------------------------
    def _on_series_selected(self, series_id):
        self.current_series_filter = series_id
        self.refresh_books()

    def _on_series_changed(self):
        self.series_panel.refresh_series()
        self.refresh_books()

    def _on_search_changed(self, text: str):
        self.current_search = text.strip()
        self._search_timer.start()

    def _focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _on_columns_changed(self, value: int):
        self.columns = int(value)
        settings.set_columns(self.columns)
        self.refresh_books()

    def _change_columns(self, delta: int):
        self.columns_spin.setValue(max(2, min(10, self.columns + delta)))

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
    # Import
    # ------------------------------------------------------------------
    def _add_book(self):
        dialog = AddBookDialog(self)
        if dialog.exec():
            self.refresh_books()
            self.series_panel.refresh_series()

    def _bulk_import(self):
        start = settings.get_library_root() or settings.get_last_import_folder()
        self._open_folder_import(start or "")

    def _open_folder_import(self, folder: str):
        if not folder:
            folder = settings.get_last_import_folder()
        dialog = FolderImportDialog(self, folder=folder or None)
        if dialog.exec():
            chosen = dialog.folder_input.text().strip()
            if chosen:
                settings.set_last_import_folder(chosen)
            self.refresh_books()
            self.series_panel.refresh_series()
            result = dialog.result
            if result and result.added:
                # New folders may need watching as well.
                self._refresh_watcher()
            message = dialog.summary_text()
            if message:
                QMessageBox.information(self, "Import finished", message)
        else:
            self.statusbar.showMessage("Folder import cancelled — nothing was added.")

    def _add_series(self):
        dialog = AddSeriesDialog(self)
        if dialog.exec():
            self.series_panel.refresh_series()

    def _show_reader_settings(self):
        dialog = ReaderSettingsDialog(self)
        if dialog.exec():
            # Reader changed: refresh cards so the "Open with" menu is current.
            for card in self.book_cards:
                card.update_data(card.book_data)

    def _show_details(self, book_id: int):
        dialog = DetailsDialog(book_id, self)
        dialog.exec()
        if dialog.updated:
            self._refresh_card(book_id)
            self.series_panel.refresh_series()

    # ------------------------------------------------------------------
    # Book operations
    # ------------------------------------------------------------------
    def _open_book(self, book_id: int):
        self._launch(book_id, reader_id=None)

    def _open_book_with(self, book_id: int, reader_id: str):
        self._launch(book_id, reader_id=reader_id)

    def _launch(self, book_id: int, reader_id: Optional[str]) -> bool:
        book = db.get_book(book_id)
        if not book:
            return False
        filepath = book["filepath"]
        if not Path(filepath).exists():
            QMessageBox.warning(
                self,
                "File not found",
                f"The file no longer exists:\n{filepath}\n\n"
                "It was moved or deleted outside the library.",
            )
            return False

        if reader_id is None:
            ok, message = reader_manager.open_file(filepath)
        else:
            ok, message = reader_manager.open_with(reader_id, filepath)

        if not ok:
            QMessageBox.warning(self, "Could not open book", message)
            return False

        db.mark_book_opened(book_id, mark_read=settings.get_view("mark_read_on_open", True))
        self._refresh_card(book_id)
        return True

    def _toggle_read(self, book_id: int):
        if db.toggle_book_read(book_id) is not None:
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
        series_id = self._ask_series()
        if series_id is _CANCELLED:
            return
        db.update_book(book_id, series_id=series_id)
        self._refresh_card(book_id)
        self.series_panel.refresh_series()

    def _ask_series(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Change series")
        dialog.setMinimumWidth(360)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Series:"))
        combo = QComboBox()
        combo.addItem("None (unsorted)", None)
        for series in db.get_all_series():
            combo.addItem(series["name"], series["id"])
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

        if not dialog.exec():
            return _CANCELLED
        return combo.currentData()

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
        if book and book.get("custom_cover") and os.path.exists(book["custom_cover"]):
            try:
                os.remove(book["custom_cover"])
            except OSError as exc:
                logger.error(f"Failed to delete custom cover: {exc}")
        db.remove_custom_cover(book_id)
        self._refresh_card(book_id)

    def _open_folder(self, book_id: int):
        book = db.get_book(book_id)
        if book:
            open_containing_folder(book["filepath"])

    def _delete_book(self, book_id: int):
        ids = self.selected_ids if book_id in self.selected_ids else {book_id}
        self._delete_books(sorted(ids))

    def _delete_selection(self):
        if not self.selected_ids:
            return
        self._delete_books(sorted(self.selected_ids))

    def _delete_books(self, book_ids: List[int]):
        books = [db.get_book(book_id) for book_id in book_ids]
        books = [book for book in books if book]
        if not books:
            return

        if len(books) == 1:
            message = f"Remove this book from the library?\n\n{Path(books[0]['filepath']).name}"
        else:
            message = f"Remove these {len(books)} books from the library?"

        dialog = ConfirmDialog(
            "Delete books",
            message,
            checkbox_text="Also delete the files from disk",
            parent=self,
        )
        if not dialog.exec():
            return

        delete_files = dialog.is_checkbox_checked()
        for book in books:
            cover_extractor.clear_cache(book["filepath"])
            if book.get("custom_cover") and os.path.exists(book["custom_cover"]):
                try:
                    os.remove(book["custom_cover"])
                except OSError:
                    pass
            if delete_files and os.path.exists(book["filepath"]):
                try:
                    os.remove(book["filepath"])
                except OSError as exc:
                    logger.error(f"Failed to delete file {book['filepath']}: {exc}")
            db.delete_book(book["id"])

        self.selected_ids.clear()
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
    # Multi-selection context menu
    # ------------------------------------------------------------------
    def _show_bulk_menu(self, book_id: int):
        ids = sorted(self.selected_ids)
        if not ids:
            return

        menu = QMenu(self)
        header = menu.addAction(f"{len(ids)} books selected")
        header.setEnabled(False)
        menu.addSeparator()

        # Open with -----------------------------------------------------
        open_menu = menu.addMenu("Open all with")
        default_action = open_menu.addAction("System default")
        default_action.triggered.connect(
            lambda: self._open_many(ids, SYSTEM_READER_ID)
        )
        readers = [r for r in reader_manager.available_readers() if not r.is_system]
        if readers:
            open_menu.addSeparator()
            for reader in readers:
                action = open_menu.addAction(reader.name)
                action.triggered.connect(
                    lambda _checked=False, reader_id=reader.id: self._open_many(ids, reader_id)
                )

        menu.addSeparator()

        read_action = menu.addAction("Mark as read")
        read_action.triggered.connect(lambda: self._set_read_many(ids, True))
        unread_action = menu.addAction("Mark as unread")
        unread_action.triggered.connect(lambda: self._set_read_many(ids, False))

        favorite_action = menu.addAction("Add to favorites")
        favorite_action.triggered.connect(lambda: self._set_favorite_many(ids, True))
        unfavorite_action = menu.addAction("Remove from favorites")
        unfavorite_action.triggered.connect(lambda: self._set_favorite_many(ids, False))

        menu.addSeparator()

        series_action = menu.addAction("Change series...")
        series_action.triggered.connect(lambda: self._change_series_many(ids))

        select_all = menu.addAction("Select all")
        select_all.triggered.connect(self.select_all)
        clear = menu.addAction("Clear selection")
        clear.triggered.connect(self.clear_selection)

        menu.addSeparator()

        delete_action = menu.addAction(f"Delete {len(ids)} books...")
        delete_action.triggered.connect(lambda: self._delete_books(ids))

        menu.exec(QCursor.pos())

    def _open_many(self, ids: List[int], reader_id: str):
        if len(ids) > 12:
            answer = QMessageBox.question(
                self,
                "Open many files",
                f"Open {len(ids)} files at once?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        failures = 0
        for book_id in ids:
            book = db.get_book(book_id)
            if not book or not Path(book["filepath"]).exists():
                failures += 1
                continue
            if reader_id == SYSTEM_READER_ID:
                ok, _ = reader_manager.open_system_default(book["filepath"])
            else:
                ok, _ = reader_manager.open_with(reader_id, book["filepath"])
            if not ok:
                failures += 1
            db.mark_book_opened(book_id, mark_read=settings.get_view("mark_read_on_open", True))

        self.refresh_books()
        if failures:
            QMessageBox.warning(
                self,
                "Open files",
                f"{failures} file(s) could not be opened (missing file or reader).",
            )

    def _set_read_many(self, ids: List[int], is_read: bool):
        for book_id in ids:
            book = db.get_book(book_id)
            if book is None:
                continue
            if bool(book.get("is_read")) != is_read:
                db.toggle_book_read(book_id)
        self.refresh_books()
        self.series_panel.refresh_series()

    def _set_favorite_many(self, ids: List[int], favorite: bool):
        for book_id in ids:
            book = db.get_book(book_id)
            if book is None:
                continue
            if bool(book.get("favorite")) != favorite:
                db.toggle_favorite(book_id)
        self.refresh_books()

    def _change_series_many(self, ids: List[int]):
        series_id = self._ask_series()
        if series_id is _CANCELLED:
            return
        for book_id in ids:
            db.update_book(book_id, series_id=series_id)
        self.refresh_books()
        self.series_panel.refresh_series()

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        files: List[str] = []
        folders: List[str] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            path = Path(local)
            if path.is_dir():
                folders.append(str(path))
            elif path.is_file():
                files.append(str(path))

        if folders:
            # A folder always gets the preview dialog: this is where the user
            # decides whether it becomes a series.
            self._open_folder_import(folders[0])
            return

        if not files:
            QMessageBox.information(
                self, "Import", "No supported comic or book files were found."
            )
            return

        # Never rename a file silently: show the cleaned title first.
        clean_names = self.clean_names_action.isChecked()
        if clean_names:
            preview = preview_when_needed(files, self)
            if preview is not None:
                if not preview.exec():
                    self.statusbar.showMessage("Import cancelled — nothing was added.")
                    return
                clean_names = preview.use_clean_names

        progress = QProgressDialog("Importing dropped files...", None, 0, len(files), self)
        progress.setWindowTitle("Import")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        def on_progress(index, total, filepath):
            progress.setMaximum(total)
            progress.setValue(index - 1)
            progress.setLabelText(f"Importing {Path(filepath).name}...")
            QApplication.processEvents()

        result = importer.import_files(
            files,
            clean_names=clean_names,
            progress=on_progress,
        )
        progress.setValue(len(files))

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

        root = settings.get_library_root() or "not set"

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
            f"<tr><td>Total size</td><td align='right'>{format_file_size(stats['total_size'])}</td></tr>"
            f"</table>"
            f"<h4>Formats</h4>"
            f"<table cellpadding='3'>{format_lines}</table>"
            f"<h4>Library folder</h4><p>{root}</p>",
        )

    def _show_shortcuts(self):
        QMessageBox.information(
            self,
            "Keyboard shortcuts",
            "<b>Ctrl+O</b> — Add books<br>"
            "<b>Ctrl+Shift+O</b> — Import folder<br>"
            "<b>Ctrl+R</b> — Sync library folder<br>"
            "<b>Ctrl+F</b> — Focus search<br>"
            "<b>Ctrl+D</b> — Toggle favorites<br>"
            "<b>Ctrl+A</b> — Select all<br>"
            "<b>Esc</b> — Clear selection<br>"
            "<b>Delete</b> — Delete selected books<br>"
            "<b>Ctrl+,</b> — Reader settings<br>"
            "<b>Ctrl+I</b> — Library statistics<br>"
            "<b>Ctrl++ / Ctrl+-</b> — Columns<br>"
            "<b>F5</b> — Refresh<br>"
            "<b>Double-click</b> — Open comic<br>"
            "<b>Ctrl / Shift + click</b> — Multi-select<br>"
            "<b>Drag on empty space</b> — Rubber-band select",
        )

    def _show_about(self):
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h2>{APP_NAME} {APP_VERSION}</h2>"
            "<p>A comic &amp; digital library manager for Windows, Linux and macOS.</p>"
            "<ul>"
            "<li>CBZ, CBR, CB7, CBT, ZIP, RAR, 7z, TAR, PDF and image support</li>"
            "<li>ComicInfo.xml metadata, automatic series from folders</li>"
            "<li>Unique volume numbers, duplicate detection, clean titles</li>"
            "<li>Detects CDisplayEx, YACReader, ComicRack, MComix and more</li>"
            "<li>Multi-select with bulk actions</li>"
            "</ul>"
            "<p>Built with Python, PyQt6 and SQLite.</p>",
        )


_CANCELLED = object()
