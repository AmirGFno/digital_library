"""
Book card widget for the library grid.

A card shows the cover (loaded in a worker thread), title, volume, series,
favorite/rating state and exposes a rich context menu, including "Open with"
for every detected comic reader.
"""
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QMenu, QVBoxLayout

from config import CARD_HEIGHT, CARD_WIDTH, COVER_HEIGHT
from cover_extractor import cover_extractor
from database import db
from utils.logger import logger
from utils.reader_manager import SYSTEM_READER_ID, reader_manager


class CoverLoaderSignals(QObject):
    """Signals for the cover loader worker."""

    finished = pyqtSignal(str, str)  # book_id, cover_path


class CoverLoaderWorker(QRunnable):
    """Load (and cache) a cover in a background thread."""

    def __init__(self, book_id: str, filepath: str):
        super().__init__()
        self.book_id = book_id
        self.filepath = filepath
        self.signals = CoverLoaderSignals()

    def _emit(self, cover_path: str):
        """Emit safely: the card may already be gone while the app closes."""
        try:
            self.signals.finished.emit(self.book_id, cover_path)
        except RuntimeError:
            # The Qt object was deleted (window closed mid-load); nothing to do.
            pass

    def run(self):
        try:
            custom_cover = db.get_custom_cover(int(self.book_id))
            if custom_cover and Path(custom_cover).exists():
                self._emit(custom_cover)
                return
            cover_path = cover_extractor.get_cover(self.filepath, int(self.book_id))
            self._emit(cover_path or "")
        except Exception as exc:
            logger.error(f"Cover loading error for {self.filepath}: {exc}")
            self._emit("")


