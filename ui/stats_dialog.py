"""
Library statistics, presented as a dashboard instead of a message box.

The numbers already existed (``db.get_statistics``) but were only ever shown as
an HTML table inside a plain dialog. This puts them on the same stat cards the
main window uses, adds a reading-progress bar and a format breakdown.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import (
    QWidget,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from config import APP_NAME
from database import db
from ui import layout as layout_tools
from ui import theme
from ui.widgets import StatCard, Divider
from utils.helpers import format_file_size
from utils.settings import settings

FORMAT_LABELS = (
    ("comic", "Comics (CBZ / CBR / CB7)", theme.ACCENT),
    ("pdf", "PDF", "#f87171"),
    ("image", "Images", theme.BLUE),
    ("archive", "Archives", theme.VIOLET),
    ("other", "Other", theme.TEXT_DIM),
)


class StatisticsDialog(QDialog):
    """A small dashboard for the whole library."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Library statistics")
        self._preferred_size = QSize(700, 600)
        self._build_ui()
        layout_tools.finish_dialog(self, self._preferred_size, QSize(520, 420))

    def _build_ui(self):
        stats = db.get_statistics()
        total = stats.get("total", 0)
        read = stats.get("read_count", 0)
        percent = round(100 * read / total) if total else 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        title = QLabel("Library statistics")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        root = settings.get_library_root() or "No library folder set"
        subtitle = QLabel(root)
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # ---- cards ------------------------------------------------------
        cards_box = QWidget()
        cards = QHBoxLayout(cards_box)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(10)
        for glyph, caption, value, accent in (
            ("▦", "BOOKS", total, theme.BLUE),
            ("✓", "READ", read, theme.GREEN),
            ("●", "UNREAD", stats.get("unread_count", 0), theme.ACCENT),
            ("★", "FAVORITES", stats.get("favorites", 0), theme.GOLD),
            ("≡", "SERIES", stats.get("series_count", 0), theme.VIOLET),
        ):
            card = StatCard(glyph, caption, accent)
            card.set_value(value)
            cards.addWidget(card)
        layout.addWidget(cards_box)

        # ---- progress ---------------------------------------------------
        progress_card = QFrame()
        progress_card.setObjectName("Chip")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(14, 12, 14, 12)
        progress_layout.setSpacing(8)

        header = QHBoxLayout()
        caption = QLabel("Reading progress")
        caption.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; font-weight: 700;")
        header.addWidget(caption)
        header.addStretch()
        value = QLabel(f"{read} of {total} books  ·  {percent}%")
        value.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        header.addWidget(value)
        progress_layout.addLayout(header)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(percent)
        bar.setTextVisible(False)
        bar.setFixedHeight(10)
        bar.setStyleSheet(
            f"QProgressBar {{ background-color: {theme.SURFACE_ACTIVE};"
            " border: none; border-radius: 5px; }"
            f"QProgressBar::chunk {{ border-radius: 5px;"
            " background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {theme.ACCENT}, stop:1 {theme.GOLD}); }}"
        )
        progress_layout.addWidget(bar)
        layout.addWidget(progress_card)

        # ---- formats ----------------------------------------------------
        layout.addWidget(Divider())
        formats = stats.get("formats", {})
        formats_box = QWidget()
        format_row = QHBoxLayout(formats_box)
        format_row.setContentsMargins(0, 0, 0, 0)
        format_row.setSpacing(10)
        for key, label, color in FORMAT_LABELS:
            count = formats.get(key, 0)
            chip = QFrame()
            chip.setObjectName("Chip")
            chip_layout = QVBoxLayout(chip)
            chip_layout.setContentsMargins(12, 8, 12, 8)
            chip_layout.setSpacing(0)
            number = QLabel(str(count))
            number.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: 800;")
            text = QLabel(label)
            text.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
            chip_layout.addWidget(number)
            chip_layout.addWidget(text)
            format_row.addWidget(chip)
        layout.addWidget(formats_box)

        # ---- footer stats ----------------------------------------------
        facts = QLabel(
            f"{format_file_size(stats.get('total_size') or 0)} on disk  ·  "
            f"{stats.get('total_pages', 0) or 0} pages  ·  "
            f"{stats.get('started_count', 0)} started  ·  "
            f"added with {APP_NAME}"
        )
        facts.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        facts.setWordWrap(True)
        layout.addWidget(facts)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("Close")
        close.setObjectName("PrimaryButton")
        close.setMinimumWidth(120)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
