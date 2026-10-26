"""
Dialog windows for the application.
"""
from typing import Optional, List
from pathlib import Path
import os

from PyQt6.QtWidgets import (
    QWidget,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QFileDialog,
    QMessageBox, QListWidget, QListWidgetItem, QCheckBox,
    QProgressDialog,
    QFrame,
    QApplication
)
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap
from PIL import Image
import io

from comic_metadata import read_metadata
from config import ALL_EXTENSIONS
from database import db
from importer import scan_folder
from ui import layout as layout_tools
from ui import theme
from ui.widgets import WrappingLabel, wrap_long_words
from utils.settings import settings


# ----------------------------------------------------------------------
# Shared building blocks for the small form dialogs
# ----------------------------------------------------------------------
def _dialog_shell(dialog: QDialog, title: str, subtitle: str = "",
                  glyph: str = "", accent: str = ""):
    """Themed header (badge + title + subtitle) used by every form dialog."""
    from ui import theme

    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(22, 20, 22, 18)
    outer.setSpacing(14)

    header = QHBoxLayout()
    header.setSpacing(12)
    if glyph:
        badge = QLabel(glyph)
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"color: {accent or theme.ACCENT_GLOW};"
            f" background-color: {theme.SURFACE_ACTIVE};"
            " border-radius: 12px; font-size: 17px; font-weight: 700;"
        )
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

    text_box = QVBoxLayout()
    text_box.setSpacing(3)
    title_label = QLabel(title)
    title_label.setObjectName("TitleLabel")
    text_box.addWidget(title_label)
    if subtitle:
        sub_label = QLabel(subtitle)
        sub_label.setObjectName("SubtitleLabel")
        sub_label.setWordWrap(True)
        text_box.addWidget(sub_label)
    header.addLayout(text_box, 1)
    outer.addLayout(header)
    return outer


def _field_caption(text: str) -> QLabel:
    """Small dimmed caption above an input."""
    from ui import theme

    label = QLabel(text)
    label.setStyleSheet(
        f"color: {theme.TEXT_DIM}; font-size: 10px; font-weight: 700;"
    )
    return label


def _dialog_actions(dialog: QDialog, primary_text: str, primary_slot,
                    cancel_text: str = "Cancel") -> QHBoxLayout:
    """Right-aligned ghost cancel + accent primary button."""
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addStretch()
    cancel = QPushButton(cancel_text)
    cancel.setObjectName("GhostButton")
    cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel.clicked.connect(dialog.reject)
    primary = QPushButton(primary_text)
    primary.setObjectName("PrimaryButton")
    primary.setCursor(Qt.CursorShape.PointingHandCursor)
    primary.setDefault(True)
    primary.setMinimumWidth(120)
    primary.clicked.connect(primary_slot)
    dialog.primary_button = primary
    row.addWidget(cancel)
    row.addWidget(primary)
    return row


