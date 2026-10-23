"""Import pipeline tests."""
import zipfile
from pathlib import Path

from importer import LibraryImporter, scan_folder

COMIC_INFO = """<?xml version="1.0"?>
<ComicInfo>
  <Series>Saga</Series>
  <Number>3</Number>
  <Title>Chapter Three</Title>
  <Writer>Brian K. Vaughan</Writer>
  <Publisher>Image Comics</Publisher>
  <Year>2014</Year>
  <PageCount>26</PageCount>
</ComicInfo>
"""


def make_cbz(path: Path, comic_info: str = COMIC_INFO) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ComicInfo.xml", comic_info)
        archive.writestr("001.jpg", b"image")
        archive.writestr("002.jpg", b"image")
    return str(path)


def test_import_uses_metadata_and_creates_series(temp_db, tmp_path):
    importer = LibraryImporter(database=temp_db)
    filepath = make_cbz(tmp_path / "saga-003.cbz")

    result = importer.import_files([filepath])

    assert result.added == 1
    assert result.series_created == 1

    book = temp_db.get_all_books()[0]
    assert book["title"] == "Chapter Three"
    assert book["series_name"] == "Saga"
    assert book["volume"] == "3"
    assert book["volume_num"] == 3
    assert book["writer"] == "Brian K. Vaughan"
    assert book["publisher"] == "Image Comics"
    assert book["year"] == 2014
    assert book["page_count"] == 26


def test_duplicate_import_is_skipped(temp_db, tmp_path):
    importer = LibraryImporter(database=temp_db)
    filepath = make_cbz(tmp_path / "saga-003.cbz")

    assert importer.import_files([filepath]).added == 1
    second = importer.import_files([filepath])
    assert second.added == 0
    assert second.skipped == 1


def test_explicit_values_override_metadata(temp_db, tmp_path):
    importer = LibraryImporter(database=temp_db)
    filepath = make_cbz(tmp_path / "saga-003.cbz")
    series_id = temp_db.create_series("Custom series")

    importer.import_files([filepath], series_id=series_id, title="Custom title", volume="99")

    book = temp_db.get_all_books()[0]
    assert book["title"] == "Custom title"
    assert book["volume"] == "99"
    assert book["series_name"] == "Custom series"
    assert temp_db.get_statistics()["series_count"] == 1


def test_metadata_can_be_disabled(temp_db, tmp_path):
    importer = LibraryImporter(database=temp_db)
    filepath = make_cbz(tmp_path / "saga-003.cbz")

    importer.import_files([filepath], use_metadata=False)
    book = temp_db.get_all_books()[0]
    assert book["series_id"] is None
    assert book["volume"] is None


def test_unsupported_and_missing_files_are_counted(temp_db, tmp_path):
    importer = LibraryImporter(database=temp_db)
    text_file = tmp_path / "notes.txt"
    text_file.write_text("hello", encoding="utf-8")

    result = importer.import_files([str(text_file), str(tmp_path / "missing.cbz")])
    assert result.failed == 2
    assert result.added == 0


def test_import_folder_scans_recursively(temp_db, tmp_path):
    importer = LibraryImporter(database=temp_db)
    nested = tmp_path / "publisher" / "series"
    nested.mkdir(parents=True)
    make_cbz(nested / "one.cbz")
    make_cbz(tmp_path / "two.cbz")
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")

    result = importer.import_folder(str(tmp_path), recursive=True)
    assert result.added == 2


def test_scan_folder_non_recursive(tmp_path):
    make_cbz(tmp_path / "one.cbz")
    nested = tmp_path / "nested"
    nested.mkdir()
    make_cbz(nested / "two.cbz")

    assert len(scan_folder(str(tmp_path), recursive=False)) == 1
    assert len(scan_folder(str(tmp_path), recursive=True)) == 2