class BookCard(QFrame):
    """Widget representing a single book."""

    clicked = pyqtSignal(int, object)          # book_id, keyboard modifiers
    context_opened = pyqtSignal(int)           # right-click, before the menu shows
    bulk_context_requested = pyqtSignal(int)   # right-click on a multi-selection
    open_requested = pyqtSignal(int)
    open_with_requested = pyqtSignal(int, str)
    details_requested = pyqtSignal(int)
    toggle_read_requested = pyqtSignal(int)
    favorite_requested = pyqtSignal(int)
    edit_volume_requested = pyqtSignal(int, str)
    edit_series_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    set_custom_cover_requested = pyqtSignal(int)
    remove_custom_cover_requested = pyqtSignal(int)
    open_folder_requested = pyqtSignal(int)

    thread_pool = QThreadPool()

    def __init__(self, book_data: dict, parent=None):
        super().__init__(parent)
        self.book_data = book_data
        self.book_id = book_data["id"]
        self._setup_ui()
        self._load_cover()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        self.setObjectName("BookCard")
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self.book_data.get("filepath", ""))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self._selected = False
        self._multi = False

        self.cover_label = QLabel("Loading...")
        self.cover_label.setFixedHeight(COVER_HEIGHT)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet(
            "background-color: #101216; border-radius: 6px; color: #5c646e;"
        )
        layout.addWidget(self.cover_label)

        self.title_label = QLabel(self._display_title())
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(38)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title_label.setStyleSheet("font-weight: 600; font-size: 12px; color: #ffffff;")
        layout.addWidget(self.title_label)

        self.info_label = QLabel(self._info_text())
        self.info_label.setStyleSheet("font-size: 10px; color: #8b949e;")
        layout.addWidget(self.info_label)

        self.status_label = QLabel()
        self.status_label.setStyleSheet("font-size: 10px;")
        layout.addWidget(self.status_label)

        # Favorite badge overlays the cover.
        self.favorite_badge = QLabel("★", self)
        self.favorite_badge.setStyleSheet(
            "color: #ffb400; font-size: 20px; background: rgba(20, 22, 26, 190);"
            "border-radius: 10px; padding: 0 3px;"
        )
        self.favorite_badge.setFixedSize(28, 28)
        self.favorite_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.favorite_badge.move(CARD_WIDTH - 36, 12)
        self.favorite_badge.setVisible(False)

        self.check_badge = QLabel("✓", self)
        self.check_badge.setStyleSheet(
            "color: #ffffff; font-size: 13px; font-weight: bold;"
            "background: #e8552d; border-radius: 11px;"
        )
        self.check_badge.setFixedSize(22, 22)
        self.check_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.check_badge.move(10, 12)
        self.check_badge.setVisible(False)

        # Let clicks reach the card itself instead of the child labels.
        for widget in (self.cover_label, self.title_label, self.info_label,
                       self.status_label, self.favorite_badge, self.check_badge):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._refresh_state()

    def _display_title(self) -> str:
        title = self.book_data.get("title") or Path(self.book_data["filepath"]).stem
        return str(title)

    def _info_text(self) -> str:
        parts = []
        if self.book_data.get("volume"):
            parts.append(f"Vol. {self.book_data['volume']}")
        if self.book_data.get("series_name"):
            parts.append(str(self.book_data["series_name"])[:22])
        if not parts:
            parts.append(Path(self.book_data["filepath"]).suffix.upper().lstrip("."))
        return "  •  ".join(parts)

    def _refresh_state(self):
        favorite = bool(self.book_data.get("favorite"))
        is_read = bool(self.book_data.get("is_read"))
        rating = int(self.book_data.get("rating") or 0)

        self.favorite_badge.setVisible(favorite)

        status_parts = []
        status_parts.append("✓ Read" if is_read else "● Unread")
        if rating:
            status_parts.append("★" * rating + "☆" * (5 - rating))
        self.status_label.setText("   ".join(status_parts))
        self.status_label.setStyleSheet(
            f"font-size: 10px; color: {'#4ade80' if is_read else '#8b949e'};"
        )
        self.title_label.setStyleSheet(
            "font-weight: 600; font-size: 12px; color: "
            f"{'#9aa3ad' if is_read else '#ffffff'};"
        )

        for name in ("isRead", "favorite"):
            self.setProperty(name, False)
        self.setProperty("isRead", is_read)
        self.setProperty("favorite", favorite)
        self.style().unpolish(self)
        self.style().polish(self)

    # ------------------------------------------------------------------
    # Cover
    # ------------------------------------------------------------------
    def _load_cover(self):
        worker = CoverLoaderWorker(str(self.book_id), self.book_data["filepath"])
        worker.signals.finished.connect(self._on_cover_loaded)
        self.thread_pool.start(worker)

    def _on_cover_loaded(self, book_id: str, cover_path: str):
        if str(self.book_id) != book_id:
            return
        if cover_path and Path(cover_path).exists():
            pixmap = QPixmap(cover_path)
            if not pixmap.isNull():
                self.cover_label.setPixmap(
                    pixmap.scaled(
                        CARD_WIDTH - 12,
                        COVER_HEIGHT,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        self.cover_label.setText("No cover")

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def set_selected(self, selected: bool):
        if self._selected == selected:
            return
        self._selected = selected
        self.check_badge.setVisible(selected)
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_multi_selected(self, multi: bool):
        self._multi = bool(multi)

    @property
    def is_selected(self) -> bool:
        return self._selected

    @property
    def in_multi_selection(self) -> bool:
        return self._selected and self._multi

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.book_id, event.modifiers())
            event.accept()
            return
        super().mousePressEvent(event)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------
    def contextMenuEvent(self, event):
        # Let the window make this card the selection anchor when needed.
        self.context_opened.emit(self.book_id)

        if self._selected and self._multi:
            self.bulk_context_requested.emit(self.book_id)
            return

        menu = QMenu(self)

        details_action = QAction("Details && edit...", self)
        details_action.triggered.connect(lambda: self.details_requested.emit(self.book_id))
        menu.addAction(details_action)

        open_action = QAction("Open", self)
        open_action.triggered.connect(lambda: self.open_requested.emit(self.book_id))
        menu.addAction(open_action)

        open_with_menu = menu.addMenu("Open with")
        default_action = QAction("System default", self)
        default_action.triggered.connect(
            lambda: self.open_with_requested.emit(self.book_id, SYSTEM_READER_ID)
        )
        open_with_menu.addAction(default_action)
        open_with_menu.addSeparator()
        readers = reader_manager.available_readers()
        if readers:
            for reader in readers:
                if reader.is_system:
                    continue
                action = QAction(reader.name, self)
                action.triggered.connect(
                    lambda _checked=False, reader_id=reader.id: self.open_with_requested.emit(
                        self.book_id, reader_id
                    )
                )
                open_with_menu.addAction(action)
            open_with_menu.addSeparator()
            settings_action = QAction("Reader settings...", self)
            settings_action.triggered.connect(self._emit_settings_request)
            open_with_menu.addAction(settings_action)

        folder_action = QAction("Show in folder", self)
        folder_action.triggered.connect(
            lambda: self.open_folder_requested.emit(self.book_id)
        )
        menu.addAction(folder_action)

        menu.addSeparator()

        favorite_text = "Remove from favorites" if self.book_data.get("favorite") else "Add to favorites"
        favorite_action = QAction(favorite_text, self)
        favorite_action.triggered.connect(
            lambda: self.favorite_requested.emit(self.book_id)
        )
        menu.addAction(favorite_action)

        is_read = self.book_data.get("is_read", 0)
        toggle_action = QAction(
            "Mark as unread" if is_read else "Mark as read", self
        )
        toggle_action.triggered.connect(
            lambda: self.toggle_read_requested.emit(self.book_id)
        )
        menu.addAction(toggle_action)

        menu.addSeparator()

        edit_volume_action = QAction("Edit volume", self)
        edit_volume_action.triggered.connect(
            lambda: self.edit_volume_requested.emit(
                self.book_id, self.book_data.get("volume", "") or ""
            )
        )
        menu.addAction(edit_volume_action)

        change_series_action = QAction("Change series", self)
        change_series_action.triggered.connect(
            lambda: self.edit_series_requested.emit(self.book_id)
        )
        menu.addAction(change_series_action)

        set_cover_action = QAction("Set custom cover", self)
        set_cover_action.triggered.connect(
            lambda: self.set_custom_cover_requested.emit(self.book_id)
        )
        menu.addAction(set_cover_action)

        if self.book_data.get("custom_cover"):
            remove_cover_action = QAction("Remove custom cover", self)
            remove_cover_action.triggered.connect(
                lambda: self.remove_custom_cover_requested.emit(self.book_id)
            )
            menu.addAction(remove_cover_action)

        menu.addSeparator()
        delete_action = QAction("Delete from library...", self)
        delete_action.triggered.connect(
            lambda: self.delete_requested.emit(self.book_id)
        )
        menu.addAction(delete_action)

        menu.exec(event.globalPos())

    def _emit_settings_request(self):
        # The main window listens through a dedicated signal-less path; opening
        # settings from a card simply reuses the parent's action when available.
        window = self.window()
        if hasattr(window, "_show_reader_settings"):
            window._show_reader_settings()

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self.book_id)

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------
    def update_data(self, book_data: dict):
        self.book_data = book_data
        self.title_label.setText(self._display_title())
        self.info_label.setText(self._info_text())
        self._refresh_state()

        if "custom_cover" in book_data:
            self._load_cover()
