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
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QCursor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QKeySequence,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QButtonGroup,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config import (
    APP_NAME,
    APP_VERSION,
    ASSETS_DIR,
    CARD_WIDTH,
)
from cover_extractor import cover_extractor
from database import db
from importer import ImportResult, build_folder_plan_with_db, importer
from ui.book_card import BookCard
from ui.books_table import BooksTable
from ui.details_dialog import DetailsDialog
from ui.dialogs import (
    AddBookDialog,
    AddSeriesDialog,
    ConfirmDialog,
    EditVolumeDialog,
    SetCustomCoverDialog,
)
from ui import layout as layout_tools
from ui import theme
from ui.folder_import_dialog import FolderImportDialog
from ui.library_grid import LibraryGrid
from ui.new_folder_dialog import ask_about_new_folders
from ui.reader_settings_dialog import ReaderSettingsDialog
from ui.restore_dialog import RestoreSeriesDialog
from ui.series_panel import SeriesPanel
from ui.update_dialog import UpdateCheckWorker, UpdateDialog
from ui.name_preview_dialog import preview_when_needed
from ui.welcome_dialog import WelcomeDialog
from ui.widgets import EmptyState, SelectionBar, ToastManager, fit_icon_button
from utils.helpers import (
    format_file_size,
    open_containing_folder,
    sort_books_naturally,
)
from utils.folder_watch import find_unmanaged_folders
from utils.logger import logger
from utils.reader_manager import SYSTEM_READER_ID, reader_manager
from utils import updater
from utils.settings import settings

# The empty library placeholder may not force the window to be taller than
# a 1366x768 laptop at 125 % scaling (a 614 px tall work area).
EMPTY_STATE_HEIGHT = 260

