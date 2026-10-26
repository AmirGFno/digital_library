"""
The book grid with rubber-band selection.

``QGridLayout`` alone cannot select several cards, so the container widget draws a
rubber band while the mouse is dragged over empty space and reports the cards it
touched. Combined with Ctrl/Shift clicks on the cards themselves this gives the
usual file-manager selection behaviour.
"""
from __future__ import annotations

from typing import Iterable, List

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QRubberBand, QWidget

from ui.book_card import BookCard


class LibraryGrid(QWidget):
    """Grid of :class:`BookCard` widgets supporting rubber-band selection."""

    empty_area_clicked = pyqtSignal()
    rubber_band_finished = pyqtSignal(list, bool)  # book ids, additive

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LibraryGrid")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._layout = QGridLayout(self)
        self._layout.setSpacing(14)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        self._band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._origin: QPoint | None = None
        self._additive = False

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------
    @property
    def grid_layout(self) -> QGridLayout:
        return self._layout

    def clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def add_card(self, card: BookCard, row: int, column: int):
        self._layout.addWidget(card, row, column)

    def set_centered(self, centered: bool):
        """Centre a lone empty-state widget instead of pinning it top-left."""
        self._layout.setAlignment(
            Qt.AlignmentFlag.AlignTop
            | (Qt.AlignmentFlag.AlignHCenter if centered else Qt.AlignmentFlag.AlignLeft)
        )

    def cards(self) -> List[BookCard]:
        result = []
        for index in range(self._layout.count()):
            widget = self._layout.itemAt(index).widget()
            if isinstance(widget, BookCard):
                result.append(widget)
        return result

    def fill(self, cards: Iterable[BookCard], columns: int):
        """Place *cards* row by row using *columns* columns."""
        self.clear()
        for index, card in enumerate(cards):
            row, column = divmod(index, max(1, columns))
            self.add_card(card, row, column)

    # ------------------------------------------------------------------
    # Rubber band
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.childAt(event.position().toPoint()) is None:
            self._origin = event.position().toPoint()
            self._additive = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self._band.setGeometry(QRect(self._origin, self._origin))
            self._band.show()
            if not self._additive:
                self.empty_area_clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            rect = QRect(self._origin, event.position().toPoint()).normalized()
            self._band.setGeometry(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._origin is not None and event.button() == Qt.MouseButton.LeftButton:
            rect = QRect(self._origin, event.position().toPoint()).normalized()
            self._band.hide()
            self._origin = None
            if rect.width() > 3 or rect.height() > 3:
                selected = [
                    card.book_id
                    for card in self.cards()
                    if rect.intersects(card.geometry())
                ]
                if selected:
                    self.rubber_band_finished.emit(selected, self._additive)
            event.accept()
            return
        super().mouseReleaseEvent(event)
