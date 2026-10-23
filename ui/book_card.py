"""
Book card widget for displaying individual books in the grid.
"""
from typing import Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QMenu, QFrame
)
from PyQt6.QtGui import QPixmap, QAction, QMouseEvent
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRunnable, QThreadPool, QObject

from config import CARD_WIDTH, CARD_HEIGHT, COVER_HEIGHT
from cover_extractor import cover_extractor
from database import db
from utils.logger import logger


class CoverLoaderSignals(QObject):
    """Signals for the cover loader worker."""
    finished = pyqtSignal(str, str)  # book_id, cover_path


class CoverLoaderWorker(QRunnable):
    """Worker to load covers in background thread."""
    
    def __init__(self, book_id: str, filepath: str):
        super().__init__()
        self.book_id = book_id
        self.filepath = filepath
        self.signals = CoverLoaderSignals()
    
    def run(self):
        try:
            # First check for custom cover
            custom_cover = db.get_custom_cover(int(self.book_id))
            
            if custom_cover and Path(custom_cover).exists():
                self.signals.finished.emit(self.book_id, custom_cover)
                return
            
            # Otherwise use extractor
            cover_path = cover_extractor.get_cover(self.filepath, int(self.book_id))
            self.signals.finished.emit(self.book_id, cover_path or "")
        except Exception as e:
            logger.error(f"Cover loading error for {self.filepath}: {e}")
            self.signals.finished.emit(self.book_id, "")


class BookCard(QFrame):
    """Widget representing a single book card."""
    
    # Signals
    open_requested = pyqtSignal(int)  # book_id
    toggle_read_requested = pyqtSignal(int)  # book_id
    edit_volume_requested = pyqtSignal(int, str)  # book_id, current_volume
    delete_requested = pyqtSignal(int)  # book_id
    edit_series_requested = pyqtSignal(int)  # book_id
    set_custom_cover_requested = pyqtSignal(int)  # book_id
    remove_custom_cover_requested = pyqtSignal(int)  # book_id
    
    # Thread pool for cover loading
    thread_pool = QThreadPool()
    
    def __init__(self, book_data: dict, parent=None):
        super().__init__(parent)
        self.book_data = book_data
        self.book_id = book_data['id']
        self._setup_ui()
        self._load_cover()
    
    def _setup_ui(self):
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Apply styling
        self._apply_style()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)
        
        # Cover image
        self.cover_label = QLabel()
        self.cover_label.setFixedHeight(COVER_HEIGHT)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("""
            background-color: #2a2a2a;
            border-radius: 4px;
        """)
        self.cover_label.setText("Loading...")
        layout.addWidget(self.cover_label)
        
        # Title
        title = self.book_data.get('title') or Path(self.book_data['filepath']).stem
        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(40)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(self.title_label)
        
        # Info line (volume + read status)
        info_parts = []
        if self.book_data.get('volume'):
            info_parts.append(f"Vol. {self.book_data['volume']}")
        if self.book_data.get('series_name'):
            info_parts.append(self.book_data['series_name'][:20])
        
        self.info_label = QLabel(" | ".join(info_parts) if info_parts else "")
        self.info_label.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(self.info_label)
        
        # Read status indicator
        self._update_read_indicator()
    
    def _apply_style(self):
        is_read = self.book_data.get('is_read', 0)
        has_custom_cover = bool(self.book_data.get('custom_cover'))
        
        base_style = """
            BookCard {
                background-color: #3a3a3a;
                border-radius: 8px;
                border: 2px solid %s;
            }
            BookCard:hover {
                background-color: #454545;
                border: 2px solid #5a9;
            }
        """
        
        if has_custom_cover:
            border_color = "#a85"  # Orange for custom cover
        elif is_read:
            border_color = "#5a5"  # Green for read
        else:
            border_color = "#555"  # Gray for unread
        
        self.setStyleSheet(base_style % border_color)
    
    def _update_read_indicator(self):
        is_read = self.book_data.get('is_read', 0)
        if is_read:
            self.title_label.setStyleSheet(
                "font-weight: bold; font-size: 11px; color: #8f8;"
            )
        else:
            self.title_label.setStyleSheet(
                "font-weight: bold; font-size: 11px; color: #fff;"
            )
    
    def _load_cover(self):
        """Start loading cover in background thread."""
        worker = CoverLoaderWorker(str(self.book_id), self.book_data['filepath'])
        worker.signals.finished.connect(self._on_cover_loaded)
        self.thread_pool.start(worker)
    
    def _on_cover_loaded(self, book_id: str, cover_path: str):
        """Handle cover loaded from worker thread."""
        if str(self.book_id) != book_id:
            return
        
        if cover_path and Path(cover_path).exists():
            pixmap = QPixmap(cover_path)
            scaled = pixmap.scaled(
                CARD_WIDTH - 10, COVER_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.cover_label.setPixmap(scaled)
        else:
            self.cover_label.setText("No Cover")
    
    def contextMenuEvent(self, event):
        """Show context menu on right-click."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #555;
            }
            QMenu::item:selected {
                background-color: #5a9;
            }
        """)
        
        # Open action
        open_action = QAction("Open", self)
        open_action.triggered.connect(lambda: self.open_requested.emit(self.book_id))
        menu.addAction(open_action)
        
        menu.addSeparator()
        
        # Toggle read action
        is_read = self.book_data.get('is_read', 0)
        read_text = "Mark as Unread" if is_read else "Mark as Read"
        toggle_action = QAction(read_text, self)
        toggle_action.triggered.connect(
            lambda: self.toggle_read_requested.emit(self.book_id)
        )
        menu.addAction(toggle_action)
        
        # Edit volume
        edit_vol_action = QAction("Edit Volume", self)
        edit_vol_action.triggered.connect(
            lambda: self.edit_volume_requested.emit(
                self.book_id, 
                self.book_data.get('volume', '') or ''
            )
        )
        menu.addAction(edit_vol_action)
        
        # Edit series
        edit_series_action = QAction("Change Series", self)
        edit_series_action.triggered.connect(
            lambda: self.edit_series_requested.emit(self.book_id)
        )
        menu.addAction(edit_series_action)
        
        menu.addSeparator()
        
        # Custom cover actions
        set_cover_action = QAction("Set Custom Cover", self)
        set_cover_action.triggered.connect(
            lambda: self.set_custom_cover_requested.emit(self.book_id)
        )
        menu.addAction(set_cover_action)
        
        if self.book_data.get('custom_cover'):
            remove_cover_action = QAction("Remove Custom Cover", self)
            remove_cover_action.triggered.connect(
                lambda: self.remove_custom_cover_requested.emit(self.book_id)
            )
            menu.addAction(remove_cover_action)
        
        menu.addSeparator()
        
        # Delete action
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(
            lambda: self.delete_requested.emit(self.book_id)
        )
        menu.addAction(delete_action)
        
        menu.exec(event.globalPos())
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Open book on double-click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self.book_id)
    
    def update_data(self, book_data: dict):
        """Update card with new data."""
        self.book_data = book_data
        
        # Update title
        title = book_data.get('title') or Path(book_data['filepath']).stem
        self.title_label.setText(title)
        
        # Update info
        info_parts = []
        if book_data.get('volume'):
            info_parts.append(f"Vol. {book_data['volume']}")
        if book_data.get('series_name'):
            info_parts.append(book_data['series_name'][:20])
        self.info_label.setText(" | ".join(info_parts) if info_parts else "")
        
        # Update styling
        self._apply_style()
        self._update_read_indicator()
        
        # Reload cover if custom cover changed
        if 'custom_cover' in book_data:
            self._load_cover()