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
