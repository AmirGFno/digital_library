"""
Dialog windows for the application.
"""
from typing import Optional, List
from pathlib import Path
import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QFileDialog,
    QMessageBox, QListWidget, QListWidgetItem, QCheckBox,
    QProgressDialog,
    QApplication
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from comic_metadata import read_metadata
from config import ALL_EXTENSIONS
from database import db
from importer import scan_folder
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
            f"Comic & book files ({extensions});;All Files (*)"
        )
        if files:
            self.filepaths = files
            if len(files) == 1:
                self.file_label.setText(files[0])
                self._autofill_from_metadata(files[0])
            else:
                self.file_label.setText(f"{len(files)} files selected")

    def _autofill_from_metadata(self, filepath: str):
        """Pre-fill the form with embedded ComicInfo.xml values."""
        try:
            metadata = read_metadata(filepath)
        except Exception:
            return
        if not metadata:
            return
        if not self.title_input.text().strip() and metadata.get('title'):
            self.title_input.setText(str(metadata['title']))
        if not self.volume_input.text().strip() and metadata.get('volume'):
            self.volume_input.setText(str(metadata['volume']))
        if metadata.get('series_name'):
            index = self.series_combo.findText(str(metadata['series_name']))
            if index >= 0:
                self.series_combo.setCurrentIndex(index)
    
    def _add_book(self):
        if not self.filepaths:
            QMessageBox.warning(self, "Error", "Please select at least one file.")
            return

        from importer import importer

        series_id = self.series_combo.currentData()
        volume = self.volume_input.text().strip() or None
        title = self.title_input.text().strip() or None
        if len(self.filepaths) > 1:
            # A single manual title cannot describe several files.
            title = None

        result = importer.import_files(
            self.filepaths,
            series_id=series_id,
            title=title,
            volume=volume,
            use_metadata=True,
        )

        message = result.summary()
        if result.errors:
            message += "\n\n" + "\n".join(result.errors[:5])
        QMessageBox.information(self, "Import finished", message)
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
        
        # Options
        options_row = QHBoxLayout()
        self.recursive_check = QCheckBox("Include subfolders")
        self.recursive_check.setChecked(True)
        self.recursive_check.stateChanged.connect(self._scan_folder)
        options_row.addWidget(self.recursive_check)

        self.metadata_check = QCheckBox("Read ComicInfo.xml metadata")
        self.metadata_check.setChecked(True)
        self.metadata_check.setToolTip(
            "Use embedded series, volume, writer and publisher information"
        )
        options_row.addWidget(self.metadata_check)
        options_row.addStretch()
        layout.addLayout(options_row)

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
        start = settings.get_last_import_folder()
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", start)
        if folder:
            self.folder_path = folder
            self.folder_label.setText(folder)
            settings.set_last_import_folder(folder)
            self._scan_folder()

    def _scan_folder(self):
        if not self.folder_path:
            return

        self.files = scan_folder(
            self.folder_path, recursive=self.recursive_check.isChecked()
        )
        self.files_list.clear()
        for filepath in self.files:
            item = QListWidgetItem(Path(filepath).name)
            item.setToolTip(filepath)
            self.files_list.addItem(item)
    
    def _import_books(self):
        if not self.files:
            QMessageBox.warning(self, "Error", "No files to import.")
            return

        from importer import importer

        series_id = self.series_combo.currentData()

        progress = QProgressDialog("Importing comics...", "Cancel", 0, len(self.files), self)
        progress.setWindowTitle("Bulk import")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        def on_progress(index, total, filepath):
            progress.setMaximum(total)
            progress.setValue(index - 1)
            progress.setLabelText(f"Importing {Path(filepath).name}...")
            QApplication.processEvents()

        result = importer.import_files(
            self.files,
            series_id=series_id,
            use_metadata=self.metadata_check.isChecked(),
            progress=on_progress,
        )
        progress.setValue(len(self.files))

        message = result.summary()
        if result.errors:
            message += "\n\n" + "\n".join(result.errors[:5])
        QMessageBox.information(self, "Import finished", message)
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
