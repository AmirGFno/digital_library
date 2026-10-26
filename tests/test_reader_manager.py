"""Reader detection and configuration tests."""
import sys

import pytest

from utils.reader_manager import (
    FORMAT_GROUPS,
    SYSTEM_READER_ID,
    ReaderInfo,
    ReaderManager,
)


@pytest.fixture
def fake_reader(tmp_path):
    if sys.platform.startswith("win"):
        path = tmp_path / "FakeReader.exe"
        path.write_bytes(b"MZ")
    else:
        path = tmp_path / "fake-reader"
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    return str(path)


def test_system_reader_always_available(temp_settings):
    manager = ReaderManager(temp_settings)
    readers = manager.refresh()
    system = next(reader for reader in readers if reader.id == SYSTEM_READER_ID)
    assert system.available
    assert system.supports("archive") and system.supports("pdf")


def test_reader_info_formats():
    reader = ReaderInfo(id="x", name="X", formats=("archive", "pdf"))
    assert reader.supports("archive")
    assert not reader.supports("image")


def test_custom_reader_is_detected(temp_settings, fake_reader):
    manager = ReaderManager(temp_settings)
    reader = manager.add_custom_reader("Fake Reader", fake_reader, ["archive", "pdf"])
    assert reader is not None
    assert reader.source == "custom"

    manager.refresh()
    assert manager.get(reader.id) is not None
    assert manager.get(reader.id).available
    assert any(r.id == reader.id for r in manager.available_readers("archive"))


def test_reader_resolution_per_format(temp_settings, fake_reader):
    manager = ReaderManager(temp_settings)
    reader = manager.add_custom_reader("Fake Reader", fake_reader, FORMAT_GROUPS)
    temp_settings.set_default_reader(SYSTEM_READER_ID)
    temp_settings.set_reader_for_format("pdf", reader.id)

    assert manager.get_reader_for_file("book.pdf").id == reader.id
    assert manager.get_reader_for_file("book.cbz") is None


def test_missing_file_reports_error(temp_settings):
    manager = ReaderManager(temp_settings)
    ok, message = manager.open_with(SYSTEM_READER_ID, "/does/not/exist.cbz")
    assert ok is False
    assert "not found" in message.lower()


def test_a_non_reader_from_the_open_with_list_is_ignored(temp_settings):
    """Windows reports programs registered for a file type, not only readers.

    A user saw ``mstsc`` (Remote Desktop) in the reader list because something
    had registered it for one of the comic extensions.
    """
    manager = ReaderManager(temp_settings)
    assert not manager.looks_like_reader(r"C:\Windows\System32\mstsc.exe")
    assert not manager.looks_like_reader(r"C:\Windows\explorer.exe")
    assert not manager.looks_like_reader(r"C:\Windows\notepad.exe")
    assert manager.looks_like_reader(r"C:\Program Files\CDisplayEx\CDisplayEx.exe")
    assert manager.looks_like_reader(r"C:\Tools\YACReader.exe")


# ---------------------------------------------------------------- new readers
def _catalog_entry(reader_id: str):
    from utils.reader_manager import CATALOG

    return next(entry for entry in CATALOG if entry.id == reader_id)


def test_adobe_sumatra_and_acbr_are_in_the_catalog():
    """The three readers the user asked for must be offered by name."""
    for reader_id, name in (
        ("adobe-reader", "Adobe Acrobat Reader"),
        ("adobe-acrobat", "Adobe Acrobat"),
        ("sumatrapdf", "SumatraPDF"),
        ("acbr", "ACBR Comic Book Reader"),
    ):
        entry = _catalog_entry(reader_id)
        assert entry.name == name
        assert "pdf" in entry.formats


def test_sumatra_portable_build_with_a_version_in_its_name_is_found(tmp_path, monkeypatch):
    """SumatraPDF ships as ``SumatraPDF-3.5.2-64.exe``, not a fixed name."""
    install = tmp_path / "SumatraPDF"
    install.mkdir()
    portable = install / "SumatraPDF-3.5.2-64.exe"
    portable.write_bytes(b"MZ")

    from utils import reader_manager as module

    definition = _catalog_entry("sumatrapdf")
    monkeypatch.setattr(module.os.path, "expandvars", lambda value: value)
    patched = module.ReaderDefinition(
        id=definition.id,
        name=definition.name,
        formats=definition.formats,
        windows_globs=(str(install / "SumatraPDF*.exe"),),
    )
    assert module.ReaderManager._globbed_executable(patched) == str(portable)


def test_adobe_reader_is_found_through_its_registry_install_folder(tmp_path, monkeypatch):
    """Every Acrobat release keeps its own folder, so the registry decides."""
    install = tmp_path / "Adobe" / "Acrobat Reader DC"
    (install / "Reader").mkdir(parents=True)
    executable = install / "Reader" / "AcroRd32.exe"
    executable.write_bytes(b"MZ")

    import types

    fake_winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=0,
        HKEY_CURRENT_USER=1,
        OpenKey=lambda *args, **kwargs: _FakeKey(str(install)),
        QueryValueEx=lambda key, name: (str(key), 1),
        EnumKey=lambda key, index: (_ for _ in ()).throw(OSError()),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr("utils.reader_manager.WINDOWS", True)

    from utils.reader_manager import ReaderManager

    found = ReaderManager._registry_install_executable(_catalog_entry("adobe-reader"))
    assert found == str(executable)


class _FakeKey:
    """Minimal context manager standing in for a registry key."""

    def __init__(self, value: str):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def __str__(self):
        return self.value


def test_acbr_opens_the_file_without_extra_switches(temp_settings, tmp_path, monkeypatch):
    """ACBR treats a bare path argument as the book to open."""
    book = tmp_path / "Issue 01.cbz"
    book.write_bytes(b"PK")
    executable = tmp_path / "ACBR"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)

    from utils import reader_manager as module

    commands = []
    entry = _catalog_entry("acbr")
    reader = module.ReaderInfo(
        id=entry.id,
        name=entry.name,
        executable=str(executable),
        formats=entry.formats,
        arguments=entry.arguments,
        available=True,
    )
    manager = module.ReaderManager(temp_settings)
    manager._readers = [reader]
    manager._loaded = True
    monkeypatch.setattr(
        module.subprocess, "Popen", lambda command, **kwargs: commands.append(command)
    )
    monkeypatch.setattr(module, "WINDOWS", False)

    ok, message = manager.open_with("acbr", str(book))
    assert ok, message
    assert commands == [[str(executable), str(book)]]
