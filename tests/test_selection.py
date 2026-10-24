"""The "pick several books" flow.

A plain click only opens one book's selection; the group selection starts from
the context menu ("Select several books…") and then grows card by card, while
the per-card menu stays out of the way.
"""
import os
import zipfile
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMenu

    from database import Database
    from importer import LibraryImporter, build_folder_plan_with_db
    from ui.theme import apply_theme

    apply_theme(qt_app)

    database = Database(db_path=tmp_path / "library.db")
    library = tmp_path / "Comics" / "Batman"
    library.mkdir(parents=True)
    for index in range(1, 5):
        with zipfile.ZipFile(library / f"Batman {index:03d}.cbz", "w") as archive:
            archive.writestr("001.jpg", os.urandom(64))
    LibraryImporter(database=database).import_plan(
        build_folder_plan_with_db(str(tmp_path / "Comics"), database=database, mode="auto")
    )

    import ui.main_window as main_window

    monkeypatch.setattr(main_window, "db", database)
    monkeypatch.setattr(
        main_window.settings, "get_library_root", lambda: str(tmp_path / "Comics")
    )
    # The real menus would block the test.
    shown = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *args, **kwargs: shown.append(self))

    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    window.resize(1400, 900)
    window.show()
    window._test_menus = shown
    from PyQt6.QtTest import QTest

    QTest.qWait(40)
    yield window
    window.close()


def _click(window, card, modifier=None):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    QTest.mouseClick(
        card.cover_label,
        Qt.MouseButton.LeftButton,
        modifier or Qt.KeyboardModifier.NoModifier,
        QPoint(20, 20),
    )
    QApplication.processEvents()
    return window.selected_ids


def _open_menu(window, card):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QContextMenuEvent

    window._test_menus.clear()
    card.contextMenuEvent(
        QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, QPoint(10, 10), card.mapToGlobal(QPoint(10, 10))
        )
    )
    return window._test_menus[-1]


def test_a_plain_click_selects_one_book_without_the_group_bar(window):
    first, second = window.book_cards[0], window.book_cards[1]

    assert _click(window, first) == {first.book_id}
    assert window._selection_mode is False
    assert not window.selection_bar.isVisible()

    assert _click(window, second) == {second.book_id}
    assert window._selection_mode is False


def test_the_context_menu_starts_the_selection(window):
    card = window.book_cards[0]
    menu = _open_menu(window, card)
    titles = [action.text() for action in menu.actions()]
    assert any("Select several" in title for title in titles)

    action = next(item for item in menu.actions() if "Select several" in item.text())
    action.trigger()

    assert window._selection_mode is True
    assert window.selected_ids == {card.book_id}
    assert window.selection_bar.isVisible()


def test_cards_are_added_one_by_one_and_offer_only_the_group_menu(window):
    cards = window.book_cards[:3]
    window._start_selection_mode(cards[0].book_id)

    assert _click(window, cards[1]) == {cards[0].book_id, cards[1].book_id}
    assert _click(window, cards[2]) == {card.book_id for card in cards}

    # Right-clicking now shows the group menu, never the card menu.
    menu = _open_menu(window, window.book_cards[3])
    titles = [action.text() for action in menu.actions()]
    assert any("3 books selected" in title for title in titles)
    assert not any("Select several" in title for title in titles)
    assert window.selected_ids == {card.book_id for card in cards}


def test_clicking_a_selected_card_removes_it(window):
    cards = window.book_cards[:3]
    window._start_selection_mode(cards[0].book_id)
    _click(window, cards[1])
    _click(window, cards[2])

    assert _click(window, cards[0]) == {cards[1].book_id, cards[2].book_id}


def test_clearing_ends_the_selection_mode(window):
    card = window.book_cards[0]
    window._start_selection_mode(card.book_id)
    window.clear_selection()

    assert window.selected_ids == set()
    assert window._selection_mode is False
    assert not window.selection_bar.isVisible()

    # and a single click keeps behaving like a single click
    assert _click(window, window.book_cards[1]) == {window.book_cards[1].book_id}
    assert window._selection_mode is False