class AddBookDialog(QDialog):
    """Dialog for adding a new book."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Book")
        self.setMinimumWidth(500)
        self.filepaths: List[str] = []
        self._setup_ui()
    
    def _setup_ui(self):
        layout = _dialog_shell(
            self,
            "Add comics",
            "Pick one or more CBZ, CBR, CB7 or PDF files. Metadata is read from "
            "ComicInfo.xml when it is available.",
            glyph="＋",
        )

        file_card = QFrame()
        file_card.setObjectName("Chip")
        file_layout = QHBoxLayout(file_card)
        file_layout.setContentsMargins(12, 10, 10, 10)
        file_layout.setSpacing(8)
        self.file_label = WrappingLabel("No file selected")
        self.file_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
        file_btn = QPushButton("Browse...")
        file_btn.setObjectName("GhostButton")
        file_btn.clicked.connect(self._browse_files)
        file_layout.addWidget(self.file_label, 1)
        file_layout.addWidget(file_btn)
        layout.addWidget(file_card)

        layout.addWidget(_field_caption("TITLE (OPTIONAL)"))
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Leave empty to use the file name")
        layout.addWidget(self.title_input)

        layout.addWidget(_field_caption("SERIES"))
        self.series_combo = QComboBox()
        self.series_combo.addItem("None", None)
        for series in db.get_all_series():
            self.series_combo.addItem(series['name'], series['id'])
        layout.addWidget(self.series_combo)

        layout.addWidget(_field_caption("VOLUME"))
        self.volume_input = QLineEdit()
        self.volume_input.setPlaceholderText("e.g. 1, 2, Special")
        layout.addWidget(self.volume_input)

        layout.addStretch()
        layout.addLayout(_dialog_actions(self, "Add to library", self._add_book))

    def _browse_files(self):
        extensions = " ".join(f"*{ext}" for ext in ALL_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Books", "",
            f"Comic & book files ({extensions});;All Files (*)"
        )
        if files:
            self.filepaths = files
            if len(files) == 1:
                self.file_label.setText(wrap_long_words(files[0]))
                self.file_label.setToolTip(files[0])
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
        from ui.name_preview_dialog import preview_when_needed
        from utils.settings import settings

        series_id = self.series_combo.currentData()
        volume = self.volume_input.text().strip() or None
        title = self.title_input.text().strip() or None
        if len(self.filepaths) > 1:
            # A single manual title cannot describe several files.
            title = None

        # The automatic title comes from the file name; show it before saving.
        clean_names = settings.get_clean_names()
        if title is None and clean_names:
            preview = preview_when_needed(self.filepaths, self)
            if preview is not None:
                if not preview.exec():
                    return
                clean_names = preview.use_clean_names

        result = importer.import_files(
            self.filepaths,
            series_id=series_id,
            title=title,
            volume=volume,
            use_metadata=True,
            clean_names=clean_names,
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
        layout = _dialog_shell(
            self,
            "Change the volume",
            "Volumes decide the order inside a series.",
            glyph="#",
        )
        layout.addWidget(_field_caption("VOLUME"))
        self.volume_input = QLineEdit()
        self.volume_input.setText(current_volume or "")
        self.volume_input.setPlaceholderText("e.g. 1, 2, Special")
        self.volume_input.selectAll()
        layout.addWidget(self.volume_input)
        layout.addStretch()
        layout.addLayout(_dialog_actions(self, "Save", self.accept, "Cancel"))

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
        layout = _dialog_shell(
            self,
            "New series",
            "A series groups the volumes of one title and gives the grid its "
            "shelves on the left.",
            glyph="≡",
        )
        layout.addWidget(_field_caption("SERIES NAME"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter series name")
        layout.addWidget(self.name_input)
        layout.addStretch()
        layout.addLayout(_dialog_actions(self, "Create series", self._add_series))

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
        layout = _dialog_shell(
            self,
            "Rename series",
            "The new name is used everywhere in the library.",
            glyph="✎",
        )
        layout.addWidget(_field_caption("SERIES NAME"))
        self.name_input = QLineEdit()
        self.name_input.setText(current_name)
        self.name_input.selectAll()
        layout.addWidget(self.name_input)
        layout.addStretch()
        layout.addLayout(_dialog_actions(self, "Save", self._save_series))

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
                 checkbox_text: Optional[str] = None, parent=None,
                 danger: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.setMaximumHeight(320)
        self.danger = danger
        self._setup_ui(message, checkbox_text)

    def _setup_ui(self, message: str, checkbox_text: Optional[str]):
        from ui import theme

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel("⚠" if self.danger else "?")
        icon.setFixedSize(38, 38)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        accent = theme.ACCENT if self.danger else theme.BLUE
        icon.setStyleSheet(
            f"color: {accent}; background: {theme.SURFACE_ACTIVE};"
            " border-radius: 12px; font-size: 17px; font-weight: 700;"
        )
        header.addWidget(icon)

        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px;")
        header.addWidget(msg_label, 1)
        layout.addLayout(header)

        self.checkbox = None
        if checkbox_text:
            self.checkbox = QCheckBox(checkbox_text)
            layout.addWidget(self.checkbox)

        layout.addStretch(1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("GhostButton")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        self.confirm_button = QPushButton("Confirm")
        self.confirm_button.setObjectName("DangerButton" if self.danger else "PrimaryButton")
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.clicked.connect(self.accept)
        self.confirm_button.setDefault(True)

        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.confirm_button)
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
        layout = _dialog_shell(
            self,
            "Bulk import",
            "Add every comic in a folder to the library in one go.",
            glyph="⇩",
        )

        folder_card = QFrame()
        folder_card.setObjectName("Chip")
        folder_layout = QHBoxLayout(folder_card)
        folder_layout.setContentsMargins(12, 10, 10, 10)
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
        folder_btn = QPushButton("Browse folder...")
        folder_btn.setObjectName("GhostButton")
        folder_btn.clicked.connect(self._browse_folder)
        folder_layout.addWidget(self.folder_label, 1)
        folder_layout.addWidget(folder_btn)
        layout.addWidget(folder_card)

        options_row = QHBoxLayout()
        options_row.setSpacing(14)
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

        layout.addWidget(_field_caption("FILES FOUND"))
        self.files_list = QListWidget()
        self.files_list.setMinimumHeight(180)
        layout.addWidget(self.files_list, 1)

        series_row = QHBoxLayout()
        series_row.setSpacing(10)
        series_row.addWidget(_field_caption("ASSIGN TO SERIES"))
        self.series_combo = QComboBox()
        self.series_combo.addItem("None", None)
        for series in db.get_all_series():
            self.series_combo.addItem(series['name'], series['id'])
        series_row.addWidget(self.series_combo, 1)
        layout.addLayout(series_row)

        layout.addLayout(_dialog_actions(self, "Import", self._import_books))

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
    """Choose the cover of one book.

    Two sources are offered: an image file from disk, and - much more useful
    for comics - any page inside the book itself. Automatic cover detection is
    right for almost every file, but an archive that starts with an advertising
    page needs a manual choice, and hunting for an image on disk is not one.
    """

    def __init__(self, book_id: int, book_title: str, parent=None,
                 filepath: str = ""):
        super().__init__(parent)
        self.book_id = book_id
        self.setWindowTitle(f"Set Custom Cover - {book_title}")
        self.filepath = str(filepath or "")
        self.selected_image = None
        self._page_bytes: Optional[bytes] = None
        self._setup_ui()
    
    def _setup_ui(self):
        from ui import theme

        layout = _dialog_shell(
            self,
            "Custom cover",
            "Choose any image to use as the cover of this book.",
            glyph="🖼",
            accent=theme.GOLD,
        )

        body_widget = QWidget()
        body = QHBoxLayout(body_widget)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        layout.addWidget(body_widget, 1)

        # Pages of the book itself -------------------------------------
        pages_column = QVBoxLayout()
        pages_column.setSpacing(6)
        self.pages_caption = QLabel("PAGES IN THIS BOOK")
        self.pages_caption.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px; font-weight: 700;"
        )
        pages_column.addWidget(self.pages_caption)
        self.pages_list = QListWidget()
        self.pages_list.setMinimumWidth(210)
        self.pages_list.currentItemChanged.connect(self._on_page_selected)
        pages_column.addWidget(self.pages_list, 1)
        self.pages_hint = QLabel("")
        self.pages_hint.setWordWrap(True)
        self.pages_hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        pages_column.addWidget(self.pages_hint)
        body.addLayout(pages_column, 1)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(240)
        self.preview_label.setStyleSheet(
            f"QLabel {{ background-color: {theme.BG_ELEVATED};"
            f" border: 1px dashed {theme.BORDER_STRONG};"
            f" border-radius: 14px; color: {theme.TEXT_DIM}; font-size: 12px; }}"
        )
        self.preview_label.setText("No image selected")
        body.addWidget(self.preview_label, 2)

        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet(
            f"font-size: 11px; color: {theme.TEXT_DIM};"
        )
        layout.addWidget(self.info_label)

        buttons_widget = QWidget()
        buttons_box = QVBoxLayout(buttons_widget)
        buttons_box.setContentsMargins(0, 0, 0, 0)
        buttons_box.setSpacing(10)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        browse_btn = QPushButton("Browse image...")
        browse_btn.clicked.connect(self._browse_image)
        clear_btn = QPushButton("Clear preview")
        clear_btn.setObjectName("GhostButton")
        clear_btn.clicked.connect(self._clear_preview)
        btn_layout.addWidget(browse_btn)
        btn_layout.addWidget(clear_btn)
        btn_layout.addStretch()
        buttons_box.addLayout(btn_layout)

        actions = _dialog_actions(self, "Set as cover", self._set_cover)
        self.primary_button.setEnabled(False)
        self.set_btn = self.primary_button
        buttons_box.addLayout(actions)
        layout.addWidget(buttons_widget)

        self._fill_pages()
        # keep_first=1: the themed header of _dialog_shell stays in place.
        layout_tools.finish_dialog(
            self, QSize(860, 620), QSize(560, 360), keep_first=1, keep_last=1
        )

    # ------------------------------------------------------------------
    # Pages of the book
    # ------------------------------------------------------------------
    def _fill_pages(self):
        from cover_extractor import cover_extractor

        pages = cover_extractor.list_pages(self.filepath) if self.filepath else []
        self.pages_list.clear()
        for index, name in enumerate(pages):
            item = QListWidgetItem(f"{index + 1}.  {name}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
            if index == 0:
                item.setText(f"{index + 1}.  {name}   ← current cover")
            self.pages_list.addItem(item)

        if pages:
            self.pages_hint.setText(
                "Pick the page that should be the cover. The first page is "
                "used automatically unless a custom cover is set."
            )
            self.pages_caption.setText(f"PAGES IN THIS BOOK ({len(pages)})")
        else:
            self.pages_hint.setText(
                "This file cannot be browsed; choose an image file instead."
            )
            self.pages_list.setVisible(False)
            self.pages_caption.setVisible(False)

    def _on_page_selected(self, current=None, _previous=None):
        if current is None:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        from cover_extractor import cover_extractor

        data = cover_extractor.read_page(self.filepath, name)
        if not data:
            self.pages_hint.setText(f"“{name}” could not be read.")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data) or pixmap.isNull():
            self.pages_hint.setText(f"“{name}” is not an image the app can show.")
            return
        self._page_bytes = data
        self.selected_image = None
        scaled = pixmap.scaled(
            max(40, self.preview_label.width() - 20),
            max(40, self.preview_label.height() - 20),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        self.info_label.setText(f"{pixmap.width()} × {pixmap.height()}  ·  {name}")
        self.set_btn.setEnabled(True)

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
        self._page_bytes = None
        self.preview_label.clear()
        self.preview_label.setText("No image selected")
        self.info_label.clear()
        self.set_btn.setEnabled(False)
    
    def _set_cover(self):
        """Save the chosen page (or file) as this book's cover."""
        if not self.selected_image and not self._page_bytes:
            return
        
        from config import CUSTOM_COVERS_DIR
        import shutil
        
        try:
            # Create new filename
            if self._page_bytes:
                # A page taken out of the archive is always stored as JPEG so
                # the cover folder never has to deal with exotic formats.
                new_filename = f"book_{self.book_id}_cover.jpg"
                new_path = CUSTOM_COVERS_DIR / new_filename
                new_path.parent.mkdir(parents=True, exist_ok=True)
                image = Image.open(io.BytesIO(self._page_bytes))
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                image.save(new_path, "JPEG", quality=92)
            else:
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
