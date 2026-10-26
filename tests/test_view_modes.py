"""The Windows-style shell: two views, two colour modes, one selection.

The user asked for an interface that looks like a real Windows program. These
tests pin the parts that make that promise concrete: the cover grid and the
Explorer-style list show the same books, the choice survives a restart, the
light and dark palettes both build, and switching a view never loses what is
selected.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def app_theme(qt_app):
    from ui.theme import apply_theme

    apply_theme(qt_app, "light")
    return qt_app


@pytest.fixture()
def window(qt_app, tmp_path, monkeypatch):
    """A real main window over a small private database."""
    from database import Database
    from ui.main_window import MainWindow
    from utils.settings import settings

    # The window restores the filters of the previous session, so pin them:
    # otherwise the developer's own settings decide what these tests see.
    saved_view = {
        key: settings.get_view(key)
        for key in ("filter", "format", "favorites_only", "view_mode", "sort")
    }
    settings.set_many_view(
        {
            "filter": "all",
            "format": "all",
            "favorites_only": False,
            "view_mode": "grid",
            "sort": "series",
        }
    )

    database = Database(db_path=tmp_path / "view-modes.db")
    series_id = database.create_series("View Modes", str(tmp_path / "View Modes"))
    for volume in range(1, 4):
        database.add_book(
            str(tmp_path / f"View Modes {volume:02d}.cbz"),
            title=f"View Modes {volume}",
            series_id=series_id,
            volume=str(volume),
            metadata={"writer": "Test Author", "year": "2024", "page_count": 40},
        )

    built = MainWindow(run_startup=False)
    # Every module keeps its own name for the shared database handle.
    for module_name in (
        "ui.main_window",
        "ui.series_panel",
        "ui.details_dialog",
        "ui.dialogs",
        "ui.stats_dialog",
        "ui.restore_dialog",
    ):
        module = __import__(module_name, fromlist=["db"])
        if hasattr(module, "db"):
            monkeypatch.setattr(module, "db", database)
    monkeypatch.setattr(built, "_db", database, raising=False)
    built.refresh_books()
    built.show()
    for _ in range(4):
        qt_app.processEvents()
    yield built
    built.close()
    for key, value in saved_view.items():
        if value is not None:
            settings.set_view(key, value)


def test_the_window_opens_with_a_windows_menu_bar(window):
    titles = [action.text() for action in window.menuBar().actions()]
    assert titles[:3] == ["&File", "&Library", "&Edit"]
    assert "&View" in titles


def test_the_grid_and_the_list_show_the_same_books(window, qt_app):
    window._set_view_mode("grid")
    for _ in range(4):
        qt_app.processEvents()
    assert window.view_stack.currentIndex() == 0
    cards = len(window.book_cards)
    assert cards == 3

    window._set_view_mode("details")
    for _ in range(4):
        qt_app.processEvents()
    assert window.view_stack.currentIndex() == 1
    assert window.books_table.isVisible()
    assert window.books_table.book_count() == 3
    # The list carries every column a desktop file list carries.
    header = window.books_table.horizontalHeader()
    model = window.books_table.model()
    titles = [
        model.headerData(column, __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.Orientation.Horizontal)
        for column in range(model.columnCount())
    ]
    assert titles[0] == "Title" and "Pages" in titles and "Status" in titles
    assert header.count() == len(titles)


def test_the_view_choice_is_remembered(window, tmp_path):
    from utils.settings import settings

    window._set_view_mode("details")
    assert settings.get_view("view_mode") == "details"
    window._set_view_mode("grid")
    assert settings.get_view("view_mode") == "grid"


def test_switching_the_view_keeps_the_selection(window, qt_app):
    window._set_view_mode("details")
    for _ in range(4):
        qt_app.processEvents()
    book_ids = [book["id"] for book in window.books][:2]
    # Select the way a user does (click / Ctrl+click), so the window hears
    # about it: ``select_ids`` is the quiet path used when the window itself
    # pushes a selection into the list.
    selection = window.books_table.selectionModel()
    table = window.books_table
    flag = (
        selection.SelectionFlag.Select | selection.SelectionFlag.Rows
    )
    for row in range(2):
        selection.select(table.model().index(row, 0), flag)
    for _ in range(4):
        qt_app.processEvents()

    assert set(window.selected_ids) == set(book_ids)

    window._set_view_mode("grid")
    for _ in range(4):
        qt_app.processEvents()
    selected_cards = {card.book_id for card in window.book_cards if card.is_selected}
    assert selected_cards == set(book_ids)


def test_a_row_double_click_opens_the_book(window, qt_app, monkeypatch):
    opened = []
    # The launch itself is stubbed: the point here is the wiring from the
    # list to the window, not the external reader.
    monkeypatch.setattr(window, "_launch", lambda book_id, reader_id=None: opened.append(book_id))
    window._set_view_mode("details")
    for _ in range(4):
        qt_app.processEvents()

    first = window.books_table.model().index(0, 0)
    window.books_table.doubleClicked.emit(first)
    assert opened == [window.books[0]["id"]]


def test_an_empty_library_shows_the_empty_page(window, qt_app, monkeypatch):
    from database import Database

    empty = Database(db_path=Path(window.books[0]["filepath"]).parent / "empty.db")
    monkeypatch.setattr("ui.main_window.db", empty)
    window.refresh_books()
    for _ in range(4):
        qt_app.processEvents()
    assert window.view_stack.currentIndex() == 2
    assert window.books_table.book_count() == 0


def test_both_palettes_build_a_full_stylesheet(qt_app):
    from ui import theme

    for mode in ("light", "dark"):
        assert theme.apply_theme(qt_app, mode) == mode
        assert len(theme.build_stylesheet()) > 5000
        # Windows 11 values: a neutral window and exactly one accent.
        if mode == "light":
            assert theme.BG.lower() == "#f3f3f3"
            assert theme.TEXT.lower() == "#1a1a1a"
        else:
            assert theme.BG.lower() == "#202020"
            assert theme.TEXT.lower() == "#ffffff"
        assert theme.ACCENT.lower() in theme.build_stylesheet().lower()


def test_the_theme_menu_offers_light_dark_and_system(window):
    labels = [action.text() for action in window.theme_group.actions()]
    assert labels == ["Follow Windows", "Light", "Dark"]
    assert any(action.isChecked() for action in window.theme_group.actions())


def test_choosing_a_theme_stores_it(window):
    from utils.settings import settings

    window._change_theme("dark")
    assert settings.get_view("theme") == "dark"


def test_the_navigation_pane_shelves_filter_the_library(window, qt_app):
    window._activate_shelf("unread")
    for _ in range(4):
        qt_app.processEvents()
    assert window.read_filter_combo.currentData() == "unread"
    assert window.series_panel.subtitle.text() == "Unread"

    window._activate_shelf("all")
    for _ in range(4):
        qt_app.processEvents()
    assert window.read_filter_combo.currentData() == "all"


def test_a_shelf_pick_clears_the_series_filter(window, qt_app):
    window.current_series_filter = 7
    window._on_quick_filter("favorites")
    for _ in range(4):
        qt_app.processEvents()
    assert window.current_series_filter is None
    assert window.favorites_button.isChecked()


def test_the_details_list_survives_a_sort_click(window, qt_app):
    window._set_view_mode("details")
    for _ in range(4):
        qt_app.processEvents()
    assert window.books_table.book_count() == 3
    ids_before = set(window.books_table.selected_ids())
    header = window.books_table.horizontalHeader()
    window.books_table._on_header_clicked(6)  # Pages
    for _ in range(4):
        qt_app.processEvents()
    assert window.books_table.book_count() == 3
    assert set(window.books_table.selected_ids()) == ids_before