SORT_OPTIONS = [
    ("Series & volume", "series"),
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


class MaintenanceWorker(QThread):
    """Reconcile the library with the disk without freezing the window.

    Both halves of this work walk the filesystem (moved files, vanished files,
    folders that appeared), so it must never run on the UI thread: on a library
    on a slow or network drive that was the reason the window took seconds to
    answer the first click.
    """

    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, root: str, want_folders: bool, parent=None):
        super().__init__(parent)
        self.root = root
        self.want_folders = want_folders

    def run(self):  # noqa: D401 - Qt entry point
        outcome = {
            "relinked": 0,
            "removed": 0,
            "pruned_series": 0,
            "folders": [],
        }
        try:
            outcome["relinked"] = db.relink_moved_books(self.root)
            db.relink_series_folders(self.root)
            missing = db.get_missing_books(library_root=self.root)
            if missing:
                outcome["removed"] = db.remove_missing_books(
                    missing, library_root=self.root
                )
            outcome["pruned_series"] = db.prune_empty_series(library_root=self.root)

            if self.want_folders:
                known = [
                    series.get("folder")
                    for series in db.get_all_series()
                    if series.get("folder")
                ]
                outcome["folders"] = find_unmanaged_folders(
                    self.root,
                    known_folders=known,
                    ignored_folders=settings.get_answered_folders(),
                    known_files=set(db.get_library_index()[0]),
                )
        except Exception as exc:
            logger.warning("Library maintenance failed: %s", exc)
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(outcome)


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
        # resizeEvent may arrive while _setup_ui is still building the widgets.
        self._ui_ready = False
        self.current_series_filter = None  # None, "unsorted" or a series id
        self.current_search = ""
        # Cards per row are measured from the window: there is no setting for
        # it any more, so a wider window always shows more covers.
        self._layout_columns = 1
        self.view_mode = "details" if settings.get_view("view_mode") == "details" else "grid"
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
        # The installed edition asks GitHub for a newer release once at start.
        self._update_thread: Optional[UpdateCheckWorker] = None
        self._update_dialog: Optional[UpdateDialog] = None
        self._pending_update = None
        self._update_retries = 0
        # Rebuilt grids fill in batches so the window is usable immediately,
        # even with thousands of books in the library.
        self._card_queue: List[Dict] = []
        self._card_queue_index = 0
        self._card_build_generation = 0
        self._maintenance_worker: Optional[MaintenanceWorker] = None

        # Throttles the "did a file disappear?" check when the window is focused.
        self._prune_timer = QTimer(self)
        self._prune_timer.setSingleShot(True)
        self._prune_timer.setInterval(800)
        self._prune_timer.timeout.connect(self._start_maintenance)

        self.setAcceptDrops(True)
        self._setup_ui()
        self._setup_actions()
        self._fill_overflow_menu()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._restore_window_state()
        self._ui_ready = True
        self._style_status_labels()
        theme.register_restyle(self)
        self._apply_responsive_layout()
        self._apply_view_mode()
        self._update_theme_actions()
        self.refresh_books()

        if self._run_startup:
            QTimer.singleShot(120, self._startup_tasks)
            QTimer.singleShot(2400, self._auto_check_updates)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _setup_ui(self):
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        # 1080x700 does not fit a 1366x768 laptop at 125 % scaling, and the
        # buttons of the header ended up outside the window. The minimum is
        # now small enough for such a screen and the header folds itself.
        layout_tools.clamp_window(self, QSize(1440, 900), QSize(880, 560))

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

        # ---- app bar ----------------------------------------------------
        # One compact strip like the command bar of a Windows program: the
        # small icon, the name and the library folder on the left, the actions
        # on the right. The old tall hero pushed the actual books down.
        self.hero = QFrame()
        self.hero.setObjectName("AppBar")
        hero_layout = QHBoxLayout(self.hero)
        hero_layout.setContentsMargins(12, 6, 12, 6)
        hero_layout.setSpacing(8)

        self.logo = QLabel()
        self.logo.setFixedSize(24, 24)
        self.logo.setPixmap(theme.logo_pixmap(24))
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(self.logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        self.app_title = QLabel(APP_NAME)
        self.app_title.setObjectName("HeroTitle")
        self.hero_subtitle = QLabel("No comics yet")
        self.hero_subtitle.setObjectName("MutedLabel")
        title_box.addWidget(self.app_title)
        title_box.addWidget(self.hero_subtitle)
        hero_layout.addLayout(title_box, 0)
        hero_layout.addStretch(1)

        # The counts used to sit in four little cards here. On a Windows
        # display at 125 % their two lines did not fit in the strip and the
        # number overlapped its caption, so the counts live where they belong:
        # in the navigation pane and in the status bar.
        self.hero.setMinimumHeight(
            max(46, self.app_title.sizeHint().height()
                + self.hero_subtitle.sizeHint().height() + 14)
        )
        self.hero.setMaximumHeight(self.hero.minimumHeight())

        hero_layout.addSpacing(4)

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

        self.sync_button = QPushButton("↻  Sync")
        self.sync_button.setObjectName("GhostButton")
        self.sync_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_button.setToolTip("Check the library folder for new comics (F5)")
        self.sync_button.clicked.connect(self._sync_library_folder)
        hero_layout.addWidget(self.sync_button)

        # A one-click way to the dark mode: the View > Appearance menu is
        # there too, but a reader should not have to hunt for it.
        self.theme_button = QToolButton()
        self.theme_button.setObjectName("IconButton")
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        fit_icon_button(self.theme_button)
        self.theme_button.clicked.connect(self._toggle_theme)
        hero_layout.addWidget(self.theme_button)
        self._update_theme_button()

        self.settings_button = QToolButton()
        self.settings_button.setObjectName("IconButton")
        self.settings_button.setText("⚙")
        self.settings_button.setToolTip("Reader settings (Ctrl+,)")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        fit_icon_button(self.settings_button)
        self.settings_button.clicked.connect(self._show_reader_settings)
        hero_layout.addWidget(self.settings_button)

        # Shown only when the window is too narrow for the buttons above.
        self.overflow_button = QToolButton()
        self.overflow_button.setObjectName("IconButton")
        self.overflow_button.setText("⋯")
        self.overflow_button.setToolTip("More actions")
        self.overflow_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overflow_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.overflow_button.setVisible(False)
        fit_icon_button(self.overflow_button)
        hero_layout.addWidget(self.overflow_button)

        self._root_layout.addWidget(self.hero)
        self._build_overflow_menu()

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
        self.series_panel.setMinimumWidth(218)
        self.series_panel.setMaximumWidth(320)
        self.series_panel.series_selected.connect(self._on_series_selected)
        self.series_panel.series_changed.connect(self._on_series_changed)
        self.series_panel.quick_filter_selected.connect(self._on_quick_filter)
        self.series_panel.import_folder_requested.connect(self._open_folder_import)
        self.series_panel.restore_requested.connect(self._restore_deleted_series)
        self.splitter.addWidget(self.series_panel)

        content = QWidget()
        content.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 10, 12, 8)
        content_layout.setSpacing(8)

        # ---- page header -----------------------------------------------
        page_header = QHBoxLayout()
        page_header.setSpacing(8)
        self.page_title = QLabel("All books")
        page_header.addWidget(self.page_title)

        self.page_count = QLabel("")
        page_header.addWidget(self.page_count)
        page_header.addStretch(1)

        # Grid / Details switch, like the View menu of Explorer.
        self.grid_view_button = QToolButton()
        self.grid_view_button.setObjectName("ViewButton")
        self.grid_view_button.setText("⊞  Grid")
        self.grid_view_button.setToolTip("Show covers (Ctrl+1)")
        self.grid_view_button.setCheckable(True)
        self.grid_view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_view_button = QToolButton()
        self.details_view_button.setObjectName("ViewButton")
        self.details_view_button.setText("☰  Details")
        self.details_view_button.setToolTip("Show a sortable list (Ctrl+2)")
        self.details_view_button.setCheckable(True)
        self.details_view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_group.addButton(self.grid_view_button, 0)
        self.view_group.addButton(self.details_view_button, 1)
        self.view_group.idClicked.connect(self._on_view_group_clicked)
        page_header.addWidget(self.grid_view_button)
        page_header.addWidget(self.details_view_button)

        content_layout.addLayout(page_header)

        # ---- the two views ----------------------------------------------
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
        # The number of cards per row depends on the width of the viewport,
        # which settles a moment after the window is shown.
        self.scroll_area.viewport().installEventFilter(self)

        self.books_table = BooksTable()
        self.books_table.open_requested.connect(self._open_book)
        self.books_table.selection_changed.connect(self._on_table_selection)
        self.books_table.book_menu_requested.connect(self._on_table_context_menu)

        self.empty_page = QWidget()
        self.empty_layout = QVBoxLayout(self.empty_page)
        self.empty_layout.setContentsMargins(0, 0, 0, 0)

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.scroll_area)     # 0: covers
        self.view_stack.addWidget(self.books_table)     # 1: details
        self.view_stack.addWidget(self.empty_page)      # 2: nothing to show
        content_layout.addWidget(self.view_stack, 1)

        # The selection bar lives in its own strip under the grid: it never
        # covers a card, so Ctrl/Shift clicks keep hitting the books.
        self.selection_bar = SelectionBar()
        self.selection_bar.setVisible(False)
        self.selection_bar.setMaximumWidth(760)
        self.selection_bar.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        selection_strip = QHBoxLayout()
        selection_strip.setContentsMargins(0, 4, 0, 0)
        selection_strip.addStretch(1)
        selection_strip.addWidget(self.selection_bar)
        selection_strip.addStretch(1)
        content_layout.addLayout(selection_strip)

        self.splitter.addWidget(content)
        self.splitter.setSizes([232, 1160])
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

        self.check_updates_action = QAction("Check for updates…", self)
        self.check_updates_action.triggered.connect(
            lambda: self._check_for_updates(manual=True)
        )

        self.auto_update_action = QAction("Check for updates automatically", self)
        self.auto_update_action.setCheckable(True)
        self.auto_update_action.setChecked(settings.get_check_updates())
        self.auto_update_action.toggled.connect(self._toggle_auto_updates)

        self.restore_series_action = QAction("Restore deleted series...", self)
        self.restore_series_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self.restore_series_action.triggered.connect(self._restore_deleted_series)

        self.remove_missing_action = QAction("Remove books with missing files...", self)
        self.remove_missing_action.triggered.connect(self._remove_missing_files)

        self.ask_folders_action = QAction("Ask before adding new folders", self)
        self.ask_folders_action.setCheckable(True)
        self.ask_folders_action.setChecked(settings.get_ask_new_folders())
        self.ask_folders_action.toggled.connect(self._toggle_ask_new_folders)

        self.theme_shortcut_action = QAction("Toggle dark theme", self)
        self.theme_shortcut_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.theme_shortcut_action.triggered.connect(self._toggle_theme)

        self.shortcuts_action = QAction("Keyboard shortcuts", self)
        self.shortcuts_action.triggered.connect(self._show_shortcuts)

        # ---- view mode (covers / details) ------------------------------
        self.grid_view_action = QAction("Covers", self)
        self.grid_view_action.setShortcut(QKeySequence("Ctrl+1"))
        self.grid_view_action.setCheckable(True)
        self.grid_view_action.triggered.connect(lambda: self._set_view_mode("grid"))

        self.details_view_action = QAction("Details", self)
        self.details_view_action.setShortcut(QKeySequence("Ctrl+2"))
        self.details_view_action.setCheckable(True)
        self.details_view_action.triggered.connect(
            lambda: self._set_view_mode("details")
        )

        # ---- appearance --------------------------------------------------
        self.theme_actions = {}
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        for mode, label in (("system", "Follow Windows"),
                            ("light", "Light"),
                            ("dark", "Dark")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, value=mode: self._change_theme(value)
            )
            self.theme_group.addAction(action)
            self.theme_actions[mode] = action

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
        view_menu.addAction(self.grid_view_action)
        view_menu.addAction(self.details_view_action)
        view_menu.addSeparator()
        view_menu.addAction(self.theme_shortcut_action)
        view_menu.addSeparator()
        reset_view = view_menu.addAction("Reset layout")
        reset_view.triggered.connect(self._reset_view)
        view_menu.addSeparator()
        appearance_menu = view_menu.addMenu("Appearance")
        for action in self.theme_actions.values():
            appearance_menu.addAction(action)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(self.check_updates_action)
        help_menu.addAction(self.auto_update_action)
        help_menu.addSeparator()
        help_menu.addAction(self.shortcuts_action)
        help_menu.addSeparator()
        help_menu.addAction(self.about_action)

    def _build_overflow_menu(self):
        """The header actions that move into “⋯” when the window is narrow."""
        menu = QMenu(self.overflow_button)
        for text, slot in (
            ("Add comics", self._add_book),
            ("Import folder", self._bulk_import),
            ("Sync library folder", self._sync_library_folder),
            ("Reader settings", self._show_reader_settings),
            ("Library statistics", self._show_statistics),
        ):
            action = menu.addAction(text)
            action.triggered.connect(slot)
        self.overflow_menu = menu
        self.overflow_button.setMenu(menu)

    def _fill_overflow_menu(self):
        """The menu grows after the actions exist (created in _setup_actions)."""
        menu = getattr(self, "overflow_menu", None)
        if menu is None:
            return
        menu.addSeparator()
        for name in ("check_updates_action", "shortcuts_action"):
            action = getattr(self, name, None)
            if action is not None:
                menu.addAction(action)

    # Widths where the header sheds its widest pieces. The numbers are the
    # natural width of each group, so nothing is clipped before it folds.
    COMPACT_WIDTH = 1180
    NARROW_WIDTH = 940
    TINY_WIDTH = 760

    def _apply_responsive_layout(self):
        """Fold the header instead of letting its buttons leave the window."""
        if not getattr(self, "_ui_ready", False):
            return
        width = self.width()

        self.hero_subtitle.setVisible(width >= self.NARROW_WIDTH)

        narrow = width < self.NARROW_WIDTH
        self.import_button.setVisible(not narrow)
        self.sync_button.setVisible(not narrow)

        tiny = width < self.TINY_WIDTH
        self.settings_button.setVisible(not tiny)
        self.search_input.setMinimumWidth(170 if tiny else 220 if narrow else 280)

        # Below ~800 px the sidebar costs a third of the window; hide it (the
        # shelf list is also reachable from the Library menu).

        # The overflow menu appears as soon as anything moved into it.
        self.overflow_button.setVisible(narrow or tiny)

        # On a narrow window the search box gets its own row (or two), so no
        # combo has to squeeze its text into half of its width.
        if hasattr(self, "command_grid"):
            self._layout_command_bar()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_layout()
        if getattr(self, "_ui_ready", False):
            self._reflow_cards()

    def eventFilter(self, watched, event):
        if (
            getattr(self, "_ui_ready", False)
            and event.type() == QEvent.Type.Resize
            and watched is getattr(getattr(self, "scroll_area", None), "viewport", lambda: None)()
        ):
            self._reflow_cards()
        return super().eventFilter(watched, event)

    def _setup_toolbar(self):
        """Search and filter bar under the hero header."""
        bar = QFrame()
        bar.setObjectName("CommandBar")
        layout = QGridLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)
        layout.setColumnStretch(0, 1)
        self.command_grid = layout

        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText("Search title, series, writer, publisher…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(280)
        self.search_input.textChanged.connect(self._on_search_changed)

        self.show_caption = self._field_label("Show")
        self.read_filter_combo = QComboBox()
        self.read_filter_combo.addItem("All books", "all")
        self.read_filter_combo.addItem("Unread", "unread")
        self.read_filter_combo.addItem("Read", "read")
        self.read_filter_combo.addItem("Started", "started")
        self.read_filter_combo.currentIndexChanged.connect(self.refresh_books)

        self.format_combo = QComboBox()
        for label, value in FORMAT_OPTIONS:
            self.format_combo.addItem(label, value)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)

        self.sort_caption = self._field_label("Sort")
        self.sort_combo = QComboBox()
        for label, value in SORT_OPTIONS:
            self.sort_combo.addItem(label, value)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)

        self.favorites_button = QToolButton()
        self.favorites_button.setObjectName("FilterChip")
        self.favorites_button.setText("★  Favorites")
        self.favorites_button.setCheckable(True)
        self.favorites_button.setToolTip("Show only favorites (Ctrl+D)")
        self.favorites_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.favorites_button.toggled.connect(self._on_favorites_toggled)

        for combo in (self.read_filter_combo, self.format_combo, self.sort_combo):
            combo.setMinimumWidth(120)
        self._layout_command_bar("wide")
        self.command_layout.addWidget(bar)
        self._restore_view_controls()

    def _command_bar_widths(self) -> tuple[int, int]:
        """How much room one row of the filter bar needs, and two rows.

        Measured from the widgets themselves: the combo boxes are much wider
        with the Windows font than with the Linux one, so a hardcoded
        breakpoint folded the bar too late and Qt clipped the labels.
        """
        grid = self.command_grid
        spacing = grid.spacing()
        hint = lambda widget: widget.sizeHint().width()  # noqa: E731
        one_row = (
            self.search_input.minimumWidth()
            + hint(self.show_caption)
            + hint(self.read_filter_combo)
            + hint(self.format_combo)
            + hint(self.sort_caption)
            + hint(self.sort_combo)
            + hint(self.favorites_button)
            + 6 * spacing
        )
        # The favourites chip sits in the last column next to the three
        # filters, so its width is part of the row and not an alternative to
        # it. Summing only the combos left the chip squeezed on a wide font.
        two_rows = max(
            self.search_input.minimumWidth() + hint(self.favorites_button) + spacing,
            hint(self.read_filter_combo)
            + hint(self.format_combo)
            + hint(self.sort_combo)
            + hint(self.favorites_button)
            + 3 * spacing,
        )
        return one_row, two_rows

    def _command_bar_mode(self) -> str:
        """Which arrangement of the filter bar fits the current width."""
        margins = self.command_grid.contentsMargins()
        available = self.width() - margins.left() - margins.right()
        one_row, two_rows = self._command_bar_widths()

        # A little slack: Qt rounds widget sizes up, and a row that only just
        # fits still shaves a few pixels off the last combo box.
        slack = 24
        if available >= one_row + slack:
            return "wide"
        if available >= two_rows + slack:
            return "two"
        # Three rows always fit: two combo boxes side by side plus the search
        # box above them, with the favourites chip next to it.
        return "three"

    def _layout_command_bar(self, mode: str | None = None):
        """One row when there is room, otherwise two or three."""
        grid = self.command_grid
        mode = mode or self._command_bar_mode()
        if getattr(self, "_command_bar_mode_name", None) == mode:
            return
        self._command_bar_mode_name = mode

        for widget in (
            self.search_input, self.show_caption, self.read_filter_combo,
            self.format_combo, self.sort_caption, self.sort_combo,
            self.favorites_button,
        ):
            grid.removeWidget(widget)
        for column in range(7):
            grid.setColumnStretch(column, 0)
        for row in range(4):
            grid.setRowStretch(row, 0)

        show_captions = mode == "wide"
        self.show_caption.setVisible(show_captions)
        self.sort_caption.setVisible(show_captions)

        if mode == "wide":
            grid.addWidget(self.search_input, 0, 0, 1, 1)
            grid.addWidget(self.show_caption, 0, 1, 1, 1)
            grid.addWidget(self.read_filter_combo, 0, 2, 1, 1)
            grid.addWidget(self.format_combo, 0, 3, 1, 1)
            grid.addWidget(self.sort_caption, 0, 4, 1, 1)
            grid.addWidget(self.sort_combo, 0, 5, 1, 1)
            grid.addWidget(self.favorites_button, 0, 6, 1, 1)
            grid.setColumnStretch(0, 1)
        elif mode == "two":
            grid.addWidget(self.search_input, 0, 0, 1, 3)
            grid.addWidget(self.favorites_button, 0, 3, 1, 1)
            grid.addWidget(self.read_filter_combo, 1, 0, 1, 1)
            grid.addWidget(self.format_combo, 1, 1, 1, 1)
            grid.addWidget(self.sort_combo, 1, 2, 1, 1)
            grid.setColumnStretch(2, 1)
        else:
            grid.addWidget(self.search_input, 0, 0, 1, 3)
            grid.addWidget(self.favorites_button, 0, 3, 1, 1)
            grid.addWidget(self.read_filter_combo, 1, 0, 1, 4)
            grid.addWidget(self.format_combo, 2, 0, 1, 4)
            grid.addWidget(self.sort_combo, 3, 0, 1, 4)
            grid.setColumnStretch(3, 1)

        self._command_bar_narrow = mode != "wide"
        grid.invalidate()
        grid.activate()

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        if not hasattr(self, "_field_labels"):
            self._field_labels = []
        self._field_labels.append(label)
        self._style_field_label(label)
        return label

    @staticmethod
    def _style_field_label(label: QLabel) -> None:
        label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; padding-left: 4px;"
        )

    def _style_status_labels(self) -> None:
        """Inline colours of the small labels; re-run after a theme change."""
        self.page_title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 14pt; font-weight: 600;"
        )
        self.page_count.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 9pt; padding-top: 5px;"
        )
        self.shown_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; padding-left: 8px;"
        )
        self.selection_label.setStyleSheet(
            f"color: {theme.ACCENT_GLOW}; font-size: 11px;"
        )
        self.stats_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        for label in getattr(self, "_field_labels", []):
            self._style_field_label(label)
        for button in (getattr(self, "theme_button", None),
                       getattr(self, "settings_button", None),
                       getattr(self, "overflow_button", None)):
            if button is not None:
                fit_icon_button(button)

    def restyle(self) -> None:
        """Repaint the widgets that keep a few colours inline."""
        self._style_status_labels()
        self._update_theme_button()
        self.series_panel.restyle()
        for card in self.book_cards:
            card.restyle()

    def _setup_statusbar(self):
        statusbar = QStatusBar()
        statusbar.setSizeGripEnabled(False)
        statusbar.setContentsMargins(8, 0, 8, 0)
        self.statusbar = statusbar
        self.setStatusBar(statusbar)

        self.shown_label = QLabel()
        self.selection_label = QLabel()
        self.stats_label = QLabel()

        statusbar.addWidget(self.shown_label, 1)
        statusbar.addPermanentWidget(self.selection_label)
        statusbar.addPermanentWidget(self.stats_label)
        self._update_statusbar()

    # ------------------------------------------------------------------
    # View mode (covers / details)
    # ------------------------------------------------------------------
    def _on_view_group_clicked(self, index: int):
        self._set_view_mode("grid" if index == 0 else "details")

    def _set_view_mode(self, mode: str, save: bool = True):
        """Switch between the cover grid and the Explorer-style list."""
        mode = "details" if mode == "details" else "grid"
        self.view_mode = mode
        if save:
            settings.set_view("view_mode", mode)
        self._apply_view_mode()
        if mode == "grid":
            self._ensure_cards()
        self._update_page_header(len(self.books))
        self._update_statusbar()

    def _apply_view_mode(self):
        details = getattr(self, "view_mode", "grid") == "details"
        empty = not getattr(self, "books", None)
        if empty:
            self.view_stack.setCurrentIndex(2)
        else:
            self.view_stack.setCurrentIndex(1 if details else 0)
        self.grid_view_button.setChecked(not details)
        self.details_view_button.setChecked(details)
        self.grid_view_action.setChecked(not details)
        self.details_view_action.setChecked(details)
        if details:
            self.books_table.select_ids(self.selected_ids)

    def _ensure_cards(self):
        """Build the cover cards the first time the grid is shown."""
        if not self.books:
            return
        if len(self.book_cards) >= len(self.books):
            return
        self._cancel_card_build()
        for card in self.book_cards:
            card.setParent(None)
            card.deleteLater()
        self.book_cards.clear()
        self.library_grid.clear()
        self._queue_cards(self.books)

    def _on_table_selection(self, book_ids):
        """The details list drives the same selection as the cards."""
        if getattr(self, "_syncing_selection", False):
            return
        self._syncing_selection = True
        try:
            self.selected_ids = {int(value) for value in book_ids}
            self._selection_mode = len(self.selected_ids) > 1
            self._anchor_id = int(book_ids[-1]) if book_ids else None
            self._update_card_selection()
        finally:
            self._syncing_selection = False

    def _on_table_context_menu(self, book_id: int, position):
        """Right-click menu of a row: the same actions as a card."""
        book = db.get_book(book_id)
        if not book:
            return
        if book_id not in self.selected_ids:
            self.selected_ids = {book_id}
            self._anchor_id = book_id
            self._update_card_selection()
        elif len(self.selected_ids) > 1:
            self._show_bulk_menu(book_id)
            return

        menu = QMenu(self)
        menu.addAction("Open", lambda: self._open_book(book_id))
        open_with = menu.addMenu("Open with")
        open_with.addAction(
            "System default",
            lambda: self._open_book_with(book_id, SYSTEM_READER_ID),
        )
        readers = [r for r in reader_manager.available_readers() if not r.is_system]
        if readers:
            open_with.addSeparator()
            for reader in readers:
                open_with.addAction(
                    reader.name,
                    lambda _checked=False, reader_id=reader.id: self._open_book_with(
                        book_id, reader_id
                    ),
                )
        open_with.addSeparator()
        open_with.addAction("Reader settings...", self._show_reader_settings)
        menu.addAction("Details && edit...", lambda: self._show_details(book_id))
        menu.addAction("Show in folder", lambda: self._open_folder(book_id))
        menu.addSeparator()
        favorite = bool(book.get("favorite"))
        menu.addAction(
            "Remove from favorites" if favorite else "Add to favorites",
            lambda: self._toggle_favorite(book_id),
        )
        is_read = bool(book.get("is_read"))
        menu.addAction(
            "Mark as unread" if is_read else "Mark as read",
            lambda: self._toggle_read(book_id),
        )
        menu.addSeparator()
        menu.addAction("Edit volume", lambda: self._edit_volume(
            book_id, book.get("volume") or ""
        ))
        menu.addAction("Change series", lambda: self._change_series(book_id))
        menu.addAction("Set custom cover", lambda: self._set_custom_cover(book_id))
        if book.get("custom_cover"):
            menu.addAction(
                "Remove custom cover", lambda: self._remove_custom_cover(book_id)
            )
        menu.addSeparator()
        menu.addAction("Select several books…", lambda: self._start_selection_mode(book_id))
        menu.addAction("Delete from library...", lambda: self._delete_book(book_id))
        menu.exec(position)

    # ------------------------------------------------------------------
    # Shelves, format chips and the appearance menu
    # ------------------------------------------------------------------
    def _on_quick_filter(self, kind: str):
        """A shelf in the navigation pane was picked."""
        self.current_series_filter = None
        self.favorites_button.blockSignals(True)
        self.read_filter_combo.blockSignals(True)
        try:
            self.favorites_button.setChecked(kind == "favorites")
            self.favorites_action.setChecked(kind == "favorites")
            wanted = {"unread": "unread", "started": "started"}.get(kind, "all")
            index = self.read_filter_combo.findData(wanted)
            self.read_filter_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.favorites_button.blockSignals(False)
            self.read_filter_combo.blockSignals(False)
        if kind == "all":
            self.format_combo.blockSignals(True)
            self.format_combo.setCurrentIndex(0)
            self.format_combo.blockSignals(False)
        settings.set_many_view(
            {
                "filter": self.read_filter_combo.currentData(),
                "favorites_only": self.favorites_button.isChecked(),
                "format": self.format_combo.currentData(),
            }
        )
        self.refresh_books()

    def _activate_shelf(self, kind: str):
        self.series_panel.activate_shelf(kind)

    def _on_format_changed(self):
        settings.set_view("format", self.format_combo.currentData())
        self.refresh_books()

    def _update_theme_actions(self):
        current = str(settings.get_view("theme", "system") or "system")
        action = self.theme_actions.get(current)
        if action is not None:
            action.setChecked(True)
        self._update_theme_button()

    def _update_theme_button(self):
        """Show the mode the button switches *to*, like a Windows toggle."""
        button = getattr(self, "theme_button", None)
        if button is None:
            return
        if theme.current_mode() == "dark":
            button.setText("☀")
            button.setToolTip("Switch to the light theme (Ctrl+Shift+D)")
        else:
            button.setText("☾")
            button.setToolTip("Switch to the dark theme (Ctrl+Shift+D)")

    def _toggle_theme(self):
        """Flip between the light and the dark theme and remember the choice."""
        mode = "light" if theme.current_mode() == "dark" else "dark"
        self._change_theme(mode)
        self._toast("Dark theme on" if mode == "dark" else "Light theme on", "info")

    def _change_theme(self, mode: str):
        """Repaint the program in another colour mode, without a restart."""
        settings.set_many_view({"theme": mode, "theme_chosen": True})
        theme.apply_theme(QApplication.instance(), mode)
        self._update_theme_actions()
        self.view_stack.update()
        self.update()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _restore_view_controls(self):
        for widget in (self.sort_combo, self.read_filter_combo, self.format_combo,
                       self.favorites_button):
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

        details = settings.get_view("view_mode") == "details"
        self.view_mode = "details" if details else "grid"

        # The navigation pane shows the same choice as the filter row.
        shelf = "all"
        if favorites_only:
            shelf = "favorites"
        elif self.read_filter_combo.currentData() in ("unread", "started"):
            shelf = self.read_filter_combo.currentData()
        if hasattr(self, "series_panel"):
            self.series_panel.set_active_shelf(shelf)
        self.details_view_button.setChecked(details)
        self.grid_view_button.setChecked(not details)
        self.details_view_action.setChecked(details)
        self.grid_view_action.setChecked(not details)

        for widget in (self.sort_combo, self.read_filter_combo, self.format_combo,
                       self.favorites_button):
            widget.blockSignals(False)

    def _restore_window_state(self):
        geometry = settings.get_view("window_geometry", "")
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
                # The saved geometry may come from a bigger screen: shrink it
                # so the window and its buttons stay reachable.
                room = layout_tools.screen_size(self)
                if self.height() > room.height() - layout_tools.MARGIN:
                    self.resize(
                        min(self.width(), room.width() - layout_tools.MARGIN),
                        room.height() - layout_tools.MARGIN,
                    )
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
                    "sort": self.sort_combo.currentData(),
                    "filter": self.read_filter_combo.currentData(),
                    "format": self.format_combo.currentData(),
                    "favorites_only": self.favorites_button.isChecked(),
                    "view_mode": self.view_mode,
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
            # to be offered as a series. Both walk the disk, so they run in a
            # worker and never freeze the window.
            self._start_maintenance()

    def _start_maintenance(self, silent: bool = True):
        """Reconcile the library with the disk in the background."""
        if self._maintenance_worker is not None:
            return
        root = settings.get_library_root()
        if not root or not Path(root).is_dir():
            return
        worker = MaintenanceWorker(root, settings.get_ask_new_folders(), self)
        self._maintenance_worker = worker
        worker.finished_ok.connect(
            lambda outcome: self._on_maintenance_finished(outcome, silent)
        )
        worker.failed.connect(self._on_maintenance_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_maintenance_failed(self, message: str):
        self._maintenance_worker = None
        logger.info("Library maintenance skipped: %s", message)

    def _on_maintenance_finished(self, outcome: Dict, silent: bool):
        self._maintenance_worker = None
        if not isinstance(outcome, dict):
            return
        relinked = outcome.get("relinked") or 0
        removed = outcome.get("removed") or 0
        pruned = outcome.get("pruned_series") or 0
        if relinked or removed or pruned:
            self.refresh_books()
            self.series_panel.refresh_series()
            if not silent:
                parts = []
                if relinked:
                    parts.append(f"{relinked} moved file(s) followed")
                if removed:
                    parts.append(f"{removed} missing book(s) removed")
                if pruned:
                    parts.append(f"{pruned} empty series removed")
                self._toast("  ·  ".join(parts), "warning" if removed else "info")
        folders = outcome.get("folders") or []
        if folders:
            self._ask_about_folders(folders)

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
        # A combo box only knows how wide its text really is once it has been
        # polished for the first time, which happens during this event. Fold
        # the filter bar again now that the numbers are final, otherwise a
        # narrow window keeps a one-row bar that clips "All formats".
        QTimer.singleShot(0, self._apply_responsive_layout)

    def closeEvent(self, event):
        self._save_state()
        if self._watch_timer.isActive():
            self._watch_timer.stop()
        if self._sync_worker and self._sync_worker.isRunning():
            self._sync_worker.wait(3000)
        if self._maintenance_worker and self._maintenance_worker.isRunning():
            self._maintenance_worker.wait(3000)
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
                QTimer.singleShot(300, self._start_maintenance)

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
        self._cancel_card_build()
        for card in self.book_cards:
            card.setParent(None)
            card.deleteLater()
        self.book_cards.clear()
        self.library_grid.clear()

        books = self._load_books()
        self.books = books

        valid_ids = {book["id"] for book in books}
        self.selected_ids &= valid_ids

        # The details list is always filled: it costs nothing and keeps the
        # status bar and the switching between the two views instant.
        self.books_table.set_books(books)

        self.library_grid.set_centered(not books)
        self._layout_columns = self.columns_that_fit()
        self._update_page_header(len(books))
        self.scroll_area.verticalScrollBar().setValue(0)

        if not books:
            self._show_empty_state()
            self._apply_view_mode()
            self._update_card_selection()
            self._update_statusbar()
            return

        if self.view_mode == "grid":
            self._queue_cards(books)
        else:
            self._update_card_selection()
            self._update_statusbar()
        self._apply_view_mode()

    # ------------------------------------------------------------------
    # Grid filling
    # ------------------------------------------------------------------
    def columns_that_fit(self) -> int:
        """How many covers fit across the window - measured, not configured.

        There is no "columns" setting any more: the grid fills whatever width
        the window has, and every resize re-measures it. A window too narrow
        for even one card still asks for one instead of drawing half of it.
        """
        viewport = self.scroll_area.viewport().width() if hasattr(self, "scroll_area") else 0
        if viewport <= 0:
            return max(1, getattr(self, "_layout_columns", 1))
        margins = self.grid_layout.contentsMargins()
        usable = viewport - margins.left() - margins.right()
        spacing = max(0, self.grid_layout.spacing())
        per_card = CARD_WIDTH + spacing
        if usable <= 0:
            return 1
        return max(1, int((usable + spacing) // per_card))

    def _reflow_cards(self) -> None:
        """Re-place the existing cards after the window changed width."""
        columns = self.columns_that_fit()
        if columns == getattr(self, "_layout_columns", None):
            return
        self._layout_columns = columns
        cards = list(self.book_cards)
        if not cards:
            return
        layout = self.library_grid.grid_layout
        layout.setEnabled(False)
        self.library_grid.setUpdatesEnabled(False)
        try:
            for card in cards:
                layout.removeWidget(card)
            for index, card in enumerate(cards):
                self.library_grid.add_card(card, *divmod(index, columns))
        finally:
            layout.setEnabled(True)
            self.library_grid.setUpdatesEnabled(True)
            self.scroll_area.updateGeometry()

    def _card_batch_size(self, first: bool = True) -> int:
        """How many cards to build before letting the window breathe again.

        The first batch is one screenful, so the window paints a real grid
        straight away. The following batches are deliberately larger: adding
        widgets in bigger chunks costs less in total, and by then the user is
        already looking at a usable window.
        """
        columns = max(1, int(getattr(self, "_layout_columns", 1) or 1))
        if first:
            return max(24, 4 * columns)
        return max(180, 10 * columns)

    def _queue_cards(self, books: List[Dict]):
        self._card_build_generation += 1
        self._card_queue = list(books)
        self._card_queue_index = 0
        self._build_cards_batch(self._card_build_generation)

    def _cancel_card_build(self):
        self._card_build_generation += 1
        self._card_queue = []
        self._card_queue_index = 0

    def flush_card_build(self):
        """Build every queued card right now (used by tests and by shutdown)."""
        if not self._card_queue:
            return
        generation = self._card_build_generation
        while self._card_queue and generation == self._card_build_generation:
            if self._card_queue_index >= len(self._card_queue):
                break
            self._build_cards_batch(generation, limit=len(self._card_queue))

    def _build_cards_batch(self, generation: int, limit: Optional[int] = None):
        if generation != self._card_build_generation or not self._card_queue:
            return
        queue = self._card_queue
        start = self._card_queue_index
        if start >= len(queue):
            return
        size = limit or self._card_batch_size(first=start == 0)
        stop = min(len(queue), start + size)

        # One layout pass per batch instead of one per card.
        columns = self.columns_that_fit()
        self._layout_columns = columns
        layout = self.library_grid.grid_layout
        self.library_grid.setUpdatesEnabled(False)
        layout.setEnabled(False)
        try:
            for index in range(start, stop):
                book = queue[index]
                card = self._create_card(book)
                row, column = divmod(index, columns)
                self.library_grid.add_card(card, row, column)
                card.set_selection_mode(self._selection_mode)
                card.set_selected(book["id"] in self.selected_ids)
                card.set_multi_selected(
                    card.is_selected
                    and (self._selection_mode or len(self.selected_ids) > 1)
                )
                self.book_cards.append(card)
        finally:
            layout.setEnabled(True)
            self.library_grid.setUpdatesEnabled(True)
        self._card_queue_index = stop

        remaining = len(self.book_cards) < len(self.books)
        if stop < len(queue):
            if remaining and self.statusbar is not None:
                self.statusbar.showMessage(
                    f"Showing {len(self.book_cards)} of {len(queue)} books…"
                )
            # One frame later: the grid that is already built gets painted
            # first, so the window never looks frozen while it fills.
            QTimer.singleShot(16, lambda: self._build_cards_batch(generation))
            return

        self._card_queue = []
        self._card_queue_index = 0
        self._update_card_selection()
        self._update_statusbar()
        if self.statusbar is not None:
            self.statusbar.clearMessage()

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

        empty.setMinimumHeight(EMPTY_STATE_HEIGHT)
        self.library_grid.grid_layout.addWidget(
            empty, 0, 0, 1, 1
        )

        # The details page has no grid to hold the message, so it gets its own
        # copy of the same empty state.
        while self.empty_layout.count():
            item = self.empty_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        detail_empty = EmptyState(title, subtitle)
        if self.current_search or self.current_series_filter is not None \
                or self.favorites_button.isChecked():
            detail_empty.add_requested.connect(self._clear_filters)
            detail_empty.folder_requested.connect(self._clear_filters)
        else:
            detail_empty.add_requested.connect(self._add_book)
            detail_empty.folder_requested.connect(self._bulk_import)
        detail_empty.setMinimumHeight(EMPTY_STATE_HEIGHT)
        self.empty_layout.addWidget(detail_empty)

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
            f"{len(self.books)} shown  ·  {stats['total']} in the library"
        )
        self.stats_label.setText(
            f"{format_file_size(stats.get('total_size') or 0)}  ·  "
            f"{stats.get('total_pages', 0) or 0} pages"
        )

        folder = settings.get_library_root()
        if hasattr(self, "hero_subtitle"):
            total = stats.get("total", 0) or 0
            if total:
                text = f"{total} comics  ·  {stats.get('series_count', 0) or 0} series"
            else:
                text = "No comics yet"
            self.hero_subtitle.setText(text)
            self.hero_subtitle.setToolTip(folder or "No library folder yet")

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
        # Keep the details list on the same rows as the cards.
        table = getattr(self, "books_table", None)
        if table is not None and not getattr(self, "_syncing_selection", False):
            table.select_ids(self.selected_ids)
        self.update_selection_bars()

    def _fit_selection_bar(self):
        """Short labels when the bar would not fit the window."""
        bar = getattr(self, "selection_bar", None)
        if bar is None or not bar.isVisible():
            return
        # The sidebar and the grid margins take part of the width; the bar
        # lives under the grid, so it can use what the content area has.
        available = max(0, self.width() - self.series_panel.width() - 80)
        bar.use_compact_labels(False)
        if bar.sizeHint().width() > available:
            bar.use_compact_labels(True)

    def update_selection_bars(self):
        count = len(self.selected_ids)
        # A single click only highlights a card; the group bar belongs to the
        # "pick several books" mode (or to a real multi-selection).
        grouping = self._selection_mode or count > 1
        if grouping:
            QTimer.singleShot(0, self._fit_selection_bar)
        self.selection_label.setText(f"{count} selected" if grouping else "")
        self.delete_selection_action.setEnabled(count > 0)

        bar = getattr(self, "selection_bar", None)
        if bar is None:
            return
        bar.set_count(count)
        bar.setVisible(count > 0 and grouping)
        self._fit_selection_bar()
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
        self.sort_combo.setCurrentIndex(0)
        self.read_filter_combo.setCurrentIndex(0)
        self.format_combo.setCurrentIndex(0)
        self.favorites_button.setChecked(False)
        layout_tools.clamp_window(self, QSize(1280, 820), QSize(880, 560))
        self._apply_responsive_layout()
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
        dialog = SetCustomCoverDialog(
            book_id,
            book.get("title") or "Untitled",
            self,
            filepath=book.get("filepath") or "",
        )
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

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    def _auto_check_updates(self):
        """Ask GitHub for a newer release, but only in the installed edition."""
        if not settings.get_check_updates():
            return
        if not updater.is_installed_copy():
            return
        self._check_for_updates(manual=False)

    def _toggle_auto_updates(self, enabled: bool):
        settings.set_check_updates(bool(enabled))
        if enabled:
            self._toast("The installed edition will look for new versions at start.")
        else:
            self._toast("Automatic update checks are off.")

    def _check_for_updates(self, manual: bool = False):
        thread = self._update_thread
        if thread is not None and thread.isRunning():
            if manual:
                self._toast("Already checking for updates…")
            return
        if manual:
            self.statusbar.showMessage("Checking for updates…", 4000)

        worker = UpdateCheckWorker(APP_VERSION, self)
        worker.checked.connect(lambda plan: self._on_update_checked(plan, manual))
        worker.failed.connect(lambda message: self._on_update_failed(message, manual))
        worker.finished.connect(worker.deleteLater)
        self._update_thread = worker
        worker.start()

    def _on_update_failed(self, message: str, manual: bool):
        self._update_thread = None
        logger.info("Update check did not finish: %s", message)
        if manual:
            self._toast(
                "Could not check for updates. Is the internet connection working?",
                "warning",
            )

    def _on_update_checked(self, plan, manual: bool):
        self._update_thread = None
        target = getattr(plan, "target", "") if plan is not None else ""
        if not target or not updater.is_newer(target):
            if manual:
                self._toast(f"You are running the newest version ({APP_VERSION}).", "success")
            return

        if not updater.is_installed_copy():
            # A portable copy must never rewrite itself; point at the page.
            if manual:
                self._offer_portable_download(target)
            return

        if plan.is_empty:
            # The remaining releases do not chain onto this version (an old
            # install, or a release whose package was withdrawn).
            if manual or not updater.was_deferred_recently(
                target, *settings.deferred_update()
            ):
                self._offer_full_download(plan)
            return

        deferred_version, deferred_at = settings.deferred_update()
        if not manual and updater.was_deferred_recently(
            target, deferred_version, deferred_at
        ):
            return

        if not manual and self._busy_with_a_dialog():
            # Never stack the update page on top of the welcome screen or the
            # "should this folder become a series?" question; ask again in a
            # moment instead.
            if self._update_retries < 20:
                self._update_retries += 1
                self._pending_update = plan
                QTimer.singleShot(8000, self._resume_pending_update)
            return

        self._show_update_dialog(plan)

    def _busy_with_a_dialog(self) -> bool:
        app = QApplication.instance()
        return bool(app is not None and app.activeModalWidget() is not None)

    def _resume_pending_update(self):
        """Show a deferred update offer once the window is free again."""
        plan = self._pending_update
        if plan is None or self._update_dialog is not None:
            return
        if self._busy_with_a_dialog():
            if self._update_retries < 20:
                self._update_retries += 1
                QTimer.singleShot(8000, self._resume_pending_update)
            return
        self._pending_update = None
        self._update_retries = 0
        self._show_update_dialog(plan)

    def _offer_portable_download(self, version: str):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(f"{APP_NAME} - update available")
        box.setText(f"Digital Library {version} is available.")
        box.setInformativeText(
            "This is the portable edition, so it cannot update itself. Download "
            "the new file from the releases page and replace the old one; your "
            "library folder and settings stay untouched."
        )
        open_button = box.addButton(
            "Open download page", QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(updater.RELEASE_PAGE))

    def _offer_full_download(self, plan):
        """No chain reaches this version: send the user to the setup program."""
        version = plan.target
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(f"{APP_NAME} - update available")
        box.setText(f"Digital Library {version} is available.")
        box.setInformativeText(
            f"The small in-place update needs to start from a nearby version, and "
            f"there is no package from {APP_VERSION} to {version}. Download the "
            "setup program once: it installs over the current version and keeps "
            "your library and settings."
        )
        open_button = box.addButton(
            "Open download page", QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(updater.RELEASE_PAGE))

    def _show_update_dialog(self, plan):
        dialog = UpdateDialog(plan, self)
        self._update_dialog = dialog
        accepted = dialog.exec()
        self._update_dialog = None
        if dialog.applying:
            # The PowerShell helper waits for this process to exit, swaps the
            # files and starts the new version.
            logger.info("Installing update %s in place", plan.target)
            self.statusbar.showMessage("Installing the update…")
            self._quit_for_update()
            return
        if not accepted:
            settings.defer_update(plan.target)

    def _quit_for_update(self):
        """Close cleanly so the helper finds no file in use, then exit."""
        app = QApplication.instance()
        self.close()
        if app is not None:
            QTimer.singleShot(0, app.quit)

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
