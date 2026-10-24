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
