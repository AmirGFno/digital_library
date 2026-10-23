"""
Series panel widget for the sidebar.
"""
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QListWidget, QListWidgetItem, QMenu,
    QMessageBox
)
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtCore import Qt, pyqtSignal

from database import db
from utils.logger import logger


class SeriesPanel(QWidget):
    """Panel for displaying and managing series."""
    
    series_selected = pyqtSignal(object)  # series_id or None for all
    series_changed = pyqtSignal()  # Emitted when series are added/edited/deleted
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.refresh_series()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # Header with title and add button
        header_widget = QWidget()
        header_widget.setStyleSheet("""
            QWidget {
                background-color: #3a3a3a;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(8, 5, 8, 5)
        
        # Title
        title_label = QLabel("Series")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #ffffff;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Add button
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(28, 28)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a7;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #5b8;
            }
            QPushButton:pressed {
                background-color: #396;
            }
        """)
        self.add_btn.setToolTip("Add new series")
        self.add_btn.clicked.connect(self._add_series)
        header_layout.addWidget(self.add_btn)
        
        layout.addWidget(header_widget)
        
        # Series list container
        list_container = QWidget()
        list_container.setStyleSheet("""
            QWidget {
                background-color: #2a2a2a;
                border-radius: 5px;
            }
        """)
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(1, 1, 1, 1)
        
        # Series list
        self.series_list = QListWidget()
        self.series_list.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                outline: none;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #3a3a3a;
                color: #dddddd;
            }
            QListWidget::item:selected {
                background-color: #4a7;
                color: white;
            }
            QListWidget::item:hover:!selected {
                background-color: #3a3a3a;
            }
        """)
        self.series_list.itemClicked.connect(self._on_series_clicked)
        self.series_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.series_list.customContextMenuRequested.connect(self._show_context_menu)
        
        list_layout.addWidget(self.series_list)
        layout.addWidget(list_container, 1)
    
    def refresh_series(self):
        """Refresh the series list from database."""
        self.series_list.clear()
        
        # Add "All Books" option
        all_item = QListWidgetItem("All Books")
        all_item.setData(Qt.ItemDataRole.UserRole, None)
        self.series_list.addItem(all_item)
        
        # Add "Unsorted" option
        unsorted_count = len(db.get_books_without_series())
        unsorted_text = "Unsorted"
        if unsorted_count > 0:
            unsorted_text = f"Unsorted ({unsorted_count})"
        unsorted_item = QListWidgetItem(unsorted_text)
        unsorted_item.setData(Qt.ItemDataRole.UserRole, "unsorted")
        self.series_list.addItem(unsorted_item)
        
        # Add separator
        separator = QListWidgetItem("─" * 30)
        separator.setFlags(Qt.ItemFlag.NoItemFlags)
        separator.setForeground(Qt.GlobalColor.gray)
        self.series_list.addItem(separator)
        
        # Add series
        series_list = db.get_all_series_with_counts()
        for series in series_list:
            unread = series.get('unread_count', 0) or 0
            total = series.get('book_count', 0) or 0
            
            # Create item text
            text = series['name']
            if total > 0:
                text = f"{series['name']} ({unread}/{total})"
            
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, series['id'])
            
            # Highlight if has unread books
            if unread > 0:
                item.setForeground(Qt.GlobalColor.white)
            else:
                item.setForeground(Qt.GlobalColor.lightGray)
            
            self.series_list.addItem(item)
        
        # Select "All Books" by default
        self.series_list.setCurrentRow(0)
    
    def _on_series_clicked(self, item: QListWidgetItem):
        """Handle series item click."""
        series_id = item.data(Qt.ItemDataRole.UserRole)
        if series_id != "unsorted" and item.flags() != Qt.ItemFlag.NoItemFlags:
            self.series_selected.emit(series_id)
    
    def _add_series(self):
        """Add a new series."""
        from ui.dialogs import AddSeriesDialog
        dialog = AddSeriesDialog(self)
        if dialog.exec():
            self.refresh_series()
            self.series_changed.emit()
            QMessageBox.information(
                self, "Success", 
                "Series added successfully!"
            )
    
    def _show_context_menu(self, pos):
        """Show context menu for series item."""
        item = self.series_list.itemAt(pos)
        if not item:
            return
        
        series_id = item.data(Qt.ItemDataRole.UserRole)
        if series_id is None or series_id == "unsorted":
            return
        
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
        
        # Edit action
        edit_action = QAction("Edit", self)
        edit_action.triggered.connect(lambda: self._edit_series(series_id))
        menu.addAction(edit_action)
        
        # Delete action
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(lambda: self._delete_series(series_id))
        menu.addAction(delete_action)
        
        menu.exec(self.series_list.mapToGlobal(pos))
    
    def _edit_series(self, series_id: int):
        """Edit a series."""
        from ui.dialogs import EditSeriesDialog
        series = db.get_series(series_id)
        if series:
            dialog = EditSeriesDialog(series_id, series['name'], self)
            if dialog.exec():
                self.refresh_series()
                self.series_changed.emit()
    
    def _delete_series(self, series_id: int):
        """Delete a series."""
        from ui.dialogs import ConfirmDialog
        series = db.get_series(series_id)
        if not series:
            return
        
        dialog = ConfirmDialog(
            "Delete Series",
            f"Are you sure you want to delete '{series['name']}'?\n"
            "Books in this series will become unsorted.",
            parent=self
        )
        
        if dialog.exec():
            db.delete_series(series_id)
            self.refresh_series()
            self.series_changed.emit()