"""
GUI smoke test.

Runs the real Qt widgets with the offscreen platform plugin: builds a small comic
folder, imports it through the preview pipeline, opens every dialog and exercises
multi-selection. CI runs this on Linux and Windows to catch wiring errors that
unit tests cannot see.
"""
import os
import sys
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from database import db  # noqa: E402
from ui.theme import apply_theme  # noqa: E402


def make_comic(path: Path, series: str, number: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "ComicInfo.xml",
            f"<ComicInfo><Series>{series}</Series><Number>{number}</Number>"
            f"<Title>{series} {number}</Title><Writer>CI</Writer><Year>2026</Year>"
            "</ComicInfo>",
        )
        archive.writestr("001.jpg", os.urandom(64))


def main() -> int:
    app = QApplication([])
    apply_theme(app)

    from importer import LibraryImporter, build_folder_plan_with_db
    from ui.details_dialog import DetailsDialog
    from ui.folder_import_dialog import FolderImportDialog
    from ui.main_window import MainWindow
    from ui.reader_settings_dialog import ReaderSettingsDialog
    from ui.welcome_dialog import WelcomeDialog

    root = Path(tempfile.mkdtemp(prefix="dl-smoke-"))
    library = root / "comics"
    make_comic(library / "Batman" / "Batman 001.cbz", "Batman", 1)
    make_comic(library / "Batman" / "Batman 002.cbz", "Batman", 2)
    make_comic(library / "Saga" / "Saga 001.cbz", "Saga", 1)

    # --- folder plan + import ------------------------------------------
    plan = build_folder_plan_with_db(str(library), database=db, mode="auto")
    assert len(plan.groups) == 2, "folder plan did not detect two series"

    importer = LibraryImporter(database=db)
    expected_new = plan.new_count
    result = importer.import_plan(plan)
    assert result.added == expected_new, result.summary()

    # Importing again must not duplicate anything.
    second = build_folder_plan_with_db(str(library), database=db, mode="auto")
    assert second.new_count == 0, "duplicate detection failed"

    # --- main window ---------------------------------------------------
    window = MainWindow(run_startup=False)
    window.show()
    app.processEvents()
    window.refresh_books()
    app.processEvents()

    assert window.book_cards, "book cards were not created"

    window.select_all()
    app.processEvents()
    assert len(window.selected_ids) == len(window.book_cards)
    assert all(card.is_selected for card in window.book_cards)

    window._set_favorite_many(sorted(window.selected_ids), True)
    app.processEvents()
    window.clear_selection()
    assert not window.selected_ids

    # --- dialogs -------------------------------------------------------
    welcome = WelcomeDialog(window)
    app.processEvents()
    welcome.close()

    reader_settings = ReaderSettingsDialog(window)
    app.processEvents()
    reader_settings.close()

    folder_dialog = FolderImportDialog(window, folder=str(library))
    app.processEvents()
    assert folder_dialog.plan is not None
    assert folder_dialog.groups_table.rowCount() == 2
    headers = [
        folder_dialog.groups_table.horizontalHeaderItem(i).text()
        for i in range(folder_dialog.groups_table.columnCount())
    ]
    assert headers[0] == "Create", headers
    assert "سری با همین نام ساخته شود؟" in folder_dialog.question_label.text()
    names = folder_dialog._series_names()
    assert set(names.values()) == {"Batman", "Saga"}, names
    # Unticked rows must import without a series.
    folder_dialog.groups_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    names = folder_dialog._series_names()
    assert None in names.values()
    folder_dialog.close()

    book = db.get_all_books()[0]
    details = DetailsDialog(book["id"], window)
    app.processEvents()
    details.close()

    window.close()
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
