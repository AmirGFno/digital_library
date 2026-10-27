"""Series info: the numbers, the metadata and the way in.

The navigation pane only had a name and a counter for each series. These tests
pin what the info page shows and that it is really reachable — from the "i"
button, the context menu and the Series menu.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _book(**overrides):
    book = {
        "title": "T",
        "filepath": "/library/T 01.cbz",
        "is_read": 0,
        "favorite": 0,
        "page_count": 20,
        "file_size": 1024,
        "year": 2020,
        "writer": "Writer",
        "publisher": "Publisher",
        "volume": "1",
        "created_at": "2026-01-02 10:00:00",
        "last_opened_at": None,
    }
    book.update(overrides)
    return book


def test_the_statistics_add_up_the_books():
    from ui.series_info_dialog import series_statistics

    books = [
        _book(is_read=1, page_count=10, file_size=100, year=2019,
              last_opened_at="2026-02-01 09:00:00"),
        _book(is_read=0, page_count=30, file_size=900, year=2023, favorite=1,
              filepath="/library/T 02.pdf", volume="2",
              writer="Someone else"),
        _book(is_read=0, filepath="/library/T 03.cbr", volume="3"),
    ]
    stats = series_statistics(books)

    assert stats["total"] == 3
    assert stats["read"] == 1
    assert stats["unread"] == 2
    assert stats["started"] == 1
    assert stats["favorites"] == 1
    assert stats["pages"] == 60
    assert stats["size"] == 2024
    assert stats["formats"] == {"CBZ": 1, "PDF": 1, "CBR": 1}
    assert stats["years"] == [2019, 2023, 2020]
    assert stats["last_read"].startswith("2026-02-01")
    assert stats["added"] == "2026-01-02 10:00:00"


def test_an_empty_series_has_no_numbers(qt_app):
    from ui import theme
    from ui.series_info_dialog import series_statistics

    theme.apply_theme(qt_app)
    stats = series_statistics([])

    assert stats["total"] == 0
    assert stats["unread"] == 0
    assert stats["formats"] == {}
    assert stats["last_read"] == ""


@pytest.fixture()
def series_db(tmp_path, monkeypatch):
    """A database with one series of three volumes and one unrelated book."""
    from database import Database

    database = Database(db_path=tmp_path / "info.db")
    series_id = database.create_series("Info Series")
    for index, extra in enumerate(
        (
            {"writer": "Ana", "publisher": "Pub", "year": 2018},
            {"writer": "Ana", "publisher": "Pub", "year": 2020},
            {"writer": "Bo", "publisher": "Pub", "year": 2022},
        ),
        start=1,
    ):
        path = tmp_path / f"Info {index:02d}.cbz"
        path.write_bytes(b"x" * (100 * index))
        book_id = database.add_book(
            str(path),
            title=f"Info {index}",
            series_id=series_id,
            volume=str(index),
            metadata={**extra, "page_count": 10 * index},
        )
        if index == 1:
            database.toggle_book_read(book_id)
    database.add_book(str(tmp_path / "Loose 01.cbz"), title="Loose", volume="1")

    for module_name in ("ui.series_info_dialog", "ui.series_panel"):
        module = __import__(module_name, fromlist=["db"])
        monkeypatch.setattr(module, "db", database)
    return database, series_id


def test_the_info_page_shows_the_series_numbers(qt_app, series_db):
    from ui import theme
    from ui.series_info_dialog import SeriesInfoDialog

    theme.apply_theme(qt_app)
    database, series_id = series_db
    dialog = SeriesInfoDialog(series_id)

    assert dialog.title.text() == "Info Series"
    assert dialog.progress_label.text().startswith("1 of 3 read")
    assert dialog.value_labels["Writer"].text().startswith("Ana")
    assert dialog.value_labels["Publisher"].text() == "Pub"
    assert dialog.value_labels["Years"].text() == "2018 – 2022"
    assert dialog.value_labels["Pages"].text() == "60"
    assert dialog.value_labels["Formats"].text() == "CBZ × 3"
    # A book outside the series never leaks into its numbers.
    assert dialog.stats["total"] == 3
    dialog.close()


def test_the_pane_offers_info_only_once_a_series_is_picked(qt_app, series_db):
    from ui import theme
    from ui.series_panel import SeriesPanel

    theme.apply_theme(qt_app)
    database, series_id = series_db
    panel = SeriesPanel()
    panel.show()
    for _ in range(4):
        qt_app.processEvents()

    assert not panel.info_btn.isEnabled()

    assert panel._select_series(series_id)
    panel._on_series_clicked(panel.series_list.currentItem())
    for _ in range(3):
        qt_app.processEvents()
    assert panel.info_btn.isEnabled()

    # A shelf is not a series: the button goes back to being unavailable.
    panel.quick_list.setCurrentRow(0)
    panel._on_shelf_clicked(panel.quick_list.item(0))
    assert not panel.info_btn.isEnabled()
    panel.close()


def test_the_series_menu_entry_follows_the_view(qt_app, series_db, monkeypatch):
    from PyQt6.QtCore import QSize

    from ui import layout, theme

    theme.apply_theme(qt_app)
    monkeypatch.setattr(layout, "screen_size", lambda widget=None: QSize(1400, 900))

    database, series_id = series_db
    import ui.main_window as main_window_module

    monkeypatch.setattr(main_window_module, "db", database)

    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    window.show()
    for _ in range(4):
        qt_app.processEvents()

    assert not window.series_info_action.isEnabled()
    window._on_series_selected(series_id)
    assert window.series_info_action.isEnabled()
    window._on_quick_filter("all")
    assert not window.series_info_action.isEnabled()
    window.close()