# ------------------------------------------------------- corner circle
def _hover(card):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QEnterEvent
    from PyQt6.QtWidgets import QApplication

    card.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    QApplication.processEvents()


def _click_circle(window, card):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    QTest.mouseClick(
        card.select_circle,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(11, 11),
    )
    QApplication.processEvents()
    return window.selected_ids


def test_the_circle_only_appears_on_hover(window):
    cards = window.book_cards[:3]
    assert not any(card.select_circle.isVisible() for card in cards)

    _hover(cards[0])

    assert cards[0].select_circle.isVisible()
    assert not cards[0].select_circle.is_selected()
    assert not cards[1].select_circle.isVisible()


def test_clicking_the_circle_fills_it_and_starts_the_selection(window):
    card = window.book_cards[0]
    _hover(card)

    _click_circle(window, card)

    assert window.selected_ids == {card.book_id}
    assert window._selection_mode is True
    assert card.select_circle.is_selected()
    assert window.selection_bar.isVisible()


def test_every_card_offers_a_hollow_circle_while_selecting(window):
    first, second, third = window.book_cards[:3]
    _click_circle(window, first)

    for card in (first, second, third):
        assert card.select_circle.isVisible()
    assert first.select_circle.is_selected()
    assert not second.select_circle.is_selected()
    assert not third.select_circle.is_selected()

    _click_circle(window, second)
    assert window.selected_ids == {first.book_id, second.book_id}
    assert second.select_circle.is_selected()

    _click_circle(window, second)
    assert window.selected_ids == {first.book_id}
    assert not second.select_circle.is_selected()


def test_select_all_fills_every_circle_and_clearing_empties_them(window):
    window.select_all()
    from PyQt6.QtWidgets import QApplication

    QApplication.processEvents()
    cards = window.book_cards
    assert cards and all(card.select_circle.is_selected() for card in cards)
    assert all(card.select_circle.isVisible() for card in cards)

    window.clear_selection()
    QApplication.processEvents()

    assert not any(card.select_circle.is_selected() for card in cards)
    assert not any(card.select_circle.isVisible() for card in cards)


def test_the_filled_circle_is_drawn_with_a_white_tick(qt_app):
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtWidgets import QWidget

    from ui.book_card import SelectCircle
    from ui import theme

    # A parent keeps the button from becoming a top-level window that would
    # paint its own background over the snapshot.
    parent = QWidget()
    circle = SelectCircle(parent, diameter=22)
    circle.set_selected(True)

    image = QImage(22, 22, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    circle.render(painter)
    painter.end()

    accent = theme.ACCENT.lower()
    # The button paints its background, so the corners show the theme colour
    # instead of the accent: the shape really is a circle.
    assert image.pixelColor(0, 0).name().lower() == theme.BG.lower()
    assert image.pixelColor(11, 4).name().lower() == accent  # the body is filled

    white = [
        (x, y)
        for x in range(22)
        for y in range(22)
        if (color := image.pixelColor(x, y)).red() > 235
        and color.green() > 235
        and color.blue() > 235
    ]
    assert len(white) >= 8  # a drawn tick, not a dot
    # the tick runs from the lower-left towards the upper-right
    assert min(x for x, _ in white) < 11 < max(x for x, _ in white)
    assert min(y for _, y in white) < 11 < max(y for _, y in white)

    hollow = SelectCircle(parent, diameter=22)
    image.fill(0)
    painter = QPainter(image)
    hollow.render(painter)
    painter.end()
    # A hollow circle keeps its middle empty and only paints the ring.
    assert image.pixelColor(11, 11).name().lower() == theme.BG.lower()
    ring = [
        (x, y)
        for x in range(22)
        for y in range(22)
        if (color := image.pixelColor(x, y)).red() > 230
        and color.green() > 230
        and color.blue() > 230
    ]
    assert ring and min(x for x, _ in ring) < 4 and max(x for x, _ in ring) > 17
