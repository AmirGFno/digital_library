"""
Main window of the Digital Library application.

Contains the series sidebar, the book grid (with multi-selection), search,
filters, sorting, drag & drop import, the library folder that is synced on every
start and the reader integration.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import (
    QEvent,
    QByteArray,
    QFileSystemWatcher,
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
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
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
from importer import ImportResult, build_folder_plan_with_db, importer
from ui.book_card import BookCard
from ui.details_dialog import DetailsDialog
from ui.dialogs import (
    AddBookDialog,
    AddSeriesDialog,
    ConfirmDialog,
    EditVolumeDialog,
    SetCustomCoverDialog,
)
from ui import theme
from ui.folder_import_dialog import FolderImportDialog
from ui.library_grid import LibraryGrid
from ui.new_folder_dialog import ask_about_new_folders
from ui.reader_settings_dialog import ReaderSettingsDialog
from ui.restore_dialog import RestoreSeriesDialog
from ui.series_panel import SeriesPanel
from ui.name_preview_dialog import preview_when_needed
from ui.welcome_dialog import WelcomeDialog
from ui.widgets import EmptyState, SelectionBar, StatCard, ToastManager
from utils.helpers import (
    format_file_size,
    open_containing_folder,
    sort_books_naturally,
)
from utils.folder_watch import find_unmanaged_folders
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


@dataclass
class SyncOutcome:
    """What a background sync produced: changes plus folders to ask about."""

    result: ImportResult
    new_folders: List[str]


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
            new_folders: List[str] = []
            if settings.get_ask_new_folders():
                known = [
                    series.get("folder")
                    for series in db.get_all_series()
                    if series.get("folder")
                ]
                new_folders = find_unmanaged_folders(
                    self.folder,
                    known_folders=known,
                    ignored_folders=settings.get_answered_folders(),
                    known_files=set(db.get_library_index()[0]),
                )
            self.finished_ok.emit(SyncOutcome(result=result, new_folders=new_folders))
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
        # Selection is only collected on purpose: the user picks "Select several
        # books…" in the card menu, then clicks the cards one by one.
        self._selection_mode = False
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
        self._pending_folder_check = False
        self._folder_prompt_open = False
        self._page_count_text = ""

        # Throttles the "did a file disappear?" check when the window is focused.
        self._prune_timer = QTimer(self)
        self._prune_timer.setSingleShot(True)
        self._prune_timer.setInterval(800)
        self._prune_timer.timeout.connect(self._prune_missing_files)

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
        self.setMinimumSize(1080, 700)
        self.resize(1440, 900)

        # The window icon is what Windows shows on the taskbar button. The
        # application icon is already the best variant (multi-size ICO on
        # Windows), so prefer it and only fall back to the PNG asset.
        app = QApplication.instance()
        icon = app.windowIcon() if app is not None else QIcon()
        if icon.isNull():
            icon = QIcon(str(ASSETS_DIR / "icon.png"))
        if not icon.isNull():
            self.setWindowIcon(icon)

        central = QWidget()
        self.setCentralWidget(central)
        self._root_layout = QVBoxLayout(central)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        # ---- hero header ------------------------------------------------
        self.hero = QFrame()
        self.hero.setObjectName("HeroBar")
        hero_layout = QHBoxLayout(self.hero)
        hero_layout.setContentsMargins(20, 14, 20, 14)
        hero_layout.setSpacing(14)

        self.logo = QLabel()
        self.logo.setFixedSize(46, 46)
        self.logo.setPixmap(theme.logo_pixmap(46))
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(self.logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        app_title = QLabel(APP_NAME)
        app_title.setObjectName("HeroTitle")
        self.hero_subtitle = QLabel("Your comic shelf")
        self.hero_subtitle.setObjectName("MutedLabel")
        title_box.addWidget(app_title)
        title_box.addWidget(self.hero_subtitle)
        hero_layout.addLayout(title_box)
        hero_layout.addStretch(1)

        self.stat_books = StatCard("▦", "BOOKS", theme.BLUE)
        self.stat_unread = StatCard("●", "UNREAD", theme.ACCENT)
        self.stat_favorites = StatCard("★", "FAVORITES", theme.GOLD)
        self.stat_series = StatCard("≡", "SERIES", theme.VIOLET)
        for card in (self.stat_books, self.stat_unread,
                     self.stat_favorites, self.stat_series):
            hero_layout.addWidget(card)
        self.stat_unread.clicked.connect(lambda: self.read_filter_combo.setCurrentIndex(1))
        self.stat_favorites.clicked.connect(lambda: self.favorites_button.setChecked(True))

        hero_layout.addSpacing(6)

        self.add_button = QPushButton("＋  Add comics")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self._add_book)
        hero_layout.addWidget(self.add_button)

        self.import_button = QPushButton("Import folder")
        self.import_button.setObjectName("GhostButton")
        self.import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_button.clicked.connect(self._bulk_import)
        hero_layout.addWidget(self.import_button)

        self.sync_button = QPushButton("Sync")
        self.sync_button.setObjectName("GhostButton")
        self.sync_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_button.setToolTip("Check the library folder for new comics (Ctrl+R)")
        self.sync_button.clicked.connect(self._sync_library_folder)
        hero_layout.addWidget(self.sync_button)

        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("GhostButton")
        self.settings_button.setFixedWidth(42)
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setToolTip("Reader settings (Ctrl+,)")
        self.settings_button.clicked.connect(self._show_reader_settings)
        hero_layout.addWidget(self.settings_button)

        self._root_layout.addWidget(self.hero)

        accent_line = QFrame()
        accent_line.setObjectName("AccentLine")
        accent_line.setFixedHeight(2)
        self._root_layout.addWidget(accent_line)

        # ---- command bar (search + filters) -----------------------------
        self.command_container = QWidget()
        self.command_layout = QVBoxLayout(self.command_container)
        self.command_layout.setContentsMargins(0, 0, 0, 0)
        self.command_layout.setSpacing(0)
        self._root_layout.addWidget(self.command_container)

        # ---- sidebar + grid --------------------------------------------
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self._root_layout.addWidget(self.splitter, 1)

        self.series_panel = SeriesPanel()
        self.series_panel.setObjectName("SidebarPanel")
        self.series_panel.setMinimumWidth(232)
        self.series_panel.setMaximumWidth(330)
        self.series_panel.series_selected.connect(self._on_series_selected)
        self.series_panel.series_changed.connect(self._on_series_changed)
        self.series_panel.import_folder_requested.connect(self._open_folder_import)
        self.series_panel.library_folder_requested.connect(self._on_library_folder_button)
        self.series_panel.restore_requested.connect(self._restore_deleted_series)
        self.splitter.addWidget(self.series_panel)

        content = QWidget()
        content.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 10)
        content_layout.setSpacing(10)

        page_header = QHBoxLayout()
        page_header.setSpacing(10)
        self.page_title = QLabel("All books")
        self.page_title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 21px; font-weight: 700;"
        )
        page_header.addWidget(self.page_title)

        self.page_count = QLabel("")
        self.page_count.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 12px; padding-top: 6px;"
        )
        page_header.addWidget(self.page_count)
        page_header.addStretch(1)

        columns_label = QLabel("Columns")
        columns_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        page_header.addWidget(columns_label)
        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(2, 10)
        self.columns_spin.setValue(self.columns)
        self.columns_spin.setToolTip("Cards per row")
        self.columns_spin.valueChanged.connect(self._on_columns_changed)
        self.columns_spin.setFixedWidth(66)
        page_header.addWidget(self.columns_spin)
        content_layout.addLayout(page_header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("GridViewport")
        self.scroll_area.viewport().setObjectName("GridViewport")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.library_grid = LibraryGrid()
        self.library_grid.empty_area_clicked.connect(self.clear_selection)
        self.library_grid.rubber_band_finished.connect(self._on_rubber_band)
        self.grid_layout = self.library_grid.grid_layout
        self.scroll_area.setWidget(self.library_grid)
        content_layout.addWidget(self.scroll_area, 1)

        # The selection bar lives in its own strip under the grid: it never
        # covers a card, so Ctrl/Shift clicks keep hitting the books.
        self.selection_bar = SelectionBar()
        self.selection_bar.setVisible(False)
        self.selection_bar.setMaximumWidth(760)
        selection_strip = QHBoxLayout()
        selection_strip.setContentsMargins(0, 4, 0, 0)
        selection_strip.addStretch(1)
        selection_strip.addWidget(self.selection_bar)
        selection_strip.addStretch(1)
        content_layout.addLayout(selection_strip)

        self.splitter.addWidget(content)
        self.splitter.setSizes([248, 1190])
        self.splitter.setStretchFactor(1, 1)

        # ---- selection bar signals --------------------------------------
        self.selection_bar.open_requested.connect(self._open_selection)
        self.selection_bar.read_requested.connect(
            lambda value: self._set_read_many(sorted(self.selected_ids), value)
        )
        self.selection_bar.favorite_requested.connect(
            lambda value: self._set_favorite_many(sorted(self.selected_ids), value)
        )
        self.selection_bar.series_requested.connect(
            lambda: self._change_series_many(sorted(self.selected_ids))
        )
        self.selection_bar.delete_requested.connect(self._delete_selection)
        self.selection_bar.clear_requested.connect(self.clear_selection)

        self._toasts = ToastManager(central)

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

        self.restore_series_action = QAction("Restore deleted series...", self)
        self.restore_series_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self.restore_series_action.triggered.connect(self._restore_deleted_series)

        self.remove_missing_action = QAction("Remove books with missing files...", self)
        self.remove_missing_action.triggered.connect(self._remove_missing_files)

        self.ask_folders_action = QAction("Ask before adding new folders", self)
        self.ask_folders_action.setCheckable(True)
        self.ask_folders_action.setChecked(settings.get_ask_new_folders())
        self.ask_folders_action.toggled.connect(self._toggle_ask_new_folders)

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
        library_menu.addAction(self.ask_folders_action)
        library_menu.addAction(self.favorites_action)
        library_menu.addAction(self.stats_action)
        library_menu.addSeparator()
        library_menu.addAction(self.remove_missing_action)
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
        series_menu.addAction(self.restore_series_action)

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
        """Search and filter bar under the hero header."""
        bar = QFrame()
        bar.setObjectName("CommandBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText("Search title, series, writer, publisher…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(280)
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input, 1)

        layout.addWidget(self._field_label("Show"))
        self.read_filter_combo = QComboBox()
        self.read_filter_combo.addItem("All books", "all")
        self.read_filter_combo.addItem("Unread", "unread")
        self.read_filter_combo.addItem("Read", "read")
        self.read_filter_combo.addItem("Started", "started")
        self.read_filter_combo.currentIndexChanged.connect(self.refresh_books)
        layout.addWidget(self.read_filter_combo)

        self.format_combo = QComboBox()
        for label, value in FORMAT_OPTIONS:
            self.format_combo.addItem(label, value)
        self.format_combo.currentIndexChanged.connect(self.refresh_books)
        layout.addWidget(self.format_combo)

        layout.addWidget(self._field_label("Sort"))
        self.sort_combo = QComboBox()
        for label, value in SORT_OPTIONS:
            self.sort_combo.addItem(label, value)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        layout.addWidget(self.sort_combo)

        self.favorites_button = QToolButton()
        self.favorites_button.setObjectName("FilterChip")
        self.favorites_button.setText("★  Favorites")
        self.favorites_button.setCheckable(True)
        self.favorites_button.setToolTip("Show only favorites (Ctrl+D)")
        self.favorites_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.favorites_button.toggled.connect(self._on_favorites_toggled)
        layout.addWidget(self.favorites_button)

        self.command_layout.addWidget(bar)
        self._restore_view_controls()

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; padding-left: 4px;"
        )
        return label

    def _setup_statusbar(self):
        statusbar = QStatusBar()
        statusbar.setSizeGripEnabled(False)
        self.statusbar = statusbar
        self.setStatusBar(statusbar)

        self.shown_label = QLabel()
        self.shown_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        self.selection_label = QLabel()
        self.selection_label.setStyleSheet(f"color: {theme.ACCENT_GLOW}; font-size: 11px;")
        self.stats_label = QLabel()
        self.stats_label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")

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

        if hasattr(self, "series_panel"):
            self.series_panel.refresh_series()

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
        if not settings.has_library_root():
            return
        if settings.get_auto_sync():
            self._start_sync(quiet=True)
        else:
            # Automatic sync is off, but a file that disappeared from the disk
            # must still leave the library, and a folder that just appeared has
            # to be offered as a series.
            self._prune_missing_files()
            self._check_new_folders()

    def _prune_missing_files(self, silent: bool = True) -> int:
        """Keep the library in step with the disk after files move or vanish.

        Moved files keep their record (and their reading state) and files that
        are really gone leave the library. Nothing on disk is ever touched.
        """
        root = settings.get_library_root()
        relinked = db.relink_moved_books(root) if root else 0
        if root:
            db.relink_series_folders(root)
        missing = db.get_missing_books(library_root=root)
        removed = db.remove_missing_books(missing, library_root=root) if missing else 0
        pruned_series = 0
        if root:
            # Series that lost every book and whose folder is gone should not
            # linger in the sidebar; they stay restorable from the trash.
            pruned_series = db.prune_empty_series(library_root=root)

        if relinked or removed or pruned_series:
            self.refresh_books()
            self.series_panel.refresh_series()
            if not silent:
                parts = []
                if relinked:
                    parts.append(f"{relinked} moved file(s) followed")
                if removed:
                    parts.append(f"{removed} missing book(s) removed")
                if pruned_series:
                    parts.append(f"{pruned_series} empty series removed")
                self._toast("  ·  ".join(parts), "warning" if removed else "info")
        return removed

    def showEvent(self, event):
        """Re-assert the window icon right before the window is mapped.

        Windows reads the taskbar icon when the window becomes visible; setting
        it here as well keeps the taskbar button from falling back to a generic
        icon after a theme or platform change.
        """
        super().showEvent(event)
        icon = self.windowIcon()
        app = QApplication.instance()
        if icon.isNull() and app is not None:
            icon = app.windowIcon()
        if not icon.isNull():
            self.setWindowIcon(icon)

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
        else:
            # Even without automatic import the library must match the disk:
            # files that were deleted or moved while the app was closed are
            # reconciled right away.
            if settings.has_library_root():
                QTimer.singleShot(300, self._prune_missing_files)
            QTimer.singleShot(400, self._check_new_folders)

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

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowActivate:
            return
        if not settings.has_library_root() or self._syncing:
            return
        # Cheap check; a full sync is not needed to notice a file deleted in
        # Explorer while the app was in the background.
        if not self._prune_timer.isActive():
            self._prune_timer.start()

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

    def _on_library_folder_button(self):
        if settings.has_library_root():
            self._start_sync(quiet=False)
        else:
            self._choose_library_folder()

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
        if hasattr(self, "sync_button"):
            self.sync_button.setEnabled(False)
        self.statusbar.showMessage(f"Checking {folder} for new comics...")

        self._sync_worker = SyncWorker(folder, self)
        self._sync_worker.finished_ok.connect(
            lambda outcome: self._on_sync_finished(outcome, quiet)
        )
        self._sync_worker.failed.connect(self._on_sync_failed)
        self._sync_worker.start()

    def _on_sync_finished(self, outcome: SyncOutcome, quiet: bool):
        self._syncing = False
        self.sync_action.setEnabled(True)
        self.sync_button.setEnabled(True)
        self._sync_worker = None
        self._refresh_watcher()

        result = outcome.result
        if result.changed:
            self.refresh_books()
            self.series_panel.refresh_series()
            self.statusbar.showMessage(f"Library updated — {result.summary()}", 8000)
            if result.removed:
                self._toast(
                    f"{result.removed} book(s) were removed because their files are gone",
                    "warning",
                )
            if result.relinked:
                self._toast(
                    f"{result.relinked} moved file(s) kept their place in the library",
                    "info",
                )
            if not quiet:
                self._toast(result.summary(), "success")
        elif not quiet:
            self._toast("Everything is already up to date", "info")

        if outcome.new_folders:
            self._ask_about_folders(outcome.new_folders)

    def _toast(self, message: str, kind: str = "info"):
        manager = getattr(self, "_toasts", None)
        if manager is None:
            self.statusbar.showMessage(message, 6000)
            return
        manager.show(message, kind=kind)

    # ------------------------------------------------------------------
    # Folders that appeared inside the library root
    # ------------------------------------------------------------------
    def _ask_about_folders(self, folders: List[str]):
        """Ask once per folder whether it should become a series."""
        if not folders or self._folder_prompt_open:
            return
        self._folder_prompt_open = True
        try:
            decisions, remember = ask_about_new_folders(folders, self)
        finally:
            self._folder_prompt_open = False

        if decisions is None:
            # "Ask me later": keep the question for the next sync.
            return

        series_names = []
        file_only = []
        ignored = []
        for folder, decision in decisions.items():
            action = decision.get("action")
            name = decision.get("name") or Path(folder).name
            if remember or action in ("ignore", "files"):
                # Ignored folders and folders imported without a series never
                # become "known" through the database, so remember the answer.
                settings.add_answered_folder(folder)
            if action == "ignore":
                ignored.append(folder)
                continue
            if action == "series":
                self._import_single_folder(folder, series_name=name)
                series_names.append(name)
            else:
                self._import_single_folder(folder, series_name=None)
                file_only.append(Path(folder).name)

        if series_names or file_only:
            self.refresh_books()
            self.series_panel.refresh_series()
            parts = []
            if series_names:
                parts.append(
                    "New series: " + ", ".join(series_names[:3])
                    + ("…" if len(series_names) > 3 else "")
                )
            if file_only:
                parts.append(
                    "Books without a series: " + ", ".join(file_only[:3])
                    + ("…" if len(file_only) > 3 else "")
                )
            self._toast("  ·  ".join(parts), "success")
        elif ignored:
            self._toast("Folders ignored. You can import them later.", "info")

        self._refresh_watcher()

    def _import_single_folder(self, folder: str, series_name: Optional[str]):
        """Import one folder, optionally creating a series named *series_name*."""
        plan = build_folder_plan_with_db(
            folder,
            database=db,
            mode="single",
            clean_names=self.clean_names_action.isChecked(),
        )
        if not plan.groups:
            return
        names = {group.key: series_name for group in plan.groups}
        result = importer.import_plan(
            plan, names, clean_names=self.clean_names_action.isChecked()
        )
        logger.info(f"Folder '{folder}' imported: {result.summary()}")

    def _check_new_folders(self):
        """Look for new folders without running a full sync (auto-sync off)."""
        folder = settings.get_library_root()
        if not folder or not settings.get_ask_new_folders():
            return
        known = [
            series.get("folder")
            for series in db.get_all_series()
            if series.get("folder")
        ]
        candidates = find_unmanaged_folders(
            folder,
            known_folders=known,
            ignored_folders=settings.get_answered_folders(),
            known_files=set(db.get_library_index()[0]),
        )
        if candidates:
            self._ask_about_folders(candidates)

    def _restore_deleted_series(self):
        dialog = RestoreSeriesDialog(self)
        if not dialog.exec() or not dialog.restored_id:
            return
        self.series_panel.refresh_series()
        self.refresh_books()
        series = db.get_series(dialog.restored_id)
        name = series["name"] if series else "series"
        self._toast(f"Restored “{name}”", "success")

    def _remove_missing_files(self):
        missing = db.get_missing_books()
        if not missing:
            self._toast("Every book in the library still has its file", "info")
            return
        dialog = ConfirmDialog(
            "Remove missing files",
            f"{len(missing)} book(s) point to files that no longer exist.\n\n"
            "Remove them from the library? Nothing on disk is deleted.",
            parent=self,
        )
        dialog.confirm_button.setText("Remove")
        if not dialog.exec():
            return
        removed = db.remove_missing_books(missing, library_root=settings.get_library_root())
        self.refresh_books()
        self.series_panel.refresh_series()
        self._toast(f"{removed} missing book(s) removed from the library", "success")

    def _toggle_ask_new_folders(self, checked: bool):
        settings.set_ask_new_folders(checked)

    def _on_sync_failed(self, message: str):
        self._syncing = False
        self.sync_action.setEnabled(True)
        if hasattr(self, "sync_button"):
            self.sync_button.setEnabled(True)
        self._toast("The library folder could not be checked", "error")
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

        self.library_grid.set_centered(not books)
        if not books:
            self._show_empty_state()
        else:
            for index, book in enumerate(books):
                card = self._create_card(book)
                row, column = divmod(index, self.columns)
                self.library_grid.add_card(card, row, column)
                self.book_cards.append(card)

        self._update_page_header(len(books))
        self._update_card_selection()
        self._update_statusbar()
        self.scroll_area.verticalScrollBar().setValue(0)

    def _update_page_header(self, shown: int):
        """Keep the title of the grid in sync with the selected shelf."""
        if self.current_search:
            title = f"Search: {self.current_search}"
        elif self.current_series_filter == "unsorted":
            title = "Unsorted"
        elif self.current_series_filter is not None:
            series = db.get_series(self.current_series_filter)
            title = series["name"] if series else "Series"
        elif self.favorites_button.isChecked():
            title = "Favorites"
        else:
            title = "All books"

        self.page_title.setText(title)
        total = db.get_total_book_count()
        if shown == total:
            self._page_count_text = f"{shown} books"
        else:
            self._page_count_text = f"{shown} of {total} books"
        self.page_count.setText(self._page_count_text)


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
        card.select_mode_requested.connect(self._start_selection_mode)
        card.select_toggled.connect(self._on_select_circle_clicked)
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
        if self.current_search or self.current_series_filter is not None \
                or self.favorites_button.isChecked():
            title = "Nothing matches this view"
            subtitle = "Try another search, or pick a different shelf on the left."
            empty = EmptyState(title, subtitle)
            empty.add_requested.connect(self._clear_filters)
            empty.folder_requested.connect(self._clear_filters)
        else:
            title = "Your shelf is empty"
            subtitle = (
                "Drop CBZ, CBR, CB7 or PDF files here — or point the library at "
                "the folder where your comics already live."
            )
            empty = EmptyState(title, subtitle)
            empty.add_requested.connect(self._add_book)
            empty.folder_requested.connect(self._bulk_import)

        empty.setMinimumHeight(420)
        self.library_grid.grid_layout.addWidget(
            empty, 0, 0, 1, max(1, self.columns)
        )

    def _clear_filters(self):
        self.search_input.clear()
        self.current_search = ""
        self.current_series_filter = None
        self.favorites_button.setChecked(False)
        self.read_filter_combo.setCurrentIndex(0)
        self.format_combo.setCurrentIndex(0)
        self.refresh_books()

    def _update_statusbar(self):
        stats = db.get_statistics()
        self.shown_label.setText(
            f"{len(self.book_cards)} shown  ·  {stats['total']} in the library"
        )
        self.stats_label.setText(
            f"{format_file_size(stats.get('total_size') or 0)}  ·  "
            f"{stats.get('total_pages', 0) or 0} pages"
        )

        for card, value in (
            (getattr(self, "stat_books", None), stats["total"]),
            (getattr(self, "stat_unread", None), stats.get("unread_count", 0)),
            (getattr(self, "stat_favorites", None), stats.get("favorites", 0)),
            (getattr(self, "stat_series", None), stats.get("series_count", 0)),
        ):
            if card is not None:
                card.set_value(value)

        folder = settings.get_library_root()
        if hasattr(self, "hero_subtitle"):
            self.hero_subtitle.setText(
                self._shorten_path(folder) if folder else "No library folder yet"
            )

    @staticmethod
    def _shorten_path(path: str, limit: int = 58) -> str:
        if len(path) <= limit:
            return path
        return "…" + path[-(limit - 1):]

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
    def _start_selection_mode(self, book_id: Optional[int] = None):
        """Enter "pick several" mode, starting with *book_id* when given."""
        self._selection_mode = True
        if book_id is not None:
            self.selected_ids.add(book_id)
            self._anchor_id = book_id
        self._update_card_selection()

    def _on_select_circle_clicked(self, book_id: int):
        """The round checkbox in the cover corner was clicked.

        The first click starts the group selection with that book; every later
        click adds or removes a single book.
        """
        if not self._selection_mode:
            self._start_selection_mode(book_id)
            return
        self._on_card_clicked(book_id, Qt.KeyboardModifier.NoModifier)

    def exit_selection_mode(self):
        """Leave the multi-selection and drop the marks."""
        if not self._selection_mode and not self.selected_ids:
            return
        self._selection_mode = False
        self.selected_ids.clear()
        self._anchor_id = None
        self._update_card_selection()

    def _on_card_clicked(self, book_id: int, modifiers):
        if self._selection_mode:
            # Clicking cards one by one adds or removes them, no key needed.
            if book_id in self.selected_ids:
                self.selected_ids.discard(book_id)
            else:
                self.selected_ids.add(book_id)
            self._anchor_id = book_id
            self._update_card_selection()
            return

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
        if self._selection_mode:
            # Never shrink the group when a card is right-clicked.
            return
        if book_id not in self.selected_ids:
            self.selected_ids = {book_id}
            self._anchor_id = book_id
            self._update_card_selection()

    def _on_rubber_band(self, book_ids: List[int], additive: bool):
        if additive or self._selection_mode:
            self.selected_ids |= set(book_ids)
        else:
            self.selected_ids = set(book_ids)
        if len(self.selected_ids) > 1:
            # Dragging a box over several cards is a selection gesture too.
            self._selection_mode = True
        self._update_card_selection()

    def _typing_text(self):
        """Return the focused text field, if the user is typing in one.

        Ctrl+A and Delete belong to the field while it has the focus; applying
        them to the grid would swallow the caret and could delete books.
        """
        widget = QApplication.focusWidget()
        return widget if isinstance(widget, QLineEdit) else None

    def select_all(self):
        field = self._typing_text()
        if field is not None:
            field.selectAll()
            return
        self.selected_ids = {book["id"] for book in self.books}
        self._selection_mode = bool(self.selected_ids)
        self._update_card_selection()

    def clear_selection(self):
        if not self.selected_ids and not self._selection_mode:
            return
        self.selected_ids.clear()
        self._selection_mode = False
        self._anchor_id = None
        self._update_card_selection()

    def _update_card_selection(self):
        multi = self._selection_mode or len(self.selected_ids) > 1
        for card in self.book_cards:
            selected = card.book_id in self.selected_ids
            card.set_selection_mode(self._selection_mode)
            card.set_selected(selected)
            card.set_multi_selected(selected and multi)
        self.update_selection_bars()

    def update_selection_bars(self):
        count = len(self.selected_ids)
        # A single click only highlights a card; the group bar belongs to the
        # "pick several books" mode (or to a real multi-selection).
        grouping = self._selection_mode or count > 1
        self.selection_label.setText(f"{count} selected" if grouping else "")
        self.delete_selection_action.setEnabled(count > 0)

        bar = getattr(self, "selection_bar", None)
        if bar is None:
            return
        bar.set_count(count)
        bar.setVisible(count > 0 and grouping)
        if hasattr(self, "page_count"):
            self.page_count.setText(
                f"{count} selected" if count and grouping else self._page_count_text
            )

    def _open_selection(self):
        ids = sorted(self.selected_ids)
        if ids:
            self._open_many(ids, SYSTEM_READER_ID)

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
                self._toast(message, "success")
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
        if self._selection_mode:
            # While picking books a double-click must not open anything.
            return
        self._launch(book_id, reader_id=None)

    def _open_book_with(self, book_id: int, reader_id: str):
        self._launch(book_id, reader_id=reader_id)

    def _launch(self, book_id: int, reader_id: Optional[str]) -> bool:
        book = db.get_book(book_id)
        if not book:
            return False
        filepath = book["filepath"]
        if not Path(filepath).exists():
            self._handle_missing_book(book, reader_id)
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

    def _handle_missing_book(self, book: Dict, reader_id: Optional[str] = None):
        """The file is gone: look for it, or drop the dead record.

        A book is often only moved inside the library. Before asking anything
        the record is matched back to the file by its fingerprint, so the book
        opens normally and keeps its reading state.
        """
        root = settings.get_library_root()
        if root and Path(root).is_dir():
            try:
                found = db.relink_moved_books(root)
            except Exception:  # never block opening a book on a scan
                logger.exception("Could not look for the moved file")
                found = 0
            if found:
                refreshed = db.get_book(book["id"])
                if refreshed and Path(refreshed["filepath"]).exists():
                    self.refresh_books()
                    self._toast(
                        f"Found the moved file in {Path(refreshed['filepath']).parent.name}",
                        "success",
                    )
                    self._launch(refreshed["id"], reader_id)
                    return

        filepath = book.get("filepath", "")
        dialog = ConfirmDialog(
            "File not found",
            f"This book cannot be opened because its file is no longer at:\n\n"
            f"{filepath}\n\nIt was moved or deleted outside the library.\n\n"
            "Remove it from the library? Nothing on disk is deleted.",
            parent=self,
        )
        dialog.confirm_button.setText("Remove from library")
        if not dialog.exec():
            return
        db.delete_book(book["id"])
        self.selected_ids.discard(book["id"])
        self.refresh_books()
        self.series_panel.refresh_series()
        self._toast("The missing book was removed from the library", "info")

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
        if self._typing_text() is not None:
            return
        ids = self.selected_ids if book_id in self.selected_ids else {book_id}
        self._delete_books(sorted(ids))

    def _delete_selection(self):
        if self._typing_text() is not None or not self.selected_ids:
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
        self._selection_mode = False
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
        clear.triggered.connect(self.exit_selection_mode)

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
        self._refresh_watcher()
        self._toast(result.summary(), "success" if result.added else "info")

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------
    def _show_statistics(self):
        from ui.stats_dialog import StatisticsDialog

        dialog = StatisticsDialog(self)
        dialog.exec()

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
