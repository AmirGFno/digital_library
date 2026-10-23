"""
Book details / metadata editor.

Shows the cover, embedded comic metadata and reading statistics, and lets the
user correct the metadata (title, series, volume, writer, publisher, year,
rating, favorite flag and summary).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from comic_metadata import count_pages
from config import CARD_WIDTH, COVER_HEIGHT
from cover_extractor import cover_extractor
from database import db
from utils.helpers import format_file_size, open_containing_folder, open_file_with_reader
from utils.logger import logger
from utils.reader_manager import SYSTEM_READER_ID, reader_manager


class DetailsDialog(QDialog):
    """View and edit everything known about a single book."""

    def __init__(self, book_id: int, parent=None):
        super().__init__(parent)
        self.book_id = book_id
        self.book = db.get_book(book_id) or {}
        self.updated = False
        self._page_count_detected = False

        self.setWindowTitle(self.book.get("title") or "Book details")
        self.setMinimumSize(820, 620)
        self._build_ui()
        self._load_book()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QLabel(self.book.get("title") or "Book details")
        header.setObjectName("TitleLabel")
        header.setWordWrap(True)
        layout.addWidget(header)

        path_label = QLabel(str(self.book.get("filepath", "")))
        path_label.setObjectName("SubtitleLabel")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        body = QHBoxLayout()
        body.setSpacing(18)
        layout.addLayout(body, 1)

        # Cover ---------------------------------------------------------
        cover_frame = QFrame()
        cover_frame.setFixedWidth(CARD_WIDTH + 40)
        cover_layout = QVBoxLayout(cover_frame)
        cover_layout.setContentsMargins(0, 0, 0, 0)
        self.cover_label = QLabel("Loading...")
        self.cover_label.setFixedSize(CARD_WIDTH, COVER_HEIGHT)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet(
            "background-color: #1a1d22; border-radius: 8px; border: 1px solid #2a2f37;"
        )
        cover_layout.addWidget(self.cover_label)
        self.cover_button = QPushButton("Open book")
        self.cover_button.setObjectName("PrimaryButton")
        self.cover_button.clicked.connect(self._open_book)
        cover_layout.addWidget(self.cover_button)

        open_row = QHBoxLayout()
        self.reader_combo = QComboBox()
        self.reader_combo.addItem("Open with...", SYSTEM_READER_ID)
        for reader in reader_manager.available_readers():
            if reader.is_system:
                continue
            self.reader_combo.addItem(reader.name, reader.id)
        open_row.addWidget(self.reader_combo, 1)
        open_reader = QPushButton("Go")
        open_reader.clicked.connect(self._open_with_selected)
        open_row.addWidget(open_reader)
        cover_layout.addLayout(open_row)

        folder_button = QPushButton("Show in folder")
        folder_button.clicked.connect(
            lambda: open_containing_folder(self.book.get("filepath", ""))
        )
        cover_layout.addWidget(folder_button)
        cover_layout.addStretch()
        body.addWidget(cover_frame)

        # Metadata form -------------------------------------------------
        form_container = QWidget()
        form = QFormLayout(form_container)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        self.title_input = QLineEdit()
        form.addRow("Title:", self.title_input)

        self.series_combo = QComboBox()
        self.series_combo.addItem("None (unsorted)", None)
        for series in db.get_all_series():
            self.series_combo.addItem(series["name"], series["id"])
        form.addRow("Series:", self.series_combo)

        self.volume_input = QLineEdit()
        self.volume_input.setPlaceholderText("e.g. 3, Annual, 1.5")
        form.addRow("Volume:", self.volume_input)

        self.writer_input = QLineEdit()
        form.addRow("Writer:", self.writer_input)

        self.publisher_input = QLineEdit()
        form.addRow("Publisher:", self.publisher_input)

        year_row = QHBoxLayout()
        self.year_spin = QSpinBox()
        self.year_spin.setRange(0, 2200)
        self.year_spin.setSpecialValueText("Unknown")
        year_row.addWidget(self.year_spin)
        self.favorite_check = QCheckBox("Favorite")
        year_row.addWidget(self.favorite_check)
        year_row.addSpacing(12)
        year_row.addWidget(QLabel("Rating:"))
        self.rating_spin = QSpinBox()
        self.rating_spin.setRange(0, 5)
        self.rating_spin.setSuffix(" ★")
        year_row.addWidget(self.rating_spin)
        year_row.addStretch()
        form.addRow("Year:", year_row)

        self.summary_edit = QTextEdit()
        self.summary_edit.setPlaceholderText("Synopsis / notes")
        self.summary_edit.setMinimumHeight(110)
        form.addRow("Summary:", self.summary_edit)

        # Statistics
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("SubtitleLabel")
        self.stats_label.setWordWrap(True)
        form.addRow("Statistics:", self.stats_label)

        body.addWidget(form_container, 1)

        # Buttons -------------------------------------------------------
        buttons = QDialogButtonBox()
        self.save_button = QPushButton("Save changes")
        self.save_button.setObjectName("PrimaryButton")
        close_button = QPushButton("Close")
        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(close_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _load_book(self):
        book = self.book = db.get_book(self.book_id) or self.book

        self.title_input.setText(book.get("title") or Path(book.get("filepath", "")).stem)
        series_id = book.get("series_id")
        index = self.series_combo.findData(series_id)
        self.series_combo.setCurrentIndex(index if index >= 0 else 0)
        self.volume_input.setText(str(book.get("volume") or ""))
        self.writer_input.setText(book.get("writer") or "")
        self.publisher_input.setText(book.get("publisher") or "")
        try:
            self.year_spin.setValue(int(book.get("year") or 0))
        except (TypeError, ValueError):
            self.year_spin.setValue(0)
        self.favorite_check.setChecked(bool(book.get("favorite")))
        try:
            self.rating_spin.setValue(int(book.get("rating") or 0))
        except (TypeError, ValueError):
            self.rating_spin.setValue(0)
        self.summary_edit.setPlainText(book.get("summary") or "")

        self._load_cover()
        self._update_statistics()
        self._detect_pages_if_needed()

    def _load_cover(self):
        try:
            cover_path = cover_extractor.get_cover(
                self.book.get("filepath", ""), self.book_id
            )
            if cover_path and Path(cover_path).exists():
                pixmap = QPixmap(cover_path)
                self.cover_label.setPixmap(
                    pixmap.scaled(
                        CARD_WIDTH,
                        COVER_HEIGHT,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self.cover_label.setText("No cover")
        except Exception as exc:
            logger.error(f"Could not load cover in details dialog: {exc}")
            self.cover_label.setText("No cover")

    def _update_statistics(self):
        book = self.book
        size = book.get("file_size")
        pages = book.get("page_count")
        created = book.get("created_at") or "-"
        last_opened = book.get("last_opened_at") or "Never"
        opened = book.get("open_count") or 0
        parts = [
            f"{format_file_size(size) if size else 'Unknown size'}",
            f"{pages} pages" if pages else "page count unknown",
            f"added {str(created)[:10]}",
            f"opened {opened}× (last: {str(last_opened)[:10]})",
        ]
        self.stats_label.setText("  •  ".join(parts))

    def _detect_pages_if_needed(self):
        """Fill in a missing page count once, for the opened book only."""
        if self.book.get("page_count"):
            return
        filepath = self.book.get("filepath", "")
        if not filepath or not Path(filepath).exists():
            return
        try:
            pages = count_pages(filepath)
            if pages:
                db.update_book(self.book_id, page_count=pages)
                self.book["page_count"] = pages
                self._update_statistics()
                self._page_count_detected = True
        except Exception as exc:
            logger.debug(f"Page detection failed: {exc}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _open_book(self):
        from utils.reader_manager import reader_manager as manager

        ok, message = manager.open_file(self.book.get("filepath", ""))
        if not ok:
            QMessageBox.warning(self, "Open book", message)

    def _open_with_selected(self):
        reader_id = self.reader_combo.currentData() or SYSTEM_READER_ID
        ok, message = open_file_with_reader(reader_id, self.book.get("filepath", ""))
        if not ok:
            QMessageBox.warning(self, "Open book", message)

    def _save(self):
        title = self.title_input.text().strip() or None
        series_id = self.series_combo.currentData()
        volume = self.volume_input.text().strip() or None
        writer = self.writer_input.text().strip() or None
        publisher = self.publisher_input.text().strip() or None
        year = self.year_spin.value() or None
        rating = self.rating_spin.value()
        favorite = 1 if self.favorite_check.isChecked() else 0
        summary = self.summary_edit.toPlainText().strip() or None

        updated = db.update_book(
            self.book_id,
            title=title,
            series_id=series_id,
            volume=volume,
            writer=writer,
            publisher=publisher,
            year=year,
            rating=rating,
            favorite=favorite,
            summary=summary,
        )
        if updated:
            self.updated = True
            self.book = db.get_book(self.book_id) or self.book
            self.setWindowTitle(self.book.get("title") or "Book details")
            self.accept()
        else:
            QMessageBox.warning(
                self, "Save", "Nothing could be saved (the book may have been deleted)."
            )
