"""
Comic metadata support.

Reads the widely used ``ComicInfo.xml`` sidecar that is embedded in CBZ/CBR/CB7
archives (ComicRack / Kavita / Komga / Mylar convention) and maps it to the
fields used by the library. PDF metadata is read with PyMuPDF.

The module is import-safe: optional archive backends are imported lazily so a
missing system tool never prevents the application from starting.
"""
from __future__ import annotations

import io
import re
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, Optional

from utils.logger import logger

COMIC_INFO_NAMES = {"comicinfo.xml"}

# ComicInfo.xml tag -> database column
_TAG_MAP = {
    "title": "title",
    "series": "series_name",
    "number": "volume",
    "volume": "volume",
    "writer": "writer",
    "publisher": "publisher",
    "year": "year",
    "pagecount": "page_count",
    "summary": "summary",
    "genre": "genre",
    "languageiso": "language",
}


def _decode_xml(data: bytes) -> Optional[ET.Element]:
    """Parse raw XML bytes, tolerating BOMs and legacy encodings."""
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        try:
            return ET.fromstring(text)
        except ET.ParseError:
            # Some files contain control characters that XML forbids.
            cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
            try:
                return ET.fromstring(cleaned)
            except ET.ParseError:
                continue
    return None


def parse_comic_info_xml(data: bytes) -> Dict[str, object]:
    """Convert ComicInfo.xml bytes into a normalized metadata dict."""
    root = _decode_xml(data)
    if root is None:
        logger.debug("ComicInfo.xml could not be parsed")
        return {}

    metadata: Dict[str, object] = {}
    for child in root:
        key = _TAG_MAP.get(child.tag.strip().lower())
        if not key:
            continue
        value = (child.text or "").strip()
        if not value:
            continue
        if key == "summary":
            value = re.sub(r"<[^>]+>", "", value)
        if key == "year":
            match = re.search(r"\d{4}", value)
            if not match:
                continue
            value = int(match.group(0))
        if key == "page_count":
            match = re.search(r"\d+", value)
            if not match:
                continue
            value = int(match.group(0))
        # "Number" wins over "Volume" because it is the reading order.
        if key == "volume" and "volume" in metadata and child.tag.lower() != "number":
            continue
        metadata[key] = value

    # Some publishers only fill <Volume> with the year; avoid falsy values.
    for key in ("title", "series_name", "volume", "writer", "publisher", "summary", "genre"):
        if key in metadata and not str(metadata[key]).strip():
            metadata.pop(key)

    return metadata


def _find_entry(names, wanted=COMIC_INFO_NAMES) -> Optional[str]:
    for name in names:
        base = Path(name).name.lower()
        if base in wanted:
            return name
    return None


def _read_zip(filepath: Path) -> Optional[bytes]:
    try:
        with zipfile.ZipFile(filepath) as archive:
            entry = _find_entry(archive.namelist())
            if entry:
                return archive.read(entry)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        logger.debug(f"ComicInfo zip read failed for {filepath}: {exc}")
    return None


def _read_rar(filepath: Path) -> Optional[bytes]:
    try:
        import rarfile
    except ImportError:
        return None
    try:
        with rarfile.RarFile(filepath) as archive:
            entry = _find_entry(archive.namelist())
            if entry:
                return archive.read(entry)
    except Exception as exc:  # rarfile raises many backend-specific errors
        logger.debug(f"ComicInfo rar read failed for {filepath}: {exc}")
    return None


def _read_7z(filepath: Path) -> Optional[bytes]:
    try:
        import py7zr
    except ImportError:
        return None
    try:
        with py7zr.SevenZipFile(filepath, "r") as archive:
            entry = _find_entry(archive.getnames())
            if not entry:
                return None
            handle = archive.read([entry]).get(entry)
            if isinstance(handle, io.BytesIO):
                return handle.getvalue()
            if handle is not None:
                return handle.read()
    except Exception as exc:  # py7zr raises many backend-specific errors
        logger.debug(f"ComicInfo 7z read failed for {filepath}: {exc}")
    return None


def _read_tar(filepath: Path) -> Optional[bytes]:
    try:
        with tarfile.open(filepath) as archive:
            entry = _find_entry(archive.getnames())
            if not entry:
                return None
            extracted = archive.extractfile(entry)
            return extracted.read() if extracted else None
    except (tarfile.TarError, OSError) as exc:
        logger.debug(f"ComicInfo tar read failed for {filepath}: {exc}")
    return None


def read_comic_info(filepath: str) -> Dict[str, object]:
    """Return metadata embedded in a comic archive, or an empty dict."""
    path = Path(filepath)
    if not path.exists():
        return {}

    suffix = path.suffix.lower()
    if suffix in (".cbz", ".zip"):
        data = _read_zip(path)
    elif suffix in (".cbr", ".rar"):
        data = _read_rar(path)
    elif suffix in (".cb7", ".7z"):
        data = _read_7z(path)
    elif suffix in (".cbt", ".tar", ".tgz") or path.name.lower().endswith(".tar.gz"):
        data = _read_tar(path)
    elif suffix == ".xml":
        data = path.read_bytes()
    else:
        data = None

    return parse_comic_info_xml(data) if data else {}


def read_pdf_metadata(filepath: str) -> Dict[str, object]:
    """Best-effort metadata extraction from a PDF file."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {}

    metadata: Dict[str, object] = {}
    try:
        with fitz.open(filepath) as document:
            info = document.metadata or {}
            if info.get("title"):
                metadata["title"] = info["title"].strip()
            if info.get("author"):
                metadata["writer"] = info["author"].strip()
            metadata["page_count"] = document.page_count
    except Exception as exc:
        logger.debug(f"PDF metadata read failed for {filepath}: {exc}")
    return metadata


def read_metadata(filepath: str) -> Dict[str, object]:
    """Read all metadata available for a comic/book file."""
    metadata = read_comic_info(filepath)
    if Path(filepath).suffix.lower() == ".pdf":
        for key, value in read_pdf_metadata(filepath).items():
            metadata.setdefault(key, value)
    return metadata


def count_pages(filepath: str) -> int:
    """Count pages/images inside a comic file. Returns 0 when unknown."""
    path = Path(filepath)
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            import fitz

            with fitz.open(path) as document:
                return int(document.page_count)
        if suffix in (".cbz", ".zip"):
            with zipfile.ZipFile(path) as archive:
                return sum(
                    1
                    for name in archive.namelist()
                    if Path(name).suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
                )
        if suffix in (".cbr", ".rar"):
            import rarfile

            with rarfile.RarFile(path) as archive:
                return sum(
                    1
                    for name in archive.namelist()
                    if Path(name).suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
                )
        if suffix in (".cb7", ".7z"):
            import py7zr

            with py7zr.SevenZipFile(path, "r") as archive:
                return sum(
                    1
                    for name in archive.getnames()
                    if Path(name).suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
                )
        if suffix in (".cbt", ".tar", ".tgz") or path.name.lower().endswith(".tar.gz"):
            with tarfile.open(path) as archive:
                return sum(
                    1
                    for name in archive.getnames()
                    if Path(name).suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
                )
        if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}:
            return 1
    except Exception as exc:
        logger.debug(f"Page count failed for {filepath}: {exc}")
    return 0
