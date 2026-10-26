"""CBR / RAR cover extraction and tool discovery."""
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
