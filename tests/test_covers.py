"""CBR / RAR cover extraction and tool discovery."""
import hashlib
import io
import os
import zipfile
from pathlib import Path

from PIL import Image


def _png_bytes(color=(200, 40, 40), size=(60, 80)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _zip_with_cover(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("002.png", _png_bytes((10, 10, 10)))
        archive.writestr("cover.png", _png_bytes((240, 90, 20)))
    return path


# ---------------------------------------------------------------- tool discovery
def test_tool_is_found_when_present(monkeypatch, tmp_path):
    from utils import rar_tools

    fake = tmp_path / "UnRAR.exe"
    fake.write_bytes(b"MZ")

    monkeypatch.setattr(rar_tools, "_candidate_paths", lambda: [fake])
    monkeypatch.setattr(rar_tools, "_registry_directories", lambda: [])
    rar_tools._active_tool = None
    rar_tools._registry_cache = None

    tool = rar_tools.find_tool()
    assert tool is not None
    assert tool["tool"] == "unrar"
    assert Path(tool["path"]) == fake


def test_no_tool_reports_clearly(monkeypatch):
    from utils import rar_tools

    monkeypatch.setattr(rar_tools, "_candidate_paths", lambda: [])
    monkeypatch.setattr(rar_tools, "_registry_directories", lambda: [])
    monkeypatch.setattr(rar_tools.shutil, "which", lambda name: None)
    rar_tools._active_tool = None

    assert rar_tools.find_tool() is None
    assert "not available" in rar_tools.describe_support()


def test_configuration_resets_rarfile_cache(monkeypatch, tmp_path):
    """rarfile caches its first lookup; configuring must force a new one."""
    import rarfile

    from utils import rar_tools

    fake = tmp_path / "7z.exe"
    fake.write_bytes(b"MZ")

    monkeypatch.setattr(rar_tools, "find_tool", lambda preferred=None: {
        "tool": "7z", "path": str(fake)
    })
    calls = []
    monkeypatch.setattr(rarfile, "tool_setup", lambda force=False: calls.append(force))

    rar_tools._active_tool = None
    tool = rar_tools.configure_rarfile(force=True)

    assert tool["tool"] == "7z"
    assert rarfile.SEVENZIP_TOOL == str(fake)
    assert calls and calls[-1] is True
    rar_tools._active_tool = None


# ---------------------------------------------------------------- covers
def test_zip_archive_named_cbr_shows_its_cover(tmp_path):
    """.cbr files that are really ZIP archives must work without any RAR tool."""
    from cover_extractor import CoverExtractor

    archive = _zip_with_cover(tmp_path / "Comic 001.cbr")
    extractor = CoverExtractor(cache_dir=tmp_path / "cache")

    cover = extractor.get_cover(str(archive))

    assert cover and Path(cover).exists()
    image = Image.open(cover)
    assert image.size == (200, 280), image.size


def test_cover_named_entry_wins(tmp_path):
    from cover_extractor import CoverExtractor

    archive = _zip_with_cover(tmp_path / "Comic 002.cbz")

    with zipfile.ZipFile(archive) as handle:
        names = [name for name in handle.namelist() if name.endswith(".png")]

    ordered = CoverExtractor._cover_candidates(names)
    assert ordered[0] == "cover.png"


def test_placeholder_cover_is_not_cached(tmp_path):
    """A missing cover must be retried later, not frozen as a placeholder."""
    from cover_extractor import CoverExtractor

    broken = tmp_path / "Broken 001.cbr"
    broken.write_bytes(b"not an archive at all")
    extractor = CoverExtractor(cache_dir=tmp_path / "cache")

    first = extractor.get_cover(str(broken))
    assert first and Path(first).exists()
    assert Path(first).parent.name == "fallback_covers"

    # The real cache stays empty, so a fixed installation can extract it later.
    assert list((tmp_path / "cache").glob("*.jpg")) == []


def test_replaced_file_gets_a_new_cover(tmp_path):
    from cover_extractor import CoverExtractor

    comic = tmp_path / "Comic 003.cbz"
    _zip_with_cover(comic)
    extractor = CoverExtractor(cache_dir=tmp_path / "cache")

    first = extractor.get_cover(str(comic))

    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("cover.png", _png_bytes((5, 200, 5)))
    os.utime(comic, (1, 1))

    second = extractor.get_cover(str(comic))
    assert second != first
    assert Image.open(second).size == (200, 280)


# ------------------------------------------------- first page is the cover
def _page_bytes(color) -> bytes:
    return _png_bytes(color, size=(60, 80))


def _cover_pixel(cover_path) -> tuple:
    image = Image.open(cover_path).convert("RGB")
    return image.getpixel((image.width // 2, image.height // 2))


def _assert_page_color(cover_path, expected, tolerance=8) -> None:
    """The cover cache is a JPEG, so compare the colour with some slack."""
    pixel = _cover_pixel(cover_path)
    assert all(
        abs(got - want) <= tolerance for got, want in zip(pixel, expected)
    ), f"{pixel} is not close to {expected}"


def _comic_with_pages(path: Path, pages) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, color in pages:
            archive.writestr(name, _page_bytes(color))
    return path


def test_the_first_page_of_the_comic_is_the_cover(tmp_path):
    """A real CBZ: 000.jpg is page one, 001.jpg is the second page.

    Reported case: the archive also carries 000c.jpg and pages named
    "Ben 10 004-001.jpg"; the old keyword search ("01") skipped page one and
    showed page two as the cover.
    """
    from cover_extractor import CoverExtractor

    comic = _comic_with_pages(
        tmp_path / "Ben 10 004.cbz",
        [
            ("000c.jpg", (10, 10, 10)),
            ("001.jpg", (240, 30, 30)),
            ("000.jpg", (30, 30, 240)),
            ("Ben 10 004-001.jpg", (30, 240, 30)),
            ("Ben 10 004-002.jpg", (240, 240, 30)),
        ],
    )

    cover = CoverExtractor(cache_dir=tmp_path / "cache").get_cover(str(comic))

    _assert_page_color(cover, (30, 30, 240))  # the blue 000.jpg


def test_pages_are_put_in_reading_order_not_alphabetical(tmp_path):
    """1.jpg < 2.jpg < 10.jpg, the way every comic reader orders pages."""
    from cover_extractor import CoverExtractor

    extractor = CoverExtractor(cache_dir=tmp_path / "cache")
    ordered = extractor._cover_candidates(
        ["10.jpg", "2.jpg", "1.jpg", "11.jpg"]
    )

    assert ordered == ["1.jpg", "2.jpg", "10.jpg", "11.jpg"]


def test_numbered_pages_come_before_lettered_pages(tmp_path):
    from cover_extractor import CoverExtractor

    extractor = CoverExtractor(cache_dir=tmp_path / "cache")
    ordered = extractor._cover_candidates(
        ["Ben 10 004-001.jpg", "000.jpg", "001.jpg"]
    )

    assert ordered[0] == "000.jpg"


def test_mac_metadata_and_thumbs_are_never_the_cover(tmp_path):
    from cover_extractor import CoverExtractor

    extractor = CoverExtractor(cache_dir=tmp_path / "cache")
    ordered = extractor._cover_candidates(
        [
            "__MACOSX/._000.jpg",
            ".hidden.jpg",
            "Thumbs.db",
            "000.jpg",
        ]
    )

    assert ordered == ["000.jpg"]


def test_a_page_named_cover_still_wins(tmp_path):
    """Comic readers honour a page literally named "cover"."""
    from cover_extractor import CoverExtractor

    extractor = CoverExtractor(cache_dir=tmp_path / "cache")
    ordered = extractor._cover_candidates(["001.jpg", "cover.jpg", "002.jpg"])

    assert ordered[0] == "cover.jpg"


def test_an_unreadable_first_page_falls_back_to_the_next(tmp_path):
    from cover_extractor import CoverExtractor

    comic = tmp_path / "Damaged 001.cbz"
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("000.jpg", b"not really a jpeg")
        archive.writestr("001.jpg", _page_bytes((90, 200, 90)))

    cover = CoverExtractor(cache_dir=tmp_path / "cache").get_cover(str(comic))

    _assert_page_color(cover, (90, 200, 90))


def test_covers_from_the_old_algorithm_are_rebuilt(tmp_path):
    """Cached covers made before the fix must not survive the new order."""
    from cover_extractor import CoverExtractor

    comic = _comic_with_pages(
        tmp_path / "Cached 001.cbz",
        [("000.jpg", (30, 30, 240)), ("001.jpg", (240, 30, 30))],
    )
    extractor = CoverExtractor(cache_dir=tmp_path / "cache")
    old_key = hashlib.md5(
        f"{comic}|{CoverExtractor._fingerprint(str(comic))}".encode()
    ).hexdigest()
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (200, 280), (240, 30, 30)).save(
        tmp_path / "cache" / f"{old_key}.jpg"
    )

    cover = extractor.get_cover(str(comic))

    assert cover != str(tmp_path / "cache" / f"{old_key}.jpg")
    _assert_page_color(cover, (30, 30, 240))
    # The stale thumbnail is not left behind in the user's cache.
    assert not (tmp_path / "cache" / f"{old_key}.jpg").exists()


def test_the_reported_archive_uses_page_000(tmp_path):
    """Exact entry list from the reported Ben 10 zip (WinRAR listing)."""
    from cover_extractor import CoverExtractor

    names = [
        "000c.jpg", "001.jpg", "000.jpg",
        "Ben 10 004-001.jpg", "Ben 10 004-002.jpg", "Ben 10 004-004.jpg",
        "Ben 10 004-003.jpg", "Ben 10 004-005.jpg", "Ben 10 004-006.jpg",
        "Ben 10 004-007.jpg", "Ben 10 004-008.jpg", "Ben 10 004-009.jpg",
        "Ben 10 004-010.jpg", "Ben 10 004-011.jpg", "Ben 10 004-012.jpg",
    ]

    ordered = CoverExtractor._cover_candidates(names)

    assert ordered[0] == "000.jpg"
    assert ordered[1] == "000c.jpg"
    assert ordered[2] == "001.jpg"
    # the numbered pages keep their reading order, 009 before 010
    tail = [name for name in ordered if name.startswith("Ben")]
    assert tail.index("Ben 10 004-009.jpg") < tail.index("Ben 10 004-010.jpg")


def test_pages_inside_a_folder_are_ordered_by_their_name(tmp_path):
    from cover_extractor import CoverExtractor

    ordered = CoverExtractor._cover_candidates(
        ["Comic/10.jpg", "Comic/2.jpg", "Comic/1.jpg"]
    )

    assert ordered == ["Comic/1.jpg", "Comic/2.jpg", "Comic/10.jpg"]


def test_tar_archives_use_the_same_page_order(tmp_path):
    import tarfile

    from cover_extractor import CoverExtractor

    archive = tmp_path / "Comic.tar"
    pages = [("10.jpg", (200, 200, 200)), ("2.jpg", (240, 30, 30)), ("1.jpg", (30, 30, 240))]
    with tarfile.open(archive, "w") as handle:
        for name, color in pages:
            data = io.BytesIO()
            Image.new("RGB", (60, 80), color).save(data, "PNG")
            payload = data.getvalue()
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            handle.addfile(info, io.BytesIO(payload))

    cover = CoverExtractor(cache_dir=tmp_path / "cache").get_cover(str(archive))

    _assert_page_color(cover, (30, 30, 240))


def test_7z_archives_use_the_same_page_order(tmp_path):
    import pytest

    py7zr = pytest.importorskip("py7zr")
    from cover_extractor import CoverExtractor

    source = tmp_path / "pages"
    source.mkdir()
    for name, color in (("10.jpg", (200, 200, 200)), ("2.jpg", (240, 30, 30)), ("1.jpg", (30, 30, 240))):
        Image.new("RGB", (60, 80), color).save(source / name)

    archive = tmp_path / "Comic.7z"
    with py7zr.SevenZipFile(archive, "w") as handle:
        handle.writeall(str(source), arcname="")

    cover = CoverExtractor(cache_dir=tmp_path / "cache").get_cover(str(archive))

    _assert_page_color(cover, (30, 30, 240))


def test_cbt_archives_are_read_like_tar(tmp_path):
    import tarfile

    from cover_extractor import CoverExtractor

    archive = tmp_path / "Comic.cbt"
    with tarfile.open(archive, "w") as handle:
        for name, color in (("000.jpg", (30, 30, 240)), ("001.jpg", (240, 30, 30))):
            data = io.BytesIO()
            Image.new("RGB", (60, 80), color).save(data, "PNG")
            payload = data.getvalue()
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            handle.addfile(info, io.BytesIO(payload))

    cover = CoverExtractor(cache_dir=tmp_path / "cache").get_cover(str(archive))

    _assert_page_color(cover, (30, 30, 240))


def test_tiff_pages_count_as_pages(tmp_path):
    from cover_extractor import CoverExtractor

    comic = tmp_path / "Scan 001.cbz"
    with zipfile.ZipFile(comic, "w") as archive:
        first = io.BytesIO()
        Image.new("RGB", (60, 80), (30, 30, 240)).save(first, "TIFF")
        archive.writestr("001.tif", first.getvalue())
        archive.writestr("002.jpg", _page_bytes((240, 30, 30)))

    cover = CoverExtractor(cache_dir=tmp_path / "cache").get_cover(str(comic))

    _assert_page_color(cover, (30, 30, 240))


def test_scan_folders_and_hidden_files_do_not_confuse_the_order(tmp_path):
    from cover_extractor import CoverExtractor

    comic = tmp_path / "Scanned 001.cbz"
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("__MACOSX/._000.jpg", b"junk")
        archive.writestr("Comic/.DS_Store", b"junk")
        archive.writestr("Comic/001.jpg", _page_bytes((240, 30, 30)))
        archive.writestr("Comic/000.jpg", _page_bytes((30, 30, 240)))

    cover = CoverExtractor(cache_dir=tmp_path / "cache").get_cover(str(comic))

    _assert_page_color(cover, (30, 30, 240))


# ---------------------------------------------------------------- page browser
def test_pages_can_be_listed_and_read_for_the_manual_cover_picker(tmp_path):
    """The cover dialog needs the page list and one page's bytes."""
    from cover_extractor import cover_extractor

    path = tmp_path / "Ben 10 02 [FA].cbz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("000.jpg", _png_bytes((20, 30, 60)))
        archive.writestr("001.jpg", _png_bytes((200, 40, 40)))
        archive.writestr("ComicInfo.xml", "<ComicInfo/>")

    pages = cover_extractor.list_pages(str(path))
    assert pages == ["000.jpg", "001.jpg"]

    data = cover_extractor.read_page(str(path), "001.jpg")
    assert data
    image = Image.open(io.BytesIO(data))
    assert image.size == (60, 80)


def test_listing_pages_of_an_unreadable_file_is_empty_not_an_error(tmp_path):
    from cover_extractor import cover_extractor

    broken = tmp_path / "broken.cbz"
    broken.write_bytes(b"not a zip")
    assert cover_extractor.list_pages(str(broken)) == []
    assert cover_extractor.read_page(str(broken), "001.jpg") is None


def test_a_page_inside_the_book_can_become_the_cover(qt_app, tmp_path, monkeypatch):
    """Automatic detection is not always right; the user must be able to pick."""
    import ui.dialogs as dialogs

    cover_dir = tmp_path / "custom_covers"
    monkeypatch.setattr("config.CUSTOM_COVERS_DIR", cover_dir, raising=False)

    book_path = tmp_path / "Ben 10 02.cbz"
    with zipfile.ZipFile(book_path, "w") as archive:
        archive.writestr("000.jpg", _png_bytes((20, 30, 60), (120, 160)))
        archive.writestr("001.jpg", _png_bytes((200, 40, 40), (120, 160)))

    saved = {}
    monkeypatch.setattr(dialogs.db, "set_custom_cover",
                        lambda book_id, path: saved.update(id=book_id, path=path) or True)
    monkeypatch.setattr(dialogs.QMessageBox, "information", staticmethod(lambda *a, **k: 0))

    dialog = dialogs.SetCustomCoverDialog(7, "Ben 10 02", None, filepath=str(book_path))
    dialog.show()
    qt_app.processEvents()

    assert dialog.pages_list.count() == 2
    dialog.pages_list.setCurrentRow(1)
    qt_app.processEvents()
    assert dialog.set_btn.isEnabled()

    dialog._set_cover()
    assert saved["id"] == 7
    assert saved["path"].endswith(".jpg")
    stored = Image.open(saved["path"])
    assert stored.size == (120, 160)
    dialog.close()
