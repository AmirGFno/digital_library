"""ComicInfo.xml and page counting tests."""
import zipfile
from pathlib import Path

import pytest

from comic_metadata import (
    count_pages,
    parse_comic_info_xml,
    read_comic_info,
    read_metadata,
)

BOM = chr(0xFEFF)

COMIC_INFO = """<?xml version="1.0" encoding="utf-8"?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Title>The Black Mirror</Title>
  <Series>Detective Comics</Series>
  <Number>3</Number>
  <Volume>2</Volume>
  <Writer>Scott Snyder</Writer>
  <Publisher>DC Comics</Publisher>
  <Year>2011</Year>
  <PageCount>120</PageCount>
  <Summary>A &lt;b&gt;dark&lt;/b&gt; story.</Summary>
  <Genre>Superhero</Genre>
</ComicInfo>
"""


def create_cbz(tmp_path: Path, comic_info: str = COMIC_INFO, images: int = 3) -> str:
    path = tmp_path / "comic.cbz"
    with zipfile.ZipFile(path, "w") as archive:
        if comic_info:
            archive.writestr("ComicInfo.xml", comic_info)
        for index in range(images):
            archive.writestr(f"page{index:03d}.jpg", b"fake-image")
    return str(path)


def test_parse_comic_info_fields():
    metadata = parse_comic_info_xml(COMIC_INFO.encode("utf-8"))
    assert metadata["title"] == "The Black Mirror"
    assert metadata["series_name"] == "Detective Comics"
    assert metadata["volume"] == "3"  # Number wins over Volume
    assert metadata["writer"] == "Scott Snyder"
    assert metadata["publisher"] == "DC Comics"
    assert metadata["year"] == 2011
    assert metadata["page_count"] == 120
    assert "<b>" not in metadata["summary"]


def test_utf8_bom_is_handled():
    metadata = parse_comic_info_xml((BOM + COMIC_INFO).encode("utf-8"))
    assert metadata["series_name"] == "Detective Comics"


def test_malformed_xml_returns_empty():
    assert parse_comic_info_xml(b"<ComicInfo><Series>Broken") == {}


def test_read_from_cbz(tmp_path):
    filepath = create_cbz(tmp_path)
    metadata = read_comic_info(filepath)
    assert metadata["writer"] == "Scott Snyder"
    assert read_metadata(filepath)["title"] == "The Black Mirror"


def test_missing_comic_info(tmp_path):
    filepath = create_cbz(tmp_path, comic_info="")
    assert read_comic_info(filepath) == {}


def test_count_pages_cbz(tmp_path):
    filepath = create_cbz(tmp_path, images=5)
    assert count_pages(filepath) == 5


def test_pdf_metadata(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "book.pdf"
    document = fitz.open()
    document.new_page()
    document.set_metadata({"title": "A PDF book", "author": "Someone"})
    document.save(str(path))
    document.close()

    metadata = read_metadata(str(path))
    assert metadata["title"] == "A PDF book"
    assert metadata["writer"] == "Someone"
    assert metadata["page_count"] == 1
    assert count_pages(str(path)) == 1
