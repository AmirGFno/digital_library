"""
Main window of the Digital Library application.
"""
import os
from typing import Optional, List
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QGridLayout, QMenuBar, QMenu, QMessageBox,
    QLabel, QStatusBar, QSpinBox, QToolBar, QLineEdit,
    QComboBox, QSplitter, QFrame, QDialog, QVBoxLayout as QVBox,
    QHBoxLayout as QHBox
)
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtCore import Qt, QSize

from database import db
from cover_extractor import cover_extractor
from config import DEFAULT_COLUMNS, CARD_WIDTH, CARD_HEIGHT
from utils.logger import logger
from utils.helpers import open_file_with_default_app
from utils.settings import settings
from ui.book_card import BookCard
from ui.series_panel import SeriesPanel
from ui.dialogs import (
    AddBookDialog, EditVolumeDialog, ConfirmDialog, 
    BulkImportDialog, AddSeriesDialog, SetCustomCoverDialog,
    ReaderSettingsDialog
)


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.current_series_filter: Optional[int] = None
        self.current_search: str = ""
        self.columns = DEFAULT_COLUMNS
        self.book_cards: List[BookCard] = []
        
        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._apply_theme()
        
        # Load initial data
        self.refresh_books()
    
    def _setup_ui(self):
        self.setWindowTitle("Digital Library")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout with splitter
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Series panel (sidebar)
        self.series_panel = SeriesPanel()
        self.series_panel.setMinimumWidth(200)
        self.series_panel.setMaximumWidth(300)
        self.series_panel.series_selected.connect(self._on_series_selected)
        self.series_panel.series_changed.connect(self.refresh_books)
        splitter.addWidget(self.series_panel)
        
        # Books area
        books_container = QWidget()
        books_layout = QVBoxLayout(books_container)
        books_layout.setContentsMargins(10, 10, 10, 10)
        
        # Scroll area for books grid
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        # Grid container
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        
        scroll_area.setWidget(self.grid_container)
        books_layout.addWidget(scroll_area)
        
        splitter.addWidget(books_container)
        splitter.setSizes([220, 980])
    
    def _setup_menu(self):
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        add_action = QAction("Add Book...", self)
        add_action.setShortcut(QKeySequence("Ctrl+O"))
        add_action.triggered.connect(self._add_book)
        file_menu.addAction(add_action)
        
        bulk_action = QAction("Bulk Import...", self)
        bulk_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        bulk_action.triggered.connect(self._bulk_import)
        file_menu.addAction(bulk_action)
        
        file_menu.addSeparator()
        
        reader_action = QAction("Reader Settings...", self)
        reader_action.triggered.connect(self._show_reader_settings)
        file_menu.addAction(reader_action)
        
        file_menu.addSeparator()
        
        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self.refresh_books)
        file_menu.addAction(refresh_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Series menu
        series_menu = menubar.addMenu("Series")
        
        add_series_action = QAction("Add Series...", self)
        add_series_action.triggered.connect(self._add_series)
        series_menu.addAction(add_series_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        clear_cache_action = QAction("Clear Cover Cache", self)
        clear_cache_action.triggered.connect(self._clear_cache)
        view_menu.addAction(clear_cache_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)
        
        # Search box
        search_label = QLabel("Search: ")
        toolbar.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search books...")
        self.search_input.setMaximumWidth(250)
        self.search_input.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.search_input)
        
        toolbar.addSeparator()
        
        # Columns spinner
        columns_label = QLabel("Columns: ")
        toolbar.addWidget(columns_label)
        
        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(2, 10)
        self.columns_spin.setValue(self.columns)
        self.columns_spin.valueChanged.connect(self._on_columns_changed)
        toolbar.addWidget(self.columns_spin)
        
        toolbar.addSeparator()
        
        # Filter combo
        filter_label = QLabel("Filter: ")
        toolbar.addWidget(filter_label)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("All", "all")
        self.filter_combo.addItem("Unread", "unread")
        self.filter_combo.addItem("Read", "read")
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.filter_combo)
    
    def _setup_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self._update_statusbar()
    
    def _apply_theme(self):
        """Apply dark theme to the application."""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QMenuBar {
                background-color: #3a3a3a;
                padding: 5px;
            }
            QMenuBar::item:selected {
                background-color: #4a7;
            }
            QMenu {
                background-color: #3a3a3a;
                border: 1px solid #555;
            }
            QMenu::item:selected {
                background-color: #4a7;
            }
            QToolBar {
                background-color: #3a3a3a;
                border: none;
                padding: 5px;
                spacing: 5px;
            }
            QLineEdit {
                background-color: #2a2a2a;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px;
                color: white;
            }
            QLineEdit:focus {
                border: 1px solid #4a7;
            }
            QSpinBox, QComboBox {
                background-color: #2a2a2a;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px;
                color: white;
            }
            QPushButton {
                background-color: #4a4a4a;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px 15px;
                color: white;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QPushButton:pressed {
                background-color: #4a7;
            }
            QScrollBar:vertical {
                background-color: #2a2a2a;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666;
            }
            QStatusBar {
                background-color: #3a3a3a;
            }
            QSplitter::handle {
                background-color: #444;
            }
        """)
    
    def refresh_books(self):
        """Refresh the books grid."""
        # Clear existing cards
        for card in self.book_cards:
            card.deleteLater()
        self.book_cards.clear()
        
        # Clear grid layout
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Get books based on current filter
        if self.current_search:
            books = db.search_books(self.current_search)
        elif self.current_series_filter == "unsorted":
            books = db.get_books_without_series()
        elif self.current_series_filter is not None:
            books = db.get_all_books(series_id=self.current_series_filter)
        else:
            books = db.get_all_books()
        
        # Apply read filter
        read_filter = self.filter_combo.currentData()
        if read_filter == "unread":
            books = [b for b in books if not b.get('is_read')]
        elif read_filter == "read":
            books = [b for b in books if b.get('is_read')]
        
        # Create cards
        for i, book in enumerate(books):
            card = BookCard(book)
            card.open_requested.connect(self._open_book)
            card.toggle_read_requested.connect(self._toggle_read)
            card.edit_volume_requested.connect(self._edit_volume)
            card.delete_requested.connect(self._delete_book)
            card.edit_series_requested.connect(self._change_series)
            card.set_custom_cover_requested.connect(self._set_custom_cover)
            card.remove_custom_cover_requested.connect(self._remove_custom_cover)
            
            row = i // self.columns
            col = i % self.columns
            self.grid_layout.addWidget(card, row, col)
            self.book_cards.append(card)
        
        self._update_statusbar()
    
    def _update_statusbar(self):
        """Update status bar with current stats."""
        total = db.get_total_book_count()
        unread = db.get_total_unread_count()
        self.statusbar.showMessage(
            f"Total: {total} books | Unread: {unread} | "
            f"Showing: {len(self.book_cards)} books"
        )
    
    def _on_series_selected(self, series_id):
        """Handle series selection from sidebar."""
        self.current_series_filter = series_id
        self.refresh_books()
    
    def _on_search_changed(self, text: str):
        """Handle search text change."""
        self.current_search = text.strip()
        self.refresh_books()
    
    def _on_columns_changed(self, value: int):
        """Handle columns spinner change."""
        self.columns = value
        self.refresh_books()
    
    def _on_filter_changed(self):
        """Handle read filter change."""
        self.refresh_books()
    
    def _add_book(self):
        """Show add book dialog."""
        dialog = AddBookDialog(self)
        if dialog.exec():
            self.refresh_books()
            self.series_panel.refresh_series()
    
    def _bulk_import(self):
        """Show bulk import dialog."""
        dialog = BulkImportDialog(self)
        if dialog.exec():
            self.refresh_books()
            self.series_panel.refresh_series()
    
    def _add_series(self):
        """Show add series dialog."""
        dialog = AddSeriesDialog(self)
        if dialog.exec():
            self.series_panel.refresh_series()
    
    def _show_reader_settings(self):
        """Show reader settings dialog."""
        dialog = ReaderSettingsDialog(self)
        dialog.exec()
    
    def _open_book(self, book_id: int):
        """Open a book with system default application."""
        book = db.get_book(book_id)
        if book:
            filepath = book['filepath']
            if os.path.exists(filepath):
                if open_file_with_default_app(filepath):
                    logger.info(f"Opened book: {filepath}")
                else:
                    QMessageBox.warning(
                        self, "Error", 
                        "Failed to open the file."
                    )
            else:
                QMessageBox.warning(
                    self, "File Not Found",
                    f"The file no longer exists:\n{filepath}"
                )
    
    def _toggle_read(self, book_id: int):
        """Toggle read status of a book."""
        new_status = db.toggle_book_read(book_id)
        if new_status is not None:
            self.refresh_books()
            self.series_panel.refresh_series()
    
    def _edit_volume(self, book_id: int, current_volume: str):
        """Edit volume of a book."""
        dialog = EditVolumeDialog(current_volume, self)
        if dialog.exec():
            new_volume = dialog.get_volume()
            db.update_book(book_id, volume=new_volume)
            self.refresh_books()
    
    def _change_series(self, book_id: int):
        """Change series of a book."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Change Series")
        dialog.setMinimumWidth(300)
        
        layout = QVBoxLayout(dialog)
        
        combo = QComboBox()
        combo.addItem("None (Unsorted)", None)
        for series in db.get_all_series():
            combo.addItem(series['name'], series['id'])
        
        # Select current series
        book = db.get_book(book_id)
        if book and book.get('series_id'):
            for i in range(combo.count()):
                if combo.itemData(i) == book['series_id']:
                    combo.setCurrentIndex(i)
                    break
        
        layout.addWidget(combo)
        
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(dialog.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
        
        if dialog.exec():
            new_series_id = combo.currentData()
            db.update_book(book_id, series_id=new_series_id)
            self.refresh_books()
            self.series_panel.refresh_series()
    
    def _set_custom_cover(self, book_id: int):
        """Show dialog to set custom cover."""
        book = db.get_book(book_id)
        if not book:
            return
        
        dialog = SetCustomCoverDialog(book_id, book.get('title', 'Untitled'), self)
        if dialog.exec():
            # Refresh card
            self.refresh_books()
    
    def _remove_custom_cover(self, book_id: int):
        """Remove custom cover from book."""
        dialog = ConfirmDialog(
            "Remove Custom Cover",
            "Are you sure you want to remove the custom cover?",
            parent=self
        )
        
        if dialog.exec():
            # Delete physical file
            book = db.get_book(book_id)
            if book and book.get('custom_cover'):
                cover_path = book['custom_cover']
                if os.path.exists(cover_path):
                    try:
                        os.remove(cover_path)
                    except Exception as e:
                        logger.error(f"Failed to delete custom cover file: {e}")
            
            # Remove from database
            db.remove_custom_cover(book_id)
            
            # Refresh
            self.refresh_books()
            
            QMessageBox.information(
                self, "Success", 
                "Custom cover removed successfully!"
            )
    
    def _delete_book(self, book_id: int):
        """Delete a book."""
        book = db.get_book(book_id)
        if not book:
            return
        
        dialog = ConfirmDialog(
            "Delete Book",
            f"Are you sure you want to delete this book?\n\n"
            f"File: {Path(book['filepath']).name}",
            checkbox_text="Also delete the file from disk",
            parent=self
        )
        
        if dialog.exec():
            # Clear cover cache
            cover_extractor.clear_cache(book['filepath'])
            
            # Delete custom cover file if exists
            if book.get('custom_cover'):
                try:
                    if os.path.exists(book['custom_cover']):
                        os.remove(book['custom_cover'])
                except Exception as e:
                    logger.error(f"Failed to delete custom cover: {e}")
            
            # Delete file if requested
            if dialog.is_checkbox_checked():
                try:
                    if os.path.exists(book['filepath']):
                        os.remove(book['filepath'])
                        logger.info(f"Deleted file: {book['filepath']}")
                except Exception as e:
                    logger.error(f"Failed to delete file: {e}")
                    QMessageBox.warning(
                        self, "Error",
                        f"Failed to delete file: {e}"
                    )
            
            # Delete from database
            db.delete_book(book_id)
            self.refresh_books()
            self.series_panel.refresh_series()
    
    def _clear_cache(self):
        """Clear cover cache."""
        dialog = ConfirmDialog(
            "Clear Cache",
            "Are you sure you want to clear all cached cover images?\n"
            "They will be regenerated when needed.",
            parent=self
        )
        
        if dialog.exec():
            cover_extractor.clear_cache()
            self.refresh_books()
            QMessageBox.information(
                self, "Cache Cleared",
                "Cover cache has been cleared."
            )
    
    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Digital Library",
            "<h2>Digital Library</h2>"
            "<p>Version 2.0</p>"
            "<p>A desktop application for managing your digital book collection.</p>"
            "<p>Supports PDF, images, and archive formats (CBZ, CBR, 7z, etc.)</p>"
            "<hr>"
            "<p>Features:</p>"
            "<ul>"
            "<li>Custom cover images</li>"
            "<li>Custom reader application</li>"
            "<li>Natural sorting of volume numbers</li>"
            "<li>RAR/CBR support with cover extraction</li>"
            "</ul>"
            "<p>Built with Python and PyQt6</p>"
        )