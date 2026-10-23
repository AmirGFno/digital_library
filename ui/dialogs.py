"""
Dialog windows for the application.
"""
from typing import Optional, List
from pathlib import Path
import os
import subprocess

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QComboBox, QFileDialog,
    QMessageBox, QListWidget, QListWidgetItem, QCheckBox,
    QRadioButton, QGroupBox, QTextEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QIcon

from config import ALL_EXTENSIONS
from database import db
from utils.settings import settings


class AddBookDialog(QDialog):
    """Dialog for adding a new book."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Book")
        self.setMinimumWidth(500)
        self.filepaths: List[str] = []
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # File selection
        file_layout = QHBoxLayout()
        self.file_label = QLabel("No file selected")
        self.file_label.setWordWrap(True)
        file_btn = QPushButton("Browse...")
        file_btn.clicked.connect(self._browse_files)
        file_layout.addWidget(self.file_label, 1)
        file_layout.addWidget(file_btn)
        layout.addLayout(file_layout)
        
        # Title
        layout.addWidget(QLabel("Title (optional):"))
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Leave empty to use filename")
        layout.addWidget(self.title_input)
        
        # Series
        layout.addWidget(QLabel("Series:"))
        self.series_combo = QComboBox()
        self.series_combo.addItem("None", None)
        for series in db.get_all_series():
            self.series_combo.addItem(series['name'], series['id'])
        layout.addWidget(self.series_combo)
        
        # Volume
        layout.addWidget(QLabel("Volume:"))
        self.volume_input = QLineEdit()
        self.volume_input.setPlaceholderText("e.g., 1, 2, Special")
        layout.addWidget(self.volume_input)
        
        # Buttons
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_book)
        add_btn.setDefault(True)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(add_btn)
        layout.addLayout(btn_layout)
    
    def _browse_files(self):
        extensions = " ".join(f"*{ext}" for ext in ALL_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Books", "",
            f"Book Files ({extensions});;All Files (*)"
        )
        if files:
            self.filepaths = files
            if len(files) == 1:
                self.file_label.setText(files[0])
            else:
                self.file_label.setText(f"{len(files)} files selected")
    
    def _add_book(self):
        if not self.filepaths:
            QMessageBox.warning(self, "Error", "Please select at least one file.")
            return
        
        series_id = self.series_combo.currentData()
        volume = self.volume_input.text().strip() or None
        title = self.title_input.text().strip() or None
        
        success = 0
        skipped = 0
        
        for filepath in self.filepaths:
            book_title = title if len(self.filepaths) == 1 else None
            if db.add_book(filepath, book_title, series_id, volume):
                success += 1
            else:
                skipped += 1
        
        if skipped > 0:
            QMessageBox.information(
                self, "Import Complete",
                f"Added: {success}, Skipped (duplicates): {skipped}"
            )
        
        self.accept()


class EditVolumeDialog(QDialog):
    """Dialog for editing book volume."""
    
    def __init__(self, current_volume: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Volume")
        self.setMinimumWidth(300)
        self._setup_ui(current_volume)
    
    def _setup_ui(self, current_volume: Optional[str]):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Volume:"))
        self.volume_input = QLineEdit()
        self.volume_input.setText(current_volume or "")
        self.volume_input.setPlaceholderText("e.g., 1, 2, Special")
        self.volume_input.selectAll()
        layout.addWidget(self.volume_input)
        
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        save_btn.setDefault(True)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
    
    def get_volume(self) -> Optional[str]:
        return self.volume_input.text().strip() or None


class AddSeriesDialog(QDialog):
    """Dialog for adding a new series."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Series")
        self.setMinimumWidth(350)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Series Name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter series name")
        layout.addWidget(self.name_input)
        
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_series)
        add_btn.setDefault(True)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(add_btn)
        layout.addLayout(btn_layout)
    
    def _add_series(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Please enter a series name.")
            return
        
        if db.create_series(name):
            self.accept()
        else:
            QMessageBox.warning(self, "Error", "Series already exists.")


class EditSeriesDialog(QDialog):
    """Dialog for editing a series name."""
    
    def __init__(self, series_id: int, current_name: str, parent=None):
        super().__init__(parent)
        self.series_id = series_id
        self.setWindowTitle("Edit Series")
        self.setMinimumWidth(350)
        self._setup_ui(current_name)
    
    def _setup_ui(self, current_name: str):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Series Name:"))
        self.name_input = QLineEdit()
        self.name_input.setText(current_name)
        self.name_input.selectAll()
        layout.addWidget(self.name_input)
        
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_series)
        save_btn.setDefault(True)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
    
    def _save_series(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Please enter a series name.")
            return
        
        if db.update_series(self.series_id, name):
            self.accept()
        else:
            QMessageBox.warning(self, "Error", "Failed to update series. Name may already exist.")


class ConfirmDialog(QDialog):
    """Confirmation dialog with optional checkbox."""
    
    def __init__(self, title: str, message: str, 
                 checkbox_text: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(350)
        self._setup_ui(message, checkbox_text)
    
    def _setup_ui(self, message: str, checkbox_text: Optional[str]):
        layout = QVBoxLayout(self)
        
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        layout.addWidget(msg_label)
        
        self.checkbox = None
        if checkbox_text:
            self.checkbox = QCheckBox(checkbox_text)
            layout.addWidget(self.checkbox)
        
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = QPushButton("Confirm")
        confirm_btn.clicked.connect(self.accept)
        confirm_btn.setDefault(True)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(confirm_btn)
        layout.addLayout(btn_layout)
    
    def is_checkbox_checked(self) -> bool:
        return self.checkbox.isChecked() if self.checkbox else False


class BulkImportDialog(QDialog):
    """Dialog for bulk importing books from a folder."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bulk Import")
        self.setMinimumSize(600, 400)
        self.folder_path: Optional[str] = None
        self.files: List[str] = []
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Folder selection
        folder_layout = QHBoxLayout()
        self.folder_label = QLabel("No folder selected")
        folder_btn = QPushButton("Browse Folder...")
        folder_btn.clicked.connect(self._browse_folder)
        folder_layout.addWidget(self.folder_label, 1)
        folder_layout.addWidget(folder_btn)
        layout.addLayout(folder_layout)
        
        # Recursive option
        self.recursive_check = QCheckBox("Include subfolders")
        self.recursive_check.setChecked(True)
        self.recursive_check.stateChanged.connect(self._scan_folder)
        layout.addWidget(self.recursive_check)
        
        # Files list
        layout.addWidget(QLabel("Files found:"))
        self.files_list = QListWidget()
        layout.addWidget(self.files_list)
        
        # Series selection
        series_layout = QHBoxLayout()
        series_layout.addWidget(QLabel("Assign to series:"))
        self.series_combo = QComboBox()
        self.series_combo.addItem("None", None)
        for series in db.get_all_series():
            self.series_combo.addItem(series['name'], series['id'])
        series_layout.addWidget(self.series_combo, 1)
        layout.addLayout(series_layout)
        
        # Buttons
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        import_btn = QPushButton("Import")
        import_btn.clicked.connect(self._import_books)
        import_btn.setDefault(True)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(import_btn)
        layout.addLayout(btn_layout)
    
    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.folder_path = folder
            self.folder_label.setText(folder)
            self._scan_folder()
    
    def _scan_folder(self):
        if not self.folder_path:
            return
        
        self.files.clear()
        self.files_list.clear()
        
        folder = Path(self.folder_path)
        pattern = "**/*" if self.recursive_check.isChecked() else "*"
        
        for ext in ALL_EXTENSIONS:
            for file_path in folder.glob(f"{pattern}{ext}"):
                if file_path.is_file():
                    self.files.append(str(file_path))
                    self.files_list.addItem(file_path.name)
        
        self.files_list.sortItems()
    
    def _import_books(self):
        if not self.files:
            QMessageBox.warning(self, "Error", "No files to import.")
            return
        
        series_id = self.series_combo.currentData()
        
        books = [
            {'filepath': f, 'series_id': series_id}
            for f in self.files
        ]
        
        success, skipped = db.bulk_add_books(books)
        
        QMessageBox.information(
            self, "Import Complete",
            f"Added: {success}\nSkipped (duplicates): {skipped}"
        )
        
        self.accept()


class SetCustomCoverDialog(QDialog):
    """Dialog for setting a custom cover image."""
    
    def __init__(self, book_id: int, book_title: str, parent=None):
        super().__init__(parent)
        self.book_id = book_id
        self.setWindowTitle(f"Set Custom Cover - {book_title}")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.selected_image = None
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel("Select Custom Cover Image")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)
        
        layout.addSpacing(10)
        
        # Image preview
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(200)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                border: 2px dashed #555;
                border-radius: 5px;
            }
        """)
        self.preview_label.setText("No image selected")
        layout.addWidget(self.preview_label)
        
        # Image info
        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(self.info_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        browse_btn = QPushButton("Browse Image...")
        browse_btn.clicked.connect(self._browse_image)
        btn_layout.addWidget(browse_btn)
        
        clear_btn = QPushButton("Clear Preview")
        clear_btn.clicked.connect(self._clear_preview)
        btn_layout.addWidget(clear_btn)
        
        layout.addLayout(btn_layout)
        
        layout.addSpacing(20)
        
        # Action buttons
        action_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        action_layout.addWidget(cancel_btn)
        
        action_layout.addStretch()
        
        self.set_btn = QPushButton("Set as Cover")
        self.set_btn.clicked.connect(self._set_cover)
        self.set_btn.setDefault(True)
        self.set_btn.setEnabled(False)
        action_layout.addWidget(self.set_btn)
        
        layout.addLayout(action_layout)
    
    def _browse_image(self):
        """Browse for image file."""
        # Image filters
        filters = "Image files (*.jpg *.jpeg *.png *.gif *.webp *.bmp);;All files (*.*)"
        
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Cover Image", "", filters
        )
        
        if filepath:
            self.selected_image = filepath
            self._update_preview(filepath)
    
    def _update_preview(self, filepath: str):
        """Update image preview."""
        try:
            # Load image
            pixmap = QPixmap(filepath)
            if pixmap.isNull():
                QMessageBox.warning(self, "Error", "Cannot load image file.")
                return
            
            # Display info
            file_size = os.path.getsize(filepath)
            from utils.helpers import format_file_size
            size_str = format_file_size(file_size)
            info = f"{pixmap.width()} × {pixmap.height()} | {size_str} | {Path(filepath).name}"
            self.info_label.setText(info)
            
            # Show preview
            scaled = pixmap.scaled(
                self.preview_label.width() - 20,
                self.preview_label.height() - 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled)
            self.set_btn.setEnabled(True)
        
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Cannot load image: {e}")
    
    def _clear_preview(self):
        """Clear image preview."""
        self.selected_image = None
        self.preview_label.clear()
        self.preview_label.setText("No image selected")
        self.info_label.clear()
        self.set_btn.setEnabled(False)
    
    def _set_cover(self):
        """Set the selected image as custom cover."""
        if not self.selected_image:
            return
        
        from config import CUSTOM_COVERS_DIR
        import shutil
        
        try:
            # Create new filename
            ext = Path(self.selected_image).suffix.lower()
            new_filename = f"book_{self.book_id}_cover{ext}"
            new_path = CUSTOM_COVERS_DIR / new_filename
            
            # Copy image
            shutil.copy2(self.selected_image, new_path)
            
            # Save to database
            if db.set_custom_cover(self.book_id, str(new_path)):
                QMessageBox.information(
                    self, "Success", 
                    "Custom cover set successfully!"
                )
                self.accept()
            else:
                QMessageBox.warning(
                    self, "Error", 
                    "Failed to set custom cover."
                )
        
        except Exception as e:
            QMessageBox.critical(
                self, "Error", 
                f"Failed to set custom cover: {str(e)}"
            )


class ReaderSettingsDialog(QDialog):
    """Dialog for configuring custom reader application."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reader Settings")
        self.setMinimumWidth(500)
        self._setup_ui()
        self._load_settings()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel("Configure Reader Application")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)
        
        layout.addSpacing(10)
        
        # Reader selection group
        selection_group = QGroupBox("Reader Selection")
        selection_layout = QVBoxLayout(selection_group)
        
        # System default radio
        self.system_radio = QRadioButton("Use system default application")
        self.system_radio.toggled.connect(self._on_selection_changed)
        selection_layout.addWidget(self.system_radio)
        
        # Custom reader radio
        self.custom_radio = QRadioButton("Use custom reader application")
        self.custom_radio.toggled.connect(self._on_selection_changed)
        selection_layout.addWidget(self.custom_radio)
        
        layout.addWidget(selection_group)
        
        # Custom reader settings (initially disabled)
        self.custom_group = QGroupBox("Custom Reader Settings")
        self.custom_group.setEnabled(False)
        custom_layout = QVBoxLayout(self.custom_group)
        
        # Path selection
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Reader path:"))
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Select .exe file...")
        path_layout.addWidget(self.path_input, 1)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_exe)
        path_layout.addWidget(browse_btn)
        custom_layout.addLayout(path_layout)
        
        # Reader name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Reader name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., CDisplayEx, SumatraPDF, etc.")
        name_layout.addWidget(self.name_input, 1)
        custom_layout.addLayout(name_layout)
        
        # Test button
        test_btn = QPushButton("Test Reader")
        test_btn.clicked.connect(self._test_reader)
        custom_layout.addWidget(test_btn)
        
        layout.addWidget(self.custom_group)
        
        # Info text
        info_label = QLabel(
            "Note: Custom reader will be used for opening all book files. "
            "Make sure the selected application supports the file formats you use."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(info_label)
        
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save_settings)
        save_btn.setDefault(True)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
    
    def _load_settings(self):
        """Load current settings."""
        reader_settings = settings.get_reader_settings()
        
        if reader_settings.get('use_system_default', False):
            self.system_radio.setChecked(True)
            self.custom_group.setEnabled(False)
        else:
            self.custom_radio.setChecked(True)
            self.custom_group.setEnabled(True)
        
        self.path_input.setText(reader_settings.get('path', ''))
        self.name_input.setText(reader_settings.get('name', ''))
    
    def _on_selection_changed(self):
        """Handle radio button selection change."""
        self.custom_group.setEnabled(self.custom_radio.isChecked())
    
    def _browse_exe(self):
        """Browse for executable file."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Reader Application", "",
            "Executable files (*.exe);;All files (*.*)"
        )
        if filepath:
            self.path_input.setText(filepath)
            
            # Auto-fill name from filename
            if not self.name_input.text():
                name = Path(filepath).stem
                self.name_input.setText(name)
    
    def _test_reader(self):
        """Test the selected reader."""
        path = self.path_input.text().strip()
        
        if not path:
            QMessageBox.warning(self, "Error", "Please select a reader application first.")
            return
        
        if not os.path.exists(path):
            QMessageBox.warning(self, "Error", f"File not found:\n{path}")
            return
        
        try:
            # Try to run the application without arguments
            subprocess.Popen([path], shell=True)
            QMessageBox.information(
                self, "Success", 
                f"Reader application started successfully!\n\n"
                f"Application: {Path(path).name}"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Error", 
                f"Failed to start reader application:\n{str(e)}"
            )
    
    def _save_settings(self):
        """Save settings and close dialog."""
        use_system_default = self.system_radio.isChecked()
        
        if not use_system_default:
            # Validate custom reader
            path = self.path_input.text().strip()
            name = self.name_input.text().strip()
            
            if not path:
                QMessageBox.warning(self, "Error", "Please select a reader application.")
                return
            
            if not os.path.exists(path):
                QMessageBox.warning(self, "Error", "Selected file does not exist.")
                return
            
            if not name:
                name = Path(path).stem
        
        # Save settings
        settings.set_reader_settings(
            enabled=True,  # Always enabled when we get here
            path=self.path_input.text().strip() if not use_system_default else "",
            name=self.name_input.text().strip() if not use_system_default else "",
            use_system_default=use_system_default
        )
        
        QMessageBox.information(
            self, "Settings Saved",
            "Reader settings have been saved successfully."
        )
        
        self.accept()