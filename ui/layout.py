"""Window sizes that respect the screen they open on.

Most "the window does not fit" reports come from fixed minimum sizes. A dialog
that demands 900x680 cannot open on a 1366x768 laptop at 125 % scaling, where
Windows leaves roughly 1090x610 of usable space: the action buttons end up
under the taskbar and there is no way to reach them.

Every window built here asks this module for a size instead:

* the size is clamped to the screen's available area, and
* when the content is still taller than the screen, the middle of the dialog
  goes into a scroll area while its header and its buttons stay in place.
"""
from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Taskbar, window frame and a little breathing room, in device independent px.
MARGIN = 32
# Never squeeze a window below this, even on a tiny screen.
ABSOLUTE_MIN = QSize(360, 300)


def screen_size(widget: Optional[QWidget] = None) -> QSize:
    """Usable area of the screen ``widget`` is (or will be) shown on."""
    screen = widget.screen() if widget is not None else None
    if screen is None:
        screen = QApplication.primaryScreen()
    if screen is None:
        return QSize(1280, 800)
    return screen.availableGeometry().size()


def fitted_size(preferred: QSize, room: QSize) -> QSize:
    """``preferred`` shrunk to fit ``room`` (leaving :data:`MARGIN` free)."""
    usable_width = max(ABSOLUTE_MIN.width(), room.width() - MARGIN)
    usable_height = max(ABSOLUTE_MIN.height(), room.height() - MARGIN)
    return QSize(min(preferred.width(), usable_width), min(preferred.height(), usable_height))


def clamp_window(
    window: QWidget,
    preferred: QSize,
    minimum: QSize = ABSOLUTE_MIN,
    available: Optional[QSize] = None,
) -> QSize:
    """Give ``window`` a minimum and a starting size that both fit the screen.

    Returns the size the window was given, which is handy for tests. The
    minimum is clamped as well: a fixed minimum larger than the screen is what
    pushes buttons out of reach in the first place.
    """
    room = available or screen_size(window)
    smallest = fitted_size(minimum, room)
    target = fitted_size(preferred, room)
    # A window can never be told to start smaller than its own minimum.
    target = QSize(
        max(target.width(), smallest.width()),
        max(target.height(), smallest.height()),
    )
    window.setMinimumSize(smallest)
    window.resize(target)
    return target


def wrap_in_scroll(body: QWidget) -> QScrollArea:
    """A frameless scroll area that expands ``body`` instead of clipping it."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(body)
    scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    return scroll


def make_scrollable(
    dialog: QWidget,
    keep_first: int = 0,
    keep_last: int = 0,
) -> Optional[QScrollArea]:
    """Scroll the middle of a dialog, keeping its header and buttons fixed.

    ``keep_first`` items at the top and ``keep_last`` items at the bottom stay
    where they are - the buttons of a dialog are normally the last item, and
    they must never scroll out of reach.
    """
    outer = dialog.layout()
    if outer is None:
        return None
    movable = outer.count() - keep_first - keep_last
    if movable <= 0:
        return None

    body = QWidget(dialog)
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(outer.spacing())
    for _ in range(movable):
        stretch = outer.stretch(keep_first)
        item = outer.takeAt(keep_first)
        if item is None:
            break
        if item.widget() is not None:
            body_layout.addWidget(item.widget())
        elif item.spacerItem() is not None:
            body_layout.addItem(item)
        else:
            # A bare QLayout keeps the old parent widget when it is moved, so
            # its children would be laid out over the dialog instead of over
            # the scroll area. Dialogs must put that part in a QWidget.
            raise ValueError(
                "make_scrollable can only move widgets; wrap this layout in "
                "a QWidget first"
            )
        body_layout.setStretch(body_layout.count() - 1, stretch)

    scroll = wrap_in_scroll(body)
    outer.insertWidget(keep_first, scroll, 1)
    return scroll


def finish_dialog(
    dialog: QWidget,
    preferred: QSize,
    minimum: QSize = ABSOLUTE_MIN,
    keep_first: int = 0,
    keep_last: int = 1,
    available: Optional[QSize] = None,
) -> QScrollArea:
    """Fit a freshly built dialog to the screen and let its body scroll."""
    scroll = make_scrollable(dialog, keep_first=keep_first, keep_last=keep_last)
    clamp_window(dialog, preferred, minimum, available=available)
    return scroll


def oversized_widgets(window: QWidget, skip_scroll: bool = True) -> List[QWidget]:
    """Visible children that stick out of ``window`` - a layout bug detector.

    Children of a :class:`QScrollArea` are skipped by default: they are *meant*
    to live below the visible edge and are reachable by scrolling.
    """
    from PyQt6.QtWidgets import QAbstractScrollArea

    inside_scroll = set()
    if skip_scroll:
        for area in window.findChildren(QAbstractScrollArea):
            for child in area.findChildren(QWidget):
                inside_scroll.add(child)

    offenders: List[QWidget] = []
    bounds = window.rect()
    for child in window.findChildren(QWidget):
        if child is window or child in inside_scroll:
            continue
        if not child.isVisible() or child.width() <= 0 or child.height() <= 0:
            continue
        top_left = child.mapTo(window, child.rect().topLeft())
        if top_left.x() < 0 or top_left.y() < 0:
            continue
        if top_left.x() + child.width() > bounds.width() + 1:
            offenders.append(child)
        elif top_left.y() + child.height() > bounds.height() + 1:
            offenders.append(child)
    return offenders
