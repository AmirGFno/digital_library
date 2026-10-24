"""
Book card widget for the library grid.

A card shows the cover (loaded in a worker thread), the title, series/volume and
reading state, and exposes a rich context menu including "Open with" for every
detected comic reader.

The card is deliberately self-contained: the main window only connects signals.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import (
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    QSize,
    QThreadPool,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config import CARD_HEIGHT, CARD_WIDTH, COVER_HEIGHT
from cover_extractor import cover_extractor
from database import db
from ui import theme
from ui.widgets import elide
from utils.logger import logger
from utils.reader_manager import SYSTEM_READER_ID, reader_manager

COVER_WIDTH = CARD_WIDTH - 16
COVER_RADIUS = 12


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


class SelectCircle(QAbstractButton):
    """Small round checkbox that sits in the corner of a cover.

    Hollow while the book is not picked, filled with the accent colour and a
    white tick once it is. The card decides when it is visible: on hover, or on
    every card while a group selection is being built.
    """

    def __init__(self, parent=None, diameter: int = 22):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Select this book")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._checked = False

    def set_selected(self, selected: bool):
        selected = bool(selected)
        if selected == self._checked:
            return
        self._checked = selected
        self.setToolTip("Selected" if selected else "Select this book")
        self.update()

    def is_selected(self) -> bool:
        return self._checked

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        inset = 1.5
        rect = QRectF(
            inset, inset, self.width() - 2 * inset, self.height() - 2 * inset
        )

        if self._checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawEllipse(rect)

            pen = QPen(QColor("#ffffff"), max(1.8, self.width() * 0.11))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            width, height = self.width(), self.height()
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(width * 0.29, height * 0.53),
                        QPointF(width * 0.44, height * 0.68),
                        QPointF(width * 0.72, height * 0.34),
                    ]
                )
            )
        else:
            # Hollow ring with a dark halo: readable on light and dark covers.
            hovered = self.underMouse()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(6, 8, 12, 185 if hovered else 165), 4.6))
            painter.drawEllipse(rect)
            painter.setPen(QPen(QColor(255, 255, 255, 255 if hovered else 240), 2.0))
            painter.drawEllipse(rect)


class BookCard(QFrame):
    """Widget representing a single book."""

    clicked = pyqtSignal(int, object)          # book_id, keyboard modifiers
    context_opened = pyqtSignal(int)           # right-click, before the menu shows
    bulk_context_requested = pyqtSignal(int)   # right-click on a multi-selection
    select_mode_requested = pyqtSignal(int)    # "Select" from the context menu
    select_toggled = pyqtSignal(int)           # the corner circle was clicked
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
        self._selected = False
        self._multi = False
        self._selection_mode = False
        self._cover_pixmap: QPixmap | None = None
        self._cover_zoomed: QPixmap | None = None
        self._hovered = False
        self._shadow = None

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
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.setSpacing(7)

        self.cover_frame = QFrame()
        self.cover_frame.setObjectName("CoverFrame")
        self.cover_frame.setFixedSize(COVER_WIDTH, COVER_HEIGHT)
        self.cover_frame.setStyleSheet(
            f"QFrame#CoverFrame {{ background-color: {theme.BG_ELEVATED};"
            f" border-radius: {COVER_RADIUS}px; border: none; }}"
        )
        cover_layout = QVBoxLayout(self.cover_frame)
        cover_layout.setContentsMargins(0, 0, 0, 0)

        self.cover_label = QLabel("")
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setFixedSize(COVER_WIDTH, COVER_HEIGHT)
        self.cover_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; background: transparent;"
        )
        cover_layout.addWidget(self.cover_label)
        layout.addWidget(self.cover_frame)

        self._build_badges()
        self._build_quick_actions()

        self.title_label = QLabel(self._elided_title())
        self.title_label.setFixedHeight(19)
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.title_label.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 13px; font-weight: 600;"
            " background: transparent;"
        )
        layout.addWidget(self.title_label)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(4)

        self.info_label = QLabel(self._info_text())
        self.info_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        status_row.addWidget(self.info_label, 1)

        self.rating_label = QLabel("")
        self.rating_label.setStyleSheet(
            f"color: {theme.GOLD}; font-size: 10px; background: transparent;"
        )
        status_row.addWidget(self.rating_label)

        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 8px; background: transparent;"
        )
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px; background: transparent;"
        )
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label)
        layout.addLayout(status_row)

        for widget in self.findChildren(QLabel):
            if widget not in (self.cover_label,):
                widget.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
                )

        self._refresh_state()

    def _build_badges(self):
        self.format_badge = QLabel("")
        self.format_badge.setParent(self.cover_frame)
        self.format_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.format_badge.setStyleSheet(
            "color: #ffffff; font-size: 9px; font-weight: 700;"
            " background: rgba(10, 12, 16, 185); border-radius: 6px; padding: 2px 6px;"
        )
        self.format_badge.move(9, 9)
        self.format_badge.adjustSize()

        self.favorite_badge = QLabel("★")
        self.favorite_badge.setParent(self.cover_frame)
        self.favorite_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.favorite_badge.setFixedSize(24, 24)
        self.favorite_badge.setStyleSheet(
            f"color: {theme.GOLD}; font-size: 13px;"
            " background: rgba(10, 12, 16, 190); border-radius: 12px;"
        )
        # The star moved to the bottom corner: the top-right corner belongs to
        # the selection circle now.
        self.favorite_badge.move(COVER_WIDTH - 33, COVER_HEIGHT - 33)
        self.favorite_badge.setVisible(False)

        self.select_circle = SelectCircle(self.cover_frame)
        self.select_circle.move(COVER_WIDTH - 31, 8)
        self.select_circle.setVisible(False)
        self.select_circle.clicked.connect(
            lambda: self.select_toggled.emit(self.book_id)
        )

        for widget in (self.format_badge, self.favorite_badge):
            widget.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )

    def _build_quick_actions(self):
        self.quick_bar = QWidget(self.cover_frame)
        self.quick_bar.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        self.quick_bar.setStyleSheet(
            "background: rgba(8, 10, 14, 225); border-radius: 10px;"
        )
        # Compact bar anchored to the bottom-left corner: most of the cover
        # stays clickable, so selecting books with Ctrl never hits a button.
        self.quick_bar.setFixedSize(140, 34)
        self.quick_bar.move(10, COVER_HEIGHT - 44)
        self.quick_bar.setVisible(False)

        row = QHBoxLayout(self.quick_bar)
        row.setContentsMargins(5, 3, 5, 3)
        row.setSpacing(2)

        def button(text: str, tooltip: str, slot) -> QToolButton:
            widget = QToolButton()
            widget.setText(text)
            widget.setToolTip(tooltip)
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
            widget.setFixedSize(28, 26)
            widget.setStyleSheet(
                "QToolButton { border: none; background: transparent;"
                f" color: {theme.TEXT}; font-size: 13px; border-radius: 7px; }}"
                f"QToolButton:hover {{ background: {theme.ACCENT}; color: #ffffff; }}"
            )
            widget.clicked.connect(slot)
            return widget

        row.addWidget(button("▶", "Open", lambda: self.open_requested.emit(self.book_id)))
        row.addWidget(
            button("★", "Toggle favorite", lambda: self.favorite_requested.emit(self.book_id))
        )
        row.addWidget(
            button("✓", "Toggle read", lambda: self.toggle_read_requested.emit(self.book_id))
        )
        row.addWidget(
            button("⋯", "Details", lambda: self.details_requested.emit(self.book_id))
        )
        row.addStretch(1)

    def _display_title(self) -> str:
        title = self.book_data.get("title") or Path(self.book_data["filepath"]).stem
        return str(title)

    def _elided_title(self) -> str:
        """Short, single-line title that fits the card width."""
        return elide(self._display_title(), 24)

    def _info_text(self) -> str:
        """One short line under the title: volume plus who made it."""
        parts = []
        if self.book_data.get("volume"):
            parts.append(f"Vol. {self.book_data['volume']}")
        writer = self.book_data.get("writer")
        if writer:
            parts.append(elide(str(writer), 16))
        elif self.book_data.get("series_name"):
            parts.append(elide(str(self.book_data["series_name"]), 16))
        if self.book_data.get("year"):
            parts.append(str(self.book_data["year"]))
        if not parts:
            parts.append(Path(self.book_data["filepath"]).suffix.upper().lstrip("."))
        return "  ·  ".join(parts)

    def _refresh_state(self):
        favorite = bool(self.book_data.get("favorite"))
        is_read = bool(self.book_data.get("is_read"))
        rating = int(self.book_data.get("rating") or 0)

        self.favorite_badge.setVisible(favorite)
        self._sync_select_circle()

        self.status_dot.setStyleSheet(
            f"color: {theme.GREEN if is_read else theme.TEXT_DIM};"
            " font-size: 9px; background: transparent;"
        )
        self.status_label.setText("Read" if is_read else "Unread")
        self.status_label.setStyleSheet(
            f"color: {theme.GREEN if is_read else theme.TEXT_DIM};"
            " font-size: 10px; background: transparent;"
        )
        self.rating_label.setText(("★" * rating) if rating else "")

        self.title_label.setStyleSheet(
            "color: %s; font-size: 13px; font-weight: 600; background: transparent;"
            % (theme.TEXT_MUTED if is_read else theme.TEXT)
        )

        suffix = Path(self.book_data["filepath"]).suffix.upper().lstrip(".") or "FILE"
        color = {
            "CBZ": theme.BLUE,
            "CBR": theme.ACCENT,
            "CB7": theme.VIOLET,
            "CBT": theme.GOLD,
            "PDF": "#f87171",
        }.get(suffix, theme.TEXT_MUTED)
        self.format_badge.setText(suffix)
        self.format_badge.setStyleSheet(
            "color: %s; font-size: 9px; font-weight: 700;"
            " background: rgba(10, 12, 16, 200); border-radius: 6px;"
            " padding: 2px 6px;" % color
        )
        self.format_badge.adjustSize()

        self.setProperty("isRead", is_read)
        self.setProperty("favorite", favorite)
        self.setProperty("selected", self._selected)
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
        if not cover_path or not Path(cover_path).exists():
            self.cover_label.setText("No cover")
            return

        pixmap = QPixmap(cover_path)
        if pixmap.isNull():
            self.cover_label.setText("No cover")
            return

        scaled = pixmap.scaled(
            COVER_WIDTH,
            COVER_HEIGHT,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Crop to the exact cover box so every card lines up perfectly.
        x = max(0, (scaled.width() - COVER_WIDTH) // 2)
        y = max(0, (scaled.height() - COVER_HEIGHT) // 2)
        cropped = scaled.copy(x, y, COVER_WIDTH, COVER_HEIGHT)

        self._cover_pixmap = self._rounded(cropped, COVER_RADIUS)
        self._cover_zoomed = self._rounded(self._zoomed(cropped, 1.07), COVER_RADIUS)
        self._apply_cover(self._cover_zoomed if self._hovered else self._cover_pixmap)

    @staticmethod
    def _rounded(pixmap: QPixmap, radius: int) -> QPixmap:
        rounded = QPixmap(pixmap.size())
        rounded.fill(QColor(0, 0, 0, 0))
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        path = QPainterPath()
        path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        return rounded

    @staticmethod
    def _zoomed(pixmap: QPixmap, factor: float) -> QPixmap:
        width = int(pixmap.width() * factor)
        height = int(pixmap.height() * factor)
        scaled = pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (width - pixmap.width()) // 2
        y = (height - pixmap.height()) // 2
        return scaled.copy(x, y, pixmap.width(), pixmap.height())

    def _apply_cover(self, pixmap: QPixmap | None):
        if pixmap is None:
            return
        self.cover_label.setPixmap(pixmap)

    # ------------------------------------------------------------------
    # Hover
    # ------------------------------------------------------------------
    def enterEvent(self, event):
        self._hovered = True
        self._sync_select_circle()
        if self._selection_mode:
            # No per-card buttons while books are being picked.
            return
        # Show the buttons only after the pointer rests on the card, so a quick
        # click (or a Ctrl+click on the way to another book) is never swallowed.
        if not hasattr(self, "_hover_timer"):
            self._hover_timer = QTimer(self)
            self._hover_timer.setSingleShot(True)
            self._hover_timer.setInterval(220)
            self._hover_timer.timeout.connect(self._show_quick_actions)
        self._hover_timer.start()
        if self._cover_zoomed is not None:
            self._apply_cover(self._cover_zoomed)
        if self._shadow is None:
            from PyQt6.QtWidgets import QGraphicsDropShadowEffect

            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(30)
            effect.setOffset(0, 10)
            color = QColor("#000000")
            color.setAlpha(150)
            effect.setColor(color)
            self._shadow = effect
            self.setGraphicsEffect(effect)
        super().enterEvent(event)

    def _show_quick_actions(self):
        if self._hovered and self.isVisible() and not self._selection_mode:
            self.quick_bar.setVisible(True)

    def leaveEvent(self, event):
        self._hovered = False
        self._sync_select_circle()
        if hasattr(self, "_hover_timer"):
            self._hover_timer.stop()
        self.quick_bar.setVisible(False)
        if self._cover_pixmap is not None:
            self._apply_cover(self._cover_pixmap)
        if self._shadow is not None:
            self.setGraphicsEffect(None)
            self._shadow = None
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def set_selected(self, selected: bool):
        if self._selected == selected:
            self._sync_select_circle()
            return
        self._selected = selected
        self._sync_select_circle()
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def _sync_select_circle(self):
        """Show the corner circle when it is useful and fill it when picked."""
        circle = getattr(self, "select_circle", None)
        if circle is None:
            return
        circle.set_selected(self._selected)
        circle.setVisible(self._selected or self._selection_mode or self._hovered)
        if circle.isVisible():
            circle.raise_()

    def set_multi_selected(self, multi: bool):
        self._multi = bool(multi)

    def set_selection_mode(self, active: bool):
        """While the window is collecting a selection the card menu is hidden."""
        self._selection_mode = bool(active)
        if self._selection_mode and self.quick_bar is not None:
            self.quick_bar.hide()
        self._sync_select_circle()

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
        # While a selection is being built (or several cards are already
        # marked) the card only offers the group menu.
        if self._selection_mode or (self._selected and self._multi):
            self.bulk_context_requested.emit(self.book_id)
            return

        # Let the window make this card the selection anchor when needed.
        self.context_opened.emit(self.book_id)

        menu = QMenu(self)

        select_action = QAction("Select several books…", self)
        select_action.triggered.connect(
            lambda: self.select_mode_requested.emit(self.book_id)
        )
        menu.addAction(select_action)
        menu.addSeparator()

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
        self.title_label.setText(self._elided_title())
        self.info_label.setText(self._info_text())
        self.setToolTip(book_data.get("filepath", ""))
        self._refresh_state()

        if "custom_cover" in book_data:
            self._load_cover()

    # ------------------------------------------------------------------
    def sizeHint(self) -> QSize:
        return QSize(CARD_WIDTH, CARD_HEIGHT)
