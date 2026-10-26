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
sys.path.insert(0, str(ROOT / "scripts"))

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

    from ui.name_preview_dialog import preview_when_needed

    advert = library / "Saga" / "Saga 002 [www.example.com] [t.me-channel].cbz"
    make_comic(advert, "Saga", 2)
    preview = preview_when_needed([str(advert)], window)
    assert preview is not None, "advertising name was not detected"
    app.processEvents()
    assert preview.changed_count() == 1
    assert preview.table.item(0, 1).text() == "Saga 002", preview.table.item(0, 1).text()
    preview.close()
    assert preview_when_needed([str(library / "Batman" / "Batman 001.cbz")]) is None

    book = db.get_all_books()[0]
    details = DetailsDialog(book["id"], window)
    app.processEvents()
    details.close()

    # --- new-folder question -------------------------------------------
    from ui.new_folder_dialog import ask_about_new_folders  # noqa: F401
    from ui.new_folder_dialog import NewFolderDialog

    new_dialog = NewFolderDialog([str(library / "Batman"), str(library / "Saga")], window)
    app.processEvents()
    decisions = new_dialog.decisions()
    assert set(decisions) == {str(library / "Batman"), str(library / "Saga")}
    assert all(d["action"] == "series" for d in decisions.values())
    assert decisions[str(library / "Batman")]["name"] == "Batman"
    new_dialog.close()

    # --- deleted series + restore ---------------------------------------
    from ui.restore_dialog import RestoreSeriesDialog

    saga = db.get_series_by_name_ci("Saga")
    books_before = db.get_total_book_count()
    db.delete_series(saga["id"])
    assert db.get_deleted_series(), "a deleted series must stay restorable"

    restore = RestoreSeriesDialog(window)
    app.processEvents()
    restore.list_widget.setCurrentRow(0)
    restore._restore()
    assert restore.restored_id, "restore did not return a series id"
    assert db.get_total_book_count() == books_before, "books disappeared on delete"
    restored = db.get_series(restore.restored_id)
    assert restored and restored["name"] == "Saga", restored
    restore.close()

    # --- statistics dialog ----------------------------------------------
    from ui.stats_dialog import StatisticsDialog

    stats_dialog = StatisticsDialog(window)
    app.processEvents()
    stats_dialog.close()

    # --- a deleted file leaves the library ------------------------------
    victim = db.get_all_books()[0]
    victim_path = Path(victim["filepath"])
    victim_path.unlink()
    assert window._prune_missing_files(silent=False) >= 1, "missing file was not pruned"
    assert db.get_book(victim["id"]) is None, "record of a deleted file survived"
    assert not victim_path.exists()

    # --- update prompt --------------------------------------------------
    from ui.update_dialog import UpdateDialog
    from utils import updater

    update_info = updater.UpdateInfo(
        version="2.5.0",
        tag="v2.5.0",
        notes="Smoke notes",
        page_url="https://example.test/releases",
        asset_url="https://example.test/update.zip",
        asset_name="DigitalLibrary-2.5.0-windows-x64-update.zip",
        asset_size=2 * 1024 * 1024,
        checksum_url="https://example.test/SHA256.txt",
    )
    installed = []
    update_dialog = UpdateDialog(
        update_info,
        parent=window,
        download=lambda report: (
            report(1024 * 1024, 2 * 1024 * 1024),
            root / "DigitalLibrary-2.5.0-update.zip",
        )[1],
        install=installed.append,
    )
    app.processEvents()
    update_dialog.start_download(inline=True)
    assert update_dialog.applying, "the update dialog never reached the install step"
    assert installed, "the downloaded package was not handed to the installer"
    assert update_dialog.result() == update_dialog.DialogCode.Accepted
    update_dialog.close()

    # --- patch package: only changed files, removals recorded -----------
    import build_update_package

    old_build = root / "build-2.4.0"
    (old_build / "_internal").mkdir(parents=True)
    (old_build / "DigitalLibrary.exe").write_bytes(b"old exe")
    (old_build / "_internal" / "same.dll").write_bytes(b"same")
    (old_build / "_internal" / "gone.dll").write_bytes(b"gone")
    first = root / "update-2.4.0.zip"
    build_update_package.build_package(old_build, "2.4.0", first)

    new_build = root / "build-2.5.0"
    (new_build / "_internal").mkdir(parents=True)
    (new_build / "DigitalLibrary.exe").write_bytes(b"new exe")
    (new_build / "_internal" / "same.dll").write_bytes(b"same")
    (new_build / "_internal" / "added.dll").write_bytes(b"added")
    second = root / "update-2.5.0.zip"
    summary = build_update_package.build_package(
        new_build, "2.5.0", second, previous=first
    )
    assert summary["files_shipped"] == 3, summary  # exe, added.dll, marker
    assert summary["files_removed"] == 1, summary
    assert updater.read_update_manifest(second)["removed"] == ["_internal/gone.dll"]

    window.close()
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
