"""Every window must fit the screen it opens on.

The user reported a dialog whose buttons sat below the taskbar on a laptop and a
main window whose header was cut off. These tests build the real widgets with a
simulated small screen and check three things:

* the window never demands more space than the screen offers,
* no control is pushed outside its window,
* the action buttons stay visible even when the body has to scroll.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SMALL = (1092, 614)      # a 1366x768 laptop at 125 % scaling
TINY = (872, 470)        # a 1024x600 netbook


@pytest.fixture(autouse=True)
def app_theme(qt_app):
    """The real stylesheet: it changes the width of every combo box."""
    from ui.theme import apply_theme

    apply_theme(qt_app)
    return qt_app


@pytest.fixture()
def screen(monkeypatch):
    """Pin the screen size the windows see (the dialogs ask ui.layout)."""
    from PyQt6.QtCore import QSize

    from ui import layout

    def pin(width, height):
        monkeypatch.setattr(layout, "screen_size", lambda widget=None: QSize(width, height))

    pin(*SMALL)
    return pin


@pytest.fixture()
def sample(tmp_path, monkeypatch):
    """One database with one book, shared by every dialog in this module."""
    from database import Database

    database = Database(db_path=tmp_path / "layout.db")
    series_id = database.create_series("Layout")
    book_id = database.add_book(
        str(tmp_path / "Layout 01.cbz"), title="Layout 1", series_id=series_id
    )

    return database, book_id


def _dialogs(database, book_id, tmp_path):
    """Every dialog the app can open, built with harmless dummy data."""
    from utils import updater
    from ui.dialogs import AddBookDialog, AddSeriesDialog, ConfirmDialog
    from ui.details_dialog import DetailsDialog
    from ui.folder_import_dialog import FolderImportDialog
    from ui.name_preview_dialog import NamePreviewDialog
    from ui.new_folder_dialog import NewFolderDialog
    from ui.reader_settings_dialog import CustomReaderDialog, ReaderSettingsDialog
    from ui.restore_dialog import RestoreSeriesDialog
    from ui.stats_dialog import StatisticsDialog
    from ui.update_dialog import UpdateDialog
    from ui.welcome_dialog import WelcomeDialog

    plan = updater.UpdatePath(
        target="9.9.9",
        steps=[
            updater.UpdateInfo(
                version="9.9.9",
                tag="v9.9.9",
                notes="• A change\n• Another change",
                page_url=updater.RELEASE_PAGE,
                asset_url="https://example.test/update.zip",
                asset_name="update.zip",
                asset_size=4_000_000,
                checksum_url="",
                from_version="9.9.8",
            )
        ],
    )

    return [
        ("AddBookDialog", lambda: AddBookDialog()),
        ("AddSeriesDialog", lambda: AddSeriesDialog()),
        ("ConfirmDialog", lambda: ConfirmDialog("Title", "Question?", "Yes")),
        ("DetailsDialog", lambda: DetailsDialog(book_id)),
        ("ReaderSettingsDialog", lambda: ReaderSettingsDialog()),
        ("CustomReaderDialog", lambda: CustomReaderDialog()),
        ("StatisticsDialog", lambda: StatisticsDialog()),
        ("RestoreSeriesDialog", lambda: RestoreSeriesDialog()),
        ("WelcomeDialog", lambda: WelcomeDialog()),
        ("NamePreviewDialog", lambda: NamePreviewDialog([str(tmp_path / "Some 01 [FA].cbz")])),
        ("NewFolderDialog", lambda: NewFolderDialog([str(tmp_path / "Comics")], None)),
        ("FolderImportDialog", lambda: FolderImportDialog(None, folder=str(tmp_path))),
        ("UpdateDialog", lambda: UpdateDialog(plan)),
    ]


def _show(app, widget, width=None, height=None):
    if width is not None:
        widget.resize(width, height)
    widget.show()
    for _ in range(4):
        app.processEvents()
    return widget


def test_every_dialog_fits_a_laptop_screen(qt_app, screen, tmp_path, sample, monkeypatch):
    from ui import layout

    database, book_id = sample
    for module_name in ("ui.details_dialog", "ui.stats_dialog", "ui.restore_dialog",
                        "ui.dialogs", "ui.folder_import_dialog"):
        module = __import__(module_name, fromlist=["db"])
        if hasattr(module, "db"):
            monkeypatch.setattr(module, "db", database)

    failures = []
    for name, factory in _dialogs(database, book_id, tmp_path):
        dialog = factory()
        size = _show(qt_app, dialog).size()
        minimum = dialog.minimumSize()
        if minimum.width() > SMALL[0] or minimum.height() > SMALL[1]:
            failures.append(f"{name}: needs {minimum.width()}x{minimum.height()}")
        if size.width() > SMALL[0] or size.height() > SMALL[1]:
            failures.append(f"{name}: opens at {size.width()}x{size.height()}")
        if layout.oversized_widgets(dialog):
            failures.append(f"{name}: a control sits outside the window")
        dialog.close()
    assert not failures, "\n".join(failures)


def test_the_reader_dialog_keeps_its_buttons_on_a_netbook(qt_app, screen, monkeypatch):
    from PyQt6.QtWidgets import QPushButton

    from ui.reader_settings_dialog import ReaderSettingsDialog

    monkeypatch.setattr(
        "ui.layout.screen_size",
        lambda widget=None: __import__("PyQt6.QtCore", fromlist=["QSize"]).QSize(*TINY),
    )
    dialog = ReaderSettingsDialog()
    _show(qt_app, dialog)

    assert dialog.width() <= TINY[0]
    assert dialog.height() <= TINY[1]
    # The body scrolls instead of pushing the buttons out of the window.
    assert dialog.scroll_area.verticalScrollBar().maximum() > 0

    save = next(b for b in dialog.findChildren(QPushButton) if b.text() == "Save settings")
    assert save.isVisible()
    bottom = save.mapTo(dialog, save.rect().bottomLeft()).y()
    assert bottom <= dialog.height(), "the Save button is below the visible area"
    dialog.close()


def test_the_reader_dialog_body_scrolls_on_a_short_screen(qt_app, screen):
    from ui.reader_settings_dialog import ReaderSettingsDialog

    dialog = ReaderSettingsDialog()
    _show(qt_app, dialog, 700, 420)
    assert dialog.scroll_area.verticalScrollBar().maximum() > 0
    assert dialog.readers_list.isVisible()
    dialog.close()


def test_the_detected_counter_ignores_the_system_entry(qt_app, screen):
    from ui.reader_settings_dialog import ReaderSettingsDialog

    dialog = ReaderSettingsDialog()
    _show(qt_app, dialog)
    text = dialog.status_label.text()
    assert text.endswith("reader(s) detected on this computer")
    counted = int(text.split()[0])
    real = [
        dialog.readers_list.item(row)
        for row in range(dialog.readers_list.count())
        if not dialog.readers_list.item(row).text().startswith("System default")
    ]
    assert counted == len(real), (text, [r.text() for r in real])
    dialog.close()


def test_main_window_shrinks_to_the_screen(qt_app, screen):
    from ui import layout
    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    assert window.minimumWidth() <= SMALL[0]
    assert window.minimumHeight() <= SMALL[1]
    _show(qt_app, window, SMALL[0] - layout.MARGIN, SMALL[1] - layout.MARGIN)
    assert window.width() <= SMALL[0]
    assert not layout.oversized_widgets(window)
    window.close()


def test_the_header_folds_instead_of_overflowing(qt_app):
    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    _show(qt_app, window, 1400, 900)
    assert not window.overflow_button.isVisible()
    assert window.import_button.isVisible()

    window.resize(820, 600)
    for _ in range(4):
        qt_app.processEvents()
    assert window.overflow_button.isVisible(), "a narrow window hides its actions"
    assert not window.import_button.isVisible()
    assert window.overflow_button.menu().actions(), "the overflow menu is empty"
    window.close()


def test_the_command_bar_wraps_on_a_narrow_window(qt_app):
    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    _show(qt_app, window, 1400, 900)
    assert window._command_bar_narrow is False

    window.resize(820, 600)
    for _ in range(4):
        qt_app.processEvents()
    assert window._command_bar_narrow is True
    # Every filter keeps enough room for its own text: that is what the user
    # sees when a combo box is squeezed to "Series & vo...".
    for combo in (window.read_filter_combo, window.format_combo, window.sort_combo):
        assert combo.width() >= combo.sizeHint().width() - 4, (
            f"{combo.currentText()}: {combo.width()} px for "
            f"{combo.sizeHint().width()} px of text"
        )
    window.close()


def test_a_wide_font_never_squeezes_a_filter(qt_app):
    """Windows draws the combo text wider than Linux does.

    The bar used to fold at a fixed 1000 px, which was measured with the Linux
    font: on Windows the three filters still sat in one row and Qt cut their
    labels to "All forma". The bar now measures the text it has to show, so a
    wider font has to make it fold further instead of clipping.
    """
    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    combos = (window.read_filter_combo, window.format_combo, window.sort_combo)
    for combo in combos:
        for index in range(combo.count()):
            combo.setItemText(index, combo.itemText(index) + "  widespecimen")
    _show(qt_app, window, 820, 600)

    assert window._command_bar_narrow is True
    for combo in combos:
        assert combo.width() >= combo.sizeHint().width() - 4, (
            f"{combo.currentText()}: {combo.width()} px for "
            f"{combo.sizeHint().width()} px of text"
        )
    # The extra rows push the bar down but never over the window edge.
    bar = window.search_input.parentWidget()
    assert bar.width() <= window.width()
    window.close()


def test_cards_never_hang_outside_the_grid(qt_app):
    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    _show(qt_app, window, 820, 600)
    window.flush_card_build()
    qt_app.processEvents()

    viewport = window.scroll_area.viewport().width()
    for card in window.book_cards:
        assert card.geometry().x() >= 0
        assert card.geometry().right() <= viewport, (
            f"card at x={card.geometry().x()} is cut off (viewport {viewport})"
        )
    window.close()


def test_the_column_setting_is_only_an_upper_bound(qt_app):
    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    window.columns_spin.setValue(6)
    _show(qt_app, window, 900, 700)
    window.flush_card_build()
    qt_app.processEvents()
    # The setting stays at 6 (that is what the user asked for) but only the
    # number of columns that fit is drawn.
    assert window.columns == 6
    assert window.columns_that_fit() < 6
    assert window._layout_columns == window.columns_that_fit()
    window.close()


def test_the_selection_bar_shortens_its_labels_on_a_narrow_window(qt_app):
    from PyQt6.QtWidgets import QAbstractButton

    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    _show(qt_app, window, 1400, 900)
    window.select_all()
    for _ in range(4):
        qt_app.processEvents()

    def overflowing():
        bad = []
        for child in window.selection_bar.findChildren(QAbstractButton):
            if child.text() and child.width() + 2 < child.sizeHint().width():
                bad.append(child.text())
        return bad

    if not window.book_cards:
        pytest.skip("the empty library has no cards to select")
    assert not overflowing(), overflowing()
    window.close()
