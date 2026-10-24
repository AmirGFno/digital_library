"""Series restore, folder linking and removal of files that disappeared."""
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from importer import LibraryImporter, build_folder_plan_with_db


def make_cbz(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.jpg", payload)
    return str(path)


@pytest.fixture
def library_root(tmp_path):
    root = tmp_path / "Comics"
    make_cbz(root / "Batman" / "Batman 001.cbz", os.urandom(32))
    make_cbz(root / "Batman" / "Batman 002.cbz", os.urandom(32))
    return root


@pytest.fixture
def loaded(temp_db, library_root):
    importer = LibraryImporter(database=temp_db)
    plan = build_folder_plan_with_db(str(library_root), database=temp_db, mode="auto")
    importer.import_plan(plan)
    return importer, temp_db, library_root


# ---------------------------------------------------------------- restore
def test_series_knows_its_folder(loaded):
    _, database, root = loaded
    series = database.get_series_by_name_ci("Batman")
    assert series is not None
    assert Path(series["folder"]) == root / "Batman"
    assert database.get_series_by_folder(str(root / "Batman"))["id"] == series["id"]


def test_deleted_series_can_be_restored_from_history(loaded):
    importer, database, root = loaded
    series = database.get_series_by_name_ci("Batman")
    book_ids = {book["id"] for book in database.get_all_books()}

    assert database.delete_series(series["id"]) is True
    assert database.get_series_by_name_ci("Batman") is None
    assert all(book["series_id"] is None for book in database.get_all_books())

    trash = database.get_deleted_series()
    assert len(trash) == 1 and trash[0]["name"] == "Batman"
    assert set(trash[0]["book_ids"]) == book_ids

    restored_id = database.restore_deleted_series(trash[0]["id"])
    assert restored_id
    restored = database.get_series(restored_id)
    assert restored["name"] == "Batman"
    assert Path(restored["folder"]) == root / "Batman"
    assert {book["id"] for book in database.get_all_books(series_id=restored_id)} == book_ids
    assert database.get_deleted_series() == []


def test_importing_the_folder_again_brings_the_series_back(loaded):
    importer, database, root = loaded
    series = database.get_series_by_name_ci("Batman")
    database.delete_series(series["id"])
    assert database.get_series_by_name_ci("Batman") is None

    # Same files on disk: they are duplicates, but they must be re-linked.
    plan = build_folder_plan_with_db(str(root), database=database, mode="auto")
    result = importer.import_plan(plan)

    assert result.added == 0
    assert result.relinked == 2
    recreated = database.get_series_by_name_ci("Batman")
    assert recreated is not None
    books = database.get_all_books(series_id=recreated["id"])
    assert len(books) == 2
    assert sorted(book["volume_num"] for book in books) == [1, 2]


def test_restore_keeps_existing_volume_numbers(loaded):
    importer, database, root = loaded
    series = database.get_series_by_name_ci("Batman")
    database.delete_series(series["id"])

    plan = build_folder_plan_with_db(str(root), database=database, mode="auto")
    importer.import_plan(plan)
    recreated = database.get_series_by_name_ci("Batman")
    numbers = sorted(
        book["volume_num"] for book in database.get_all_books(series_id=recreated["id"])
    )
    assert numbers == [1, 2]


def test_restored_series_survives_its_books_being_deleted(loaded):
    """A deleted book must not break the restore of the rest of the series."""
    _, database, _ = loaded
    series = database.get_series_by_name_ci("Batman")
    database.delete_series(series["id"])

    first_book = database.get_all_books()[0]
    database.delete_book(first_book["id"])

    trash = database.get_deleted_series()[0]
    restored_id = database.restore_deleted_series(trash["id"])
    assert restored_id
    assert len(database.get_all_books(series_id=restored_id)) == 1


def test_forgetting_a_deleted_series(loaded):
    _, database, _ = loaded
    series = database.get_series_by_name_ci("Batman")
    database.delete_series(series["id"])
    assert database.get_deleted_series()

    database.forget_deleted_series()
    assert database.get_deleted_series() == []


def test_delete_series_without_remembering(loaded):
    _, database, _ = loaded
    series = database.get_series_by_name_ci("Batman")
    database.delete_series(series["id"], remember=False)
    assert database.get_series_by_name_ci("Batman") is None
    assert database.get_deleted_series() == []


# ---------------------------------------------------------------- missing files
def test_missing_file_is_removed_from_the_library(loaded):
    _, database, root = loaded
    target = root / "Batman" / "Batman 001.cbz"
    target.unlink()

    missing = database.get_missing_books()
    assert [book["filepath"] for book in missing] == [str(target)]

    assert database.remove_missing_books() == 1
    assert database.get_total_book_count() == 1
    assert database.get_missing_books() == []


def test_sync_removes_deleted_files_and_keeps_the_rest(loaded):
    importer, database, root = loaded
    (root / "Batman" / "Batman 002.cbz").unlink()

    result = importer.sync_library_folder(str(root))

    assert result.removed == 1
    remaining = database.get_all_books()
    assert len(remaining) == 1
    assert remaining[0]["filepath"].endswith("Batman 001.cbz")


def test_offline_folder_is_not_treated_as_deleted(loaded, tmp_path):
    _, database, root = loaded
    shutil.rmtree(root)

    # The parent folder is gone as well: this looks like an unplugged drive.
    assert database.get_missing_books() == []
    assert database.get_total_book_count() == 2


def test_removing_missing_files_never_touches_disk(loaded):
    _, database, root = loaded
    survivor = root / "Batman" / "Batman 002.cbz"
    (root / "Batman" / "Batman 001.cbz").unlink()

    database.remove_missing_books()

    assert survivor.exists()


# ---------------------------------------------------------------- folder prompt
def test_new_folder_is_detected_but_known_series_are_not(tmp_path):
    from utils.folder_watch import find_unmanaged_folders

    root = tmp_path / "Comics"
    make_cbz(root / "Batman" / "Batman 001.cbz", os.urandom(16))
    make_cbz(root / "Brand New Series" / "Issue 01.cbz", os.urandom(16))
    (root / "Notes").mkdir()  # empty folder: nothing to import

    candidates = find_unmanaged_folders(
        str(root),
        known_folders=[],
        ignored_folders=[str(root / "Batman")],  # already a series
    )
    names = [Path(folder).name for folder in candidates]
    assert names == ["Brand New Series"]

    # Already answered before -> never asked again.
    candidates = find_unmanaged_folders(
        str(root),
        known_folders=[],
        ignored_folders=[str(root / "Brand New Series"), str(root / "Batman")],
    )
    assert candidates == []


def test_folder_with_a_series_is_not_offered_again(temp_db, library_root):
    from utils.folder_watch import find_unmanaged_folders

    importer = LibraryImporter(database=temp_db)
    plan = build_folder_plan_with_db(str(library_root), database=temp_db, mode="auto")
    importer.import_plan(plan)

    known = [series["folder"] for series in temp_db.get_all_series() if series["folder"]]
    candidates = find_unmanaged_folders(
        str(library_root), known_folders=known, ignored_folders=[]
    )
    assert candidates == []


# ------------------------------------------------- moved / deleted files
def test_moved_file_keeps_its_record(loaded):
    importer, database, root = loaded
    source = root / "Batman" / "Batman 001.cbz"
    book = next(b for b in database.get_all_books() if b["filepath"] == str(source))
    database.toggle_book_read(book["id"])
    moved = root / "Elsewhere" / "Batman 001.cbz"
    moved.parent.mkdir(parents=True)
    shutil.move(str(source), str(moved))

    result = importer.sync_library_folder(str(root))

    assert result.relinked == 1
    assert result.added == 0
    assert database.get_total_book_count() == 2
    after = database.get_book(book["id"])
    assert after["filepath"] == str(moved)
    assert after["is_read"] == 1


def test_deleted_folder_leaves_the_library(loaded):
    _, database, root = loaded
    shutil.rmtree(root / "Batman")

    importer = LibraryImporter(database=database)
    result = importer.sync_library_folder(str(root))

    assert result.removed == 2
    assert database.get_total_book_count() == 0
    assert database.get_series_by_name_ci("Batman") is None
    assert [item["name"] for item in database.get_deleted_series()] == ["Batman"]


def test_deleted_file_keeps_its_series(loaded):
    importer, database, root = loaded
    (root / "Batman" / "Batman 002.cbz").unlink()

    result = importer.sync_library_folder(str(root))

    assert result.removed == 1
    assert result.series_removed == 0
    assert database.get_total_book_count() == 1
    assert database.get_series_by_name_ci("Batman") is not None


def test_a_copy_of_a_known_comic_is_not_added_twice(loaded):
    importer, database, root = loaded
    shutil.copy2(root / "Batman" / "Batman 001.cbz", root / "Batman" / "Batman 001 copy.cbz")

    result = importer.sync_library_folder(str(root))

    assert result.added == 0
    assert database.get_total_book_count() == 2


# ------------------------------------------------- path spelling on Windows
def test_library_membership_ignores_separators_and_case():
    """Windows paths use backslashes; the check must not depend on that."""
    from database import _is_inside

    assert _is_inside("c:/comics/batman/one.cbz", "c:/comics")
    assert _is_inside("c:/comics", "c:/comics")
    assert not _is_inside("c:/comics2/one.cbz", "c:/comics")
    assert not _is_inside("d:/comics/one.cbz", "c:/comics")
    assert not _is_inside("c:/comics/one.cbz", "")


def test_comparable_path_uses_forward_slashes():
    from database import _comparable_path

    assert "\\" not in _comparable_path("some\\folder\\comic.cbz")
