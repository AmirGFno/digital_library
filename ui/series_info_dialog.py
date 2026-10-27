"""
Information about one series.

The navigation pane only had room for a name and a counter, so everything else
the library knows about a series — how many volumes it has, how much is read,
who wrote it, which formats and years it spans, where it came from — was
invisible. This dialog shows all of it in one place, computed from the books
themselves so it can never drift from the grid.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from database import db
from ui import layout as layout_tools
from ui import theme
from ui.widgets import Divider, StatCard
from utils.helpers import format_file_size, open_containing_folder


def _file_format(filepath: str) -> str:
    """``.cbz`` -> ``CBZ``; anything without a suffix is ``OTHER``."""
    suffix = Path(str(filepath or "")).suffix.lstrip(".").upper()
    return suffix or "OTHER"


def _join_limited(values, limit: int = 3) -> str:
    """``a, b, c`` and ``a, b, c +2`` instead of an endless line."""
    unique = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in unique:
            unique.append(text)
    if not unique:
        return "—"
    shown = unique[:limit]
    extra = len(unique) - len(shown)
    return ", ".join(shown) + (f"  +{extra}" if extra > 0 else "")


def _year_text(years) -> str:
    values = sorted({int(year) for year in years if year})
    if not values:
        return "—"
    if len(values) == 1:
        return str(values[0])
    return f"{values[0]} – {values[-1]}"


def _date_text(value) -> str:
    """A stored timestamp as a plain date, or an em dash when there is none."""
    text = str(value or "").strip()
    if not text:
        return "—"
    return text.split(" ")[0].split("T")[0]


def series_statistics(books) -> dict:
    """Everything the info dialog shows, derived from the series' books."""
    books = list(books or [])
    total = len(books)
    read = sum(1 for book in books if book.get("is_read"))
    favorites = sum(1 for book in books if book.get("favorite"))
    started = sum(1 for book in books if book.get("last_opened_at"))
    pages = sum(int(book.get("page_count") or 0) for book in books)
    size = sum(int(book.get("file_size") or 0) for book in books)

    formats: dict[str, int] = {}
    for book in books:
        name = _file_format(book.get("filepath", ""))
        formats[name] = formats.get(name, 0) + 1

    opened = [book.get("last_opened_at") for book in books if book.get("last_opened_at")]
    added = [book.get("created_at") for book in books if book.get("created_at")]

    return {
        "total": total,
        "read": read,
        "unread": total - read,
        "started": started,
        "favorites": favorites,
        "pages": pages,
        "size": size,
        "formats": formats,
        "years": [book.get("year") for book in books],
        "writers": [book.get("writer") for book in books],
        "publishers": [book.get("publisher") for book in books],
        "volumes": [book.get("volume") for book in books],
        "last_read": max(opened) if opened else "",
        "added": min(added) if added else "",
    }


