"""
Small building blocks of the interface.

Kept separate from the window so the dashboard, the sidebar and the dialogs can
share the same visual language: chips, icon buttons, toasts and the floating
selection bar.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

from PyQt6 import sip
from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui import theme


# ---------------------------------------------------------------- primitives
class Chip(QLabel):
    """A small rounded label used for counts and states."""

    def __init__(self, text: str = "", color: str = theme.TEXT_MUTED,
                 background: str = theme.SURFACE, parent=None):
        super().__init__(text, parent)
        self.setObjectName("ChipLabel")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_color(color, background)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_color(self, color: str, background: Optional[str] = None):
        background = background or theme.SURFACE
        self.setStyleSheet(
            f"QLabel#ChipLabel {{ color: {color}; background-color: {background};"
            " border-radius: 8px; padding: 2px 8px; font-size: 11px;"
            " font-weight: 600; }}"
        )


class IconButton(QToolButton):
    """Flat, rounded icon button with an optional tooltip."""

    def __init__(self, text: str = "", tooltip: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("IconButton")
        self.setText(text)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        # Only the height is fixed: a wider glyph (or a bigger Windows text
        # scale) must not be cut in half.
        self.setFixedHeight(32)
        self.setMinimumWidth(32)
        self.setStyleSheet("font-size: 15px;")


class Divider(QFrame):
    """A hairline separator."""

    def __init__(self, horizontal: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("Divider")
        if horizontal:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedWidth(1)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background-color: {theme.BORDER_SOFT}; border: none;")


class StatCard(QFrame):
    """A compact metric tile: icon, value and caption."""

    clicked = pyqtSignal()

    def __init__(self, icon: str, caption: str, accent: str = theme.ACCENT, parent=None):
        super().__init__(parent)
        self.setObjectName("Chip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accent = accent

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 7, 13, 7)
        layout.setSpacing(9)

        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"color: {accent}; font-size: 15px;")
        layout.addWidget(icon_label)

        text_box = QVBoxLayout()
        text_box.setSpacing(0)
        self.value_label = QLabel("0")
        self.value_label.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 14px; font-weight: 700;"
        )
        caption_label = QLabel(caption)
        caption_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px;"
        )
        text_box.addWidget(self.value_label)
        text_box.addWidget(caption_label)
        layout.addLayout(text_box)

    def set_value(self, value) -> None:
        self.value_label.setText(str(value))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class Banner(QFrame):
    """Gradient panel with a title, subtitle and optional action buttons."""

    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName("HeroBar")
        self.setFixedHeight(76)
        self.setStyleSheet(
            "QFrame#HeroBar {"
            f" background-color: {theme.BG_ELEVATED};"
            f" border-bottom: 1px solid {theme.BORDER_SOFT};"
            "}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)

        self.logo = QLabel()
        self.logo.setFixedSize(44, 44)
        self.logo.setPixmap(theme.gradient_pixmap(44, 44, theme.ACCENT, "#ff9a62", 14))
        layout.addWidget(self.logo)

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("HeroTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("MutedLabel")
        text_box.addWidget(self.title_label)
        text_box.addWidget(self.subtitle_label)
        layout.addLayout(text_box)
        layout.addStretch(1)

    def add_widget(self, widget: QWidget):
        layout = self.layout()
        layout.addWidget(widget)


# ---------------------------------------------------------------- toasts
def is_alive(widget: Optional[QWidget]) -> bool:
    """True while the C++ object behind a widget still exists.

    Calling any method of a widget that was already deleted with
    ``deleteLater()`` raises ``RuntimeError``; this check keeps references held
    in Python (queues, managers) safe.
    """
    return widget is not None and not sip.isdeleted(widget)


class Toast(QFrame):
    """Transient notification that fades in at the bottom of its parent."""

    closed = pyqtSignal()

    def __init__(self, parent: QWidget, text: str, kind: str = "info",
                 msecs: int = 4200):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QFrame#Toast {"
            f" background-color: {theme.SURFACE_ACTIVE};"
            f" border: 1px solid {theme.BORDER_STRONG};"
            " border-radius: 14px;"
            "}"
        )
        theme.add_shadow(self, blur=34, y_offset=10, alpha=200)

        accent = {
            "info": theme.BLUE,
            "success": theme.GREEN,
            "warning": theme.GOLD,
            "error": theme.ACCENT,
        }.get(kind, theme.BLUE)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        bar = QFrame()
        bar.setFixedWidth(3)
        bar.setStyleSheet(f"background-color: {accent}; border-radius: 2px;")
        layout.addWidget(bar)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px;")
        layout.addWidget(label, 1)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)

        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setFixedWidth(min(420, max(240, parent.width() - 80)))
        self.adjustSize()
        self._msecs = msecs
        self._closing = False
        self._closed = False

        # Timers owned by the toast disappear together with it, so a queued
        # callback can never run against a deleted C++ object.
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show_animated)
        self._show_timer.start(20)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_animated)

        self._animation.finished.connect(self._finished)

    def _show_animated(self):
        if self._closing or not is_alive(self):
            return
        self._reposition()
        self.show()
        self.raise_()
        self._animation.stop()
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.start()
        self._hide_timer.start(self._msecs)

    def _hide_animated(self):
        if self._closing or not is_alive(self):
            return
        self._closing = True
        try:
            self._animation.stop()
            self._animation.setStartValue(self._effect.opacity())
            self._animation.setEndValue(0.0)
            self._animation.start()
        except RuntimeError:
            self._finished()

    def _finished(self):
        if self._closing and not self._closed and is_alive(self):
            self._closed = True
            self.closed.emit()
            self.deleteLater()

    def dismiss(self):
        """Remove the toast right away (used when too many are on screen)."""
        if not is_alive(self):
            return
        self._show_timer.stop()
        self._hide_timer.stop()
        self._animation.stop()
        self._closing = True
        self.hide()
        self._finished()

    def _reposition(self):
        parent = self.parentWidget()
        if parent is None or not is_alive(parent):
            return
        margin = 22
        x = max(margin, (parent.width() - self.width()) // 2)
        y = parent.height() - self.height() - 58
        self.move(x, y)


class ToastManager:
    """Keeps at most three toasts stacked above each other."""

    MAX_VISIBLE = 3

    def __init__(self, parent: QWidget):
        self.parent = parent
        self._toasts: list[Toast] = []

    def _forget(self, toast: Toast):
        """Drop a toast that closed (or whose window was destroyed)."""
        self._toasts = [item for item in self._toasts if item is not toast]

    def _visible_toasts(self) -> list[Toast]:
        alive = []
        for item in self._toasts:
            try:
                if is_alive(item) and item.isVisible():
                    alive.append(item)
            except RuntimeError:
                continue
        self._toasts = alive
        return alive

    def show(self, text: str, kind: str = "info", msecs: int = 4200):
        parent = self.parent
        if not is_alive(parent):
            return None
        toast = Toast(parent, text, kind=kind, msecs=msecs)
        existing = self._visible_toasts()
        while len(existing) >= self.MAX_VISIBLE:
            existing.pop(0).dismiss()
        offset = 52 * len(existing)
        self._toasts.append(toast)
        toast.closed.connect(lambda item=toast: self._forget(item))
        original = toast._reposition

        def reposition():
            if not is_alive(toast):
                return
            original()
            toast.move(toast.x(), toast.y() - offset)

        toast._reposition = reposition
        return toast


# ---------------------------------------------------------------- selection bar
class SelectionBar(QFrame):
    """Floating action bar shown while several books are selected."""

    open_requested = pyqtSignal()
    read_requested = pyqtSignal(bool)
    favorite_requested = pyqtSignal(bool)
    series_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SelectionBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(56)
        self.setMinimumWidth(300)
        theme.add_shadow(self, blur=40, y_offset=12, alpha=220)

        self._layout = QHBoxLayout(self)
        layout = self._layout
        layout.setContentsMargins(16, 8, 12, 8)
        layout.setSpacing(8)

        self.count_label = QLabel("0 selected")
        self.count_label.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: 700; font-size: 13px;"
            " background: transparent;"
        )
        layout.addWidget(self.count_label)
        layout.addSpacing(6)
        layout.addWidget(Divider(horizontal=False))
        layout.addSpacing(6)

        def add_button(text: str, slot, object_name: str = ""):
            button = QPushButton(text)
            if object_name:
                button.setObjectName(object_name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton { background: transparent; border: 1px solid transparent;"
                f" color: {theme.TEXT_MUTED}; padding: 6px 11px; border-radius: 9px; }}"
                f"QPushButton:hover {{ background: {theme.SURFACE_HOVER}; color: {theme.TEXT}; }}"
            )
            button.clicked.connect(slot)
            layout.addWidget(button)
            return button

        # Each entry keeps its full label and its short form: on a narrow
        # window the icons alone are used so that no button is cut in half.
        self._buttons = []
        for full, short, slot in (
            ("▶  Open", "▶", self.open_requested.emit),
            ("✓  Read", "✓", lambda: self.read_requested.emit(True)),
            ("↺  Unread", "↺", lambda: self.read_requested.emit(False)),
            ("★  Favorite", "★", lambda: self.favorite_requested.emit(True)),
            ("☰  Series", "☰", self.series_requested.emit),
        ):
            button = add_button(full, slot)
            button.setToolTip(full.replace("  ", " "))
            self._buttons.append((button, full, short))
        layout.addStretch(1)

        close = QToolButton()
        close.setText("✕")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            "QToolButton { border: none; color: %s; font-size: 14px; padding: 4px; }"
            "QToolButton:hover { color: %s; }" % (theme.TEXT_DIM, theme.TEXT)
        )
        close.clicked.connect(self.clear_requested.emit)
        layout.addWidget(close)

    def set_count(self, count: int):
        self.count_label.setText(f"{count} selected")
        self.count_label.setToolTip(f"{count} selected")

    def use_compact_labels(self, compact: bool):
        """Shorten the buttons so the bar fits a narrow window."""
        for button, full, short in getattr(self, "_buttons", []):
            if button.text() != (short if compact else full):
                button.setText(short if compact else full)
                button.updateGeometry()
        self.updateGeometry()

    def sizeHint(self):  # noqa: N802 - Qt API
        """The width the current labels need - never the cached one.

        ``super().sizeHint()`` is not refreshed after the labels change, and
        the window compares the two to decide when to shorten them.
        """
        hint = super().sizeHint()
        widths = [self.count_label.sizeHint().width()]
        widths += [button.sizeHint().width() for button, _full, _short in self._buttons]
        margins = self._layout.contentsMargins()
        spacing = self._layout.spacing() * (len(widths) + 3)
        return QSize(
            sum(widths) + margins.left() + margins.right() + spacing + 40,
            hint.height(),
        )


# ---------------------------------------------------------------- empty state
class EmptyState(QWidget):
    """Friendly placeholder shown when the library or a filter is empty."""

    add_requested = pyqtSignal()
    folder_requested = pyqtSignal()

    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 60, 40, 60)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        art = QLabel()
        art.setPixmap(self._artwork())
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(art)

        heading = QLabel(title)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 19px; font-weight: 700;"
        )
        layout.addWidget(heading)

        description = QLabel(subtitle)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        description.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 13px;")
        layout.addWidget(description)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)

        add_button = QPushButton("Add comics")
        add_button.setObjectName("PrimaryButton")
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.clicked.connect(self.add_requested.emit)

        folder_button = QPushButton("Import a folder")
        folder_button.setObjectName("GhostButton")
        folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_button.clicked.connect(self.folder_requested.emit)

        buttons.addWidget(add_button)
        buttons.addWidget(folder_button)
        layout.addSpacing(6)
        layout.addLayout(buttons)

    @staticmethod
    def _artwork() -> QPixmap:
        pixmap = QPixmap(150, 96)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = ["#1c2330", "#242c3c", "#2d3648"]
        for index, color in enumerate(colors):
            x = 18 + index * 30
            y = 12 + index * 6
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(x, y, 56, 74, 9, 9)
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawRoundedRect(66, 20, 56, 74, 9, 9)
        painter.end()
        return pixmap


# ---------------------------------------------------------------- helpers
def title_font(size: int, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    font = QFont()
    font.setPointSize(size)
    font.setWeight(weight)
    return font


def elide(text: str, limit: int = 42) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def workspace_badge(format_name: str) -> Tuple[str, str]:
    """Return (label, colour) for a file format badge."""
    value = format_name.upper().lstrip(".")
    color = {
        "CBZ": theme.BLUE,
        "CBR": theme.ACCENT,
        "CB7": theme.VIOLET,
        "CBT": theme.GOLD,
        "PDF": "#f87171",
    }.get(value, theme.TEXT_MUTED)
    return value, color


def join_actions(actions: Sequence[QPushButton], parent: QWidget) -> QWidget:
    """Lay a number of actions out horizontally (used by dialogs)."""
    holder = QWidget(parent)
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for action in actions:
        layout.addWidget(action)
    return holder


def set_size(widget: QWidget, width: int, height: int) -> QWidget:
    widget.setFixedSize(QSize(width, height))
    return widget


def visible_widgets(widgets: Iterable[QWidget]) -> list:
    return [widget for widget in widgets if widget is not None and widget.isVisible()]
