"""End-to-end folder import: series detection, duplicates, volumes, cleaning."""
import os
import zipfile
from pathlib import Path

import pytest

from importer import LibraryImporter, build_folder_plan_with_db, detect_folder_mode


def make_cbz(path: Path, comic_info: str = "") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        if comic_info:
            archive.writestr("ComicInfo.xml", comic_info)
        archive.writestr("001.jpg", os.urandom(64))
    return str(path)


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "Comics"
    make_cbz(root / "Batman [www.site.com]" / "Batman 001.cbz")
    make_cbz(root / "Batman [www.site.com]" / "Batman 002.cbz")
    make_cbz(root / "Batman [www.site.com]" / "Batman 002 (copy).cbz")
    make_cbz(root / "Saga" / "Saga 001.cbz")
    return root


def test_detect_mode(tmp_path, library):
    assert detect_folder_mode(str(library)) == "subfolders"
    flat = tmp_path / "flat"
    make_cbz(flat / "one.cbz")
    assert detect_folder_mode(str(flat)) == "single"


def test_plan_groups_by_subfolder_with_clean_names(temp_db, library):
    plan = build_folder_plan_with_db(str(library), database=temp_db, mode="auto")

    names = sorted(group.default_name for group in plan.groups)
    assert names == ["Batman", "Saga"]
    assert plan.new_count == 4
    assert plan.duplicate_count == 0


def test_volumes_are_unique_within_a_series(temp_db, library):
    plan = build_folder_plan_with_db(str(library), database=temp_db, mode="auto")
    batman = next(group for group in plan.groups if group.default_name == "Batman")
    numbers = [assignment.number for assignment in batman.assignments]
    assert sorted(numbers) == [1, 2, 3]
    assert len(set(numbers)) == 3


def test_single_mode_uses_folder_name(temp_db, library):
    plan = build_folder_plan_with_db(str(library), database=temp_db, mode="single")
    assert len(plan.groups) == 1
    assert plan.groups[0].default_name == "Comics"
    assert plan.new_count == 4


def test_import_plan_creates_series_and_volumes(temp_db, library):
    importer = LibraryImporter(database=temp_db)
    plan = build_folder_plan_with_db(str(library), database=temp_db, mode="auto")

    result = importer.import_plan(plan, use_metadata=True, clean_names=True)

    assert result.added == 4
    assert temp_db.get_statistics()["series_count"] == 2
    batman = temp_db.get_series_by_name_ci("Batman")
    books = temp_db.get_all_books(series_id=batman["id"])
    assert [book["volume_num"] for book in books] == [1, 2, 3]
    assert {book["title"] for book in books} == {"Batman 001", "Batman 002", "Batman 002 (copy)"}


def test_second_import_adds_nothing_new(temp_db, library):
    importer = LibraryImporter(database=temp_db)
    plan = build_folder_plan_with_db(str(library), database=temp_db, mode="auto")
    importer.import_plan(plan)

    second = build_folder_plan_with_db(str(library), database=temp_db, mode="auto")
    assert second.new_count == 0
    assert second.duplicate_count == 4


def test_only_new_files_are_added(temp_db, library):
    importer = LibraryImporter(database=temp_db)
    plan = build_folder_plan_with_db(str(library), database=temp_db, mode="auto")
    importer.import_plan(plan)

    make_cbz(library / "Batman [www.site.com]" / "Batman 003.cbz")

    second = build_folder_plan_with_db(str(library), database=temp_db, mode="auto")
    assert second.new_count == 1
    assert second.duplicate_count == 4

    result = importer.import_plan(second)
    assert result.added == 1
    batman = temp_db.get_series_by_name_ci("Batman")
    volumes = sorted(
        book["volume_num"] for book in temp_db.get_all_books(series_id=batman["id"])
    )
    assert volumes == [1, 2, 3, 4]


def test_same_content_under_new_name_is_a_duplicate(temp_db, tmp_path):
    importer = LibraryImporter(database=temp_db)
    original = Path(make_cbz(tmp_path / "Original 001.cbz"))
    importer.import_files([str(original)])

    copy = tmp_path / "Renamed 001.cbz"
    copy.write_bytes(original.read_bytes())

    result = importer.import_files([str(copy)])
    assert result.added == 0
    assert result.skipped == 1
    assert temp_db.get_total_book_count() == 1


def test_no_series_mode(temp_db, library):
    importer = LibraryImporter(database=temp_db)
    plan = build_folder_plan_with_db(str(library), database=temp_db, mode="subfolders")
    names = {group.key: None for group in plan.groups}

    importer.import_plan(plan, series_names=names)

    assert temp_db.get_statistics()["series_count"] == 0
    assert temp_db.get_total_book_count() == 4


def test_series_name_can_be_edited_before_import(temp_db, library):
    importer = LibraryImporter(database=temp_db)
    plan = build_folder_plan_with_db(str(library), database=temp_db, mode="auto")
    batman = next(group for group in plan.groups if group.default_name == "Batman")

    importer.import_plan(plan, series_names={batman.key: "Batman (2016)"})

    assert temp_db.get_series_by_name_ci("Batman (2016)") is not None
    assert temp_db.get_series_by_name_ci("Batman") is None


def test_metadata_series_is_used_when_adding_single_files(temp_db, tmp_path):
    importer = LibraryImporter(database=temp_db)
    comic_info = (
        "<ComicInfo><Series>Saga</Series><Number>7</Number>"
        "<Title>Chapter Seven</Title></ComicInfo>"
    )
    filepath = make_cbz(tmp_path / "saga-007.cbz", comic_info)

    result = importer.import_files([filepath])

    assert result.added == 1
    assert result.series_created == 1
    book = temp_db.get_all_books()[0]
    assert book["series_name"] == "Saga"
    assert book["volume"] == "7"