class SeriesInfoDialog(QDialog):
    """A one-page summary of a series: counts, progress and metadata."""

    def __init__(self, series_id: int, parent=None):
        super().__init__(parent)
        self.series_id = series_id
        self.series = db.get_series(series_id) or {}
        self.books = db.get_all_books(series_id=series_id) if self.series else []
        self.stats = series_statistics(self.books)

        self.setWindowTitle(f"{self.series.get('name') or 'Series'} — info")
        self._build_ui()
        layout_tools.finish_dialog(self, QSize(680, 560), QSize(480, 380))

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        # ---- header ------------------------------------------------------
        header_widget = QWidget()
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)

        self.tile = QLabel((self.series.get("name") or "?")[:1].upper())
        self.tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tile.setFixedSize(48, 48)
        self.tile.setStyleSheet(
            f"color: {theme.TEXT}; background-color: {theme.SURFACE_ACTIVE};"
            " border-radius: 10px; font-size: 20px; font-weight: 700;"
        )
        header.addWidget(self.tile, 0, Qt.AlignmentFlag.AlignTop)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title = QLabel(self.series.get("name") or "Series")
        self.title.setObjectName("TitleLabel")
        self.title.setWordWrap(True)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("SubtitleLabel")
        self.subtitle.setWordWrap(True)
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box, 1)
        layout.addWidget(header_widget)

        # Everything between the header and the buttons scrolls when the screen
        # is short, so the Close button never ends up below the taskbar.
        body_widget = QWidget()
        body = QVBoxLayout(body_widget)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        layout.addWidget(body_widget, 1)

        # ---- counts ------------------------------------------------------
        cards = QHBoxLayout()
        cards.setSpacing(10)
        for glyph, caption, value, accent in (
            ("▦", "VOLUMES", self.stats["total"], theme.BLUE),
            ("✓", "READ", self.stats["read"], theme.GREEN),
            ("●", "UNREAD", self.stats["unread"], theme.ACCENT),
            ("★", "FAVORITES", self.stats["favorites"], theme.GOLD),
        ):
            card = StatCard(glyph, caption, accent)
            card.set_value(value)
            card.setCursor(Qt.CursorShape.ArrowCursor)
            cards.addWidget(card)
        body.addLayout(cards)

        # ---- reading progress -------------------------------------------
        progress_card = QFrame()
        progress_card.setObjectName("Chip")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(14, 12, 14, 12)
        progress_layout.setSpacing(8)

        progress_header = QHBoxLayout()
        caption = QLabel("Reading progress")
        caption.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 12px; font-weight: 700;"
        )
        progress_header.addWidget(caption)
        progress_header.addStretch()
        total = self.stats["total"]
        percent = round(100 * self.stats["read"] / total) if total else 0
        self.progress_label = QLabel(
            f"{self.stats['read']} of {total} read  ·  {percent}%"
            if total else "No volumes yet"
        )
        self.progress_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px;"
        )
        progress_header.addWidget(self.progress_label)
        progress_layout.addLayout(progress_header)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(percent)
        bar.setTextVisible(False)
        bar.setFixedHeight(10)
        bar.setStyleSheet(
            f"QProgressBar {{ background-color: {theme.SURFACE_ACTIVE};"
            " border: none; border-radius: 5px; }"
            "QProgressBar::chunk { border-radius: 5px;"
            " background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {theme.ACCENT}, stop:1 {theme.GOLD}); }}"
        )
        progress_layout.addWidget(bar)
        body.addWidget(progress_card)

        # ---- metadata ----------------------------------------------------
        body.addWidget(Divider())
        facts = QFrame()
        facts.setObjectName("Chip")
        grid = QGridLayout(facts)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.value_labels = {}
        rows = (
            ("Writer", _join_limited(self.stats["writers"])),
            ("Publisher", _join_limited(self.stats["publishers"])),
            ("Years", _year_text(self.stats["years"])),
            ("Formats", self._formats_text()),
            ("Pages", f"{self.stats['pages']:,}" if self.stats["pages"] else "—"),
            ("Size on disk", format_file_size(self.stats["size"])
             if self.stats["size"] else "—"),
            ("First volume", self._first_volume_text()),
            ("Last read", _date_text(self.stats["last_read"])),
        )
        for index, (caption_text, value) in enumerate(rows):
            row, column = divmod(index, 2)
            caption_label = QLabel(caption_text.upper())
            caption_label.setObjectName("SectionLabel")
            value_label = QLabel(value)
            value_label.setStyleSheet(
                f"color: {theme.TEXT}; font-size: 12px;"
            )
            value_label.setWordWrap(True)
            value_label.setToolTip(value)
            grid.addWidget(caption_label, row, column * 2)
            grid.addWidget(value_label, row, column * 2 + 1)
            self.value_labels[caption_text] = value_label
        body.addWidget(facts)

        # ---- where it came from -----------------------------------------
        self.folder = str(self.series.get("folder") or "")
        self.folder_label = QLabel("")
        self.folder_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        self.folder_label.setWordWrap(True)
        if self.folder:
            self.folder_label.setText(f"Folder: {self.folder}")
            self.folder_label.setToolTip(self.folder)
        elif self.stats["added"]:
            self.folder_label.setText(
                f"Added {_date_text(self.stats['added'])}  ·  "
                f"No folder is linked to this series"
            )
        else:
            self.folder_label.setText("No folder is linked to this series")
        body.addWidget(self.folder_label)
        body.addStretch(1)

        # ---- buttons -----------------------------------------------------
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        if self.folder and Path(self.folder).is_dir():
            open_folder = QPushButton("Show in folder")
            open_folder.setObjectName("GhostButton")
            open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
            open_folder.clicked.connect(
                lambda: open_containing_folder(self.folder)
            )
            buttons.addWidget(open_folder)
        buttons.addStretch()
        close = QPushButton("Close")
        close.setObjectName("PrimaryButton")
        close.setMinimumWidth(110)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self._update_subtitle()

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------
    def _formats_text(self) -> str:
        formats = self.stats["formats"]
        if not formats:
            return "—"
        ordered = sorted(formats.items(), key=lambda item: (-item[1], item[0]))
        return "  ·  ".join(f"{name} × {count}" for name, count in ordered)

    def _first_volume_text(self) -> str:
        volumes = [str(book.get("volume") or "").strip()
                   for book in self.books if book.get("volume")]
        if not volumes:
            return "—"
        return volumes[0]

    def _update_subtitle(self):
        parts = []
        if self.stats["total"]:
            parts.append(
                f"{self.stats['total']} volume"
                + ("s" if self.stats["total"] != 1 else "")
            )
        if self.stats["unread"]:
            parts.append(f"{self.stats['unread']} unread")
        if self.stats["started"]:
            parts.append(f"{self.stats['started']} started")
        if not parts:
            parts.append("Empty series")
        self.subtitle.setText("  ·  ".join(parts))
