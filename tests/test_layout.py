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
    from ui.series_info_dialog import SeriesInfoDialog
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
        ("SeriesInfoDialog", lambda: SeriesInfoDialog(database.get_all_series()[0]["id"])),
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
                        "ui.dialogs", "ui.folder_import_dialog",
                        "ui.series_info_dialog"):
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
    # Name the offender: a bare "assert not []" tells nobody which control
    # overflowed, and the font differs between Windows and Linux.
    offenders = [
        f"{type(widget).__name__}#{widget.objectName() or '-'}"
        f" {widget.geometry().getRect()} in {window.width()}x{window.height()}"
        for widget in layout.oversized_widgets(window)
    ]
    assert not offenders, offenders
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
    # The bar decides from what it measures, not from a hardcoded breakpoint,
    # so the decision has to match the width the window really got. A small
    # screen can hand back a narrower window than the one asked for.
    margins = window.command_grid.contentsMargins()
    room = window.width() - margins.left() - margins.right()
    one_row, _ = window._command_bar_widths()
    assert window._command_bar_narrow is (room < one_row + 24), (
        f"window={window.width()} px, room={room} px, one row needs {one_row} px, "
        f"mode={window._command_bar_mode_name}"
    )

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


def test_a_toast_wraps_a_long_path_instead_of_running_off(qt_app):
    """A message with no spaces used to run past the edge of the toast."""
    from PyQt6.QtWidgets import QLabel
    from ui.widgets import wrap_long_words

    assert wrap_long_words("short words stay whole") == "short words stay whole"
    path = wrap_long_words("C:" + "\\Comics\\Amazing Spider-Man (2026)" * 3)
    assert "\u200b" in path and "C:" in path

    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    _show(qt_app, window, 900, 700)
    from PyQt6.QtTest import QTest

    message = "Import failed: " + "D:" + "\\VeryLongFolderName" * 18
    toast = window._toasts.show(message, kind="error")
    QTest.qWait(80)   # the toast fades in on a 20 ms timer
    qt_app.processEvents()
    label = toast.findChild(QLabel)
    assert toast.isVisible()
    assert label.height() > label.fontMetrics().height() * 2, "the text was not wrapped"
    parent = toast.parentWidget()
    assert toast.geometry().left() >= 0
    assert toast.geometry().top() >= 0
    assert toast.geometry().right() < parent.width()
    assert toast.geometry().bottom() < parent.height()
    toast.dismiss()
    window.close()


def test_the_details_window_wraps_a_long_file_path(qt_app, tmp_path, sample, monkeypatch):
    from ui import details_dialog

    database, _ = sample
    monkeypatch.setattr(details_dialog, "db", database)
    long_path = str(tmp_path / ("A folder name without any spaces " * 6) / "book.cbz")
    book_id = database.add_book(long_path, title="A long path")
    dialog = details_dialog.DetailsDialog(book_id)
    _show(qt_app, dialog, 620, 460)
    label = dialog.path_label
    assert label.height() >= label.heightForWidth(label.width()) - 2, (
        "the path is cut off instead of wrapped"
    )
    assert label.toolTip().endswith("book.cbz")
    dialog.close()


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


def test_the_grid_fits_itself_to_the_window(qt_app, sample, monkeypatch):
    """There is no column setting: a wider window simply holds more covers."""
    import ui.main_window as main_window

    database, _book_id = sample
    for index in range(2, 10):
        database.add_book(str(database.db_path.parent / f"T {index:02d}.cbz"),
                          title=f"T {index}", series_id=1, volume=str(index))
    monkeypatch.setattr(main_window, "db", database)

    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)

    def columns_at(width):
        _show(qt_app, window, width, 720)
        window.flush_card_build()
        qt_app.processEvents()
        return window.columns_that_fit()

    narrow, wide = columns_at(700), columns_at(1400)
    assert 1 <= narrow < wide
    # The layout follows the measurement, and nothing sticks out of the grid.
    assert window._layout_columns == window.columns_that_fit()
    viewport = window.scroll_area.viewport().width()
    for card in window.book_cards:
        assert card.geometry().right() <= viewport
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


def _clipped_labels(root, tolerance: int = 2):
    """Visible labels and buttons whose text does not fit their own box.

    The user saw a counter drawn on top of its caption and a number cut in
    half. Both are the same bug: a widget was given less room than the font it
    draws, so the text was clipped instead of laid out.
    """
    from PyQt6.QtWidgets import QAbstractButton, QLabel

    problems = []
    for child in root.findChildren((QLabel, QAbstractButton)):
        if not child.isVisible() or child.text() == "":
            continue
        # An elided label shortens its own text on purpose.
        if getattr(child, "elide", False) or type(child).__name__ == "ElidedLabel":
            continue
        hint = child.sizeHint()
        if child.height() + tolerance < hint.height():
            problems.append(f"{type(child).__name__} '{child.text()[:24]}' "
                            f"{child.height()}px tall, needs {hint.height()}")
        # Wrapping labels grow downwards; their width hint is a minimum.
        if getattr(child, "wordWrap", lambda: False)():
            continue
        if child.width() + tolerance < hint.width():
            problems.append(f"{type(child).__name__} '{child.text()[:24]}' "
                            f"{child.width()}px wide, needs {hint.width()}")
    return problems


def test_no_text_is_cut_in_half(qt_app, sample, monkeypatch):
    """Every visible piece of text fits the box that draws it."""
    import ui.main_window as main_window

    database, _book_id = sample
    for index in range(2, 8):
        database.add_book(str(database.db_path.parent / f"T {index:02d}.cbz"),
                          title=f"T {index}", series_id=1, volume=str(index))
    monkeypatch.setattr(main_window, "db", database)

    from ui.main_window import MainWindow

    for width, height in ((1440, 900), (1000, 700), (880, 620)):
        window = MainWindow(run_startup=False)
        window.resize(width, height)
        window.show()
        window.flush_card_build()
        for _ in range(6):
            qt_app.processEvents()
        assert not _clipped_labels(window), (width, _clipped_labels(window))
        window.close()


def test_the_details_table_shares_the_window(qt_app, sample, monkeypatch):
    """No sideways scrolling, and no column squeezed below its own header.

    With fixed pixel widths the Title column was left 96 px wide on a 1280 px
    window and Qt drew "Deep Fie…" in it. The table must divide the space it
    is given instead of asking for more than it has.
    """
    import ui.main_window as main_window

    database, _book_id = sample
    for index in range(2, 8):
        database.add_book(str(database.db_path.parent / f"T {index:02d}.cbz"),
                          title=f"T {index}", series_id=1, volume=str(index))
    monkeypatch.setattr(main_window, "db", database)

    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    window._set_view_mode("details")
    _show(qt_app, window, 1280, 800)

    table = window.books_table
    header = table.horizontalHeader()
    viewport = table.viewport().width()
    assert table.horizontalScrollBar().maximum() == 0
    assert sum(header.sectionSize(i) for i in range(header.count())) <= viewport

    title_width = header.sectionSize(0)
    assert title_width >= 240, title_width
    window.close()
