"""
Import service.

Single code path used by the "Add book" dialog, bulk import, drag & drop and
the CLI: scans folders, reads ComicInfo.xml metadata, creates missing series and
adds books to the database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from comic_metadata import read_metadata
from config import ALL_EXTENSIONS
from utils.logger import logger


@dataclass
class ImportResult:
    """Summary of an import operation."""

    added: int = 0
    skipped: int = 0
    failed: int = 0
    series_created: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.added + self.skipped + self.failed

    def summary(self) -> str:
        parts = [f"Added: {self.added}"]
        if self.skipped:
            parts.append(f"Skipped: {self.skipped}")
        if self.failed:
            parts.append(f"Failed: {self.failed}")
        if self.series_created:
            parts.append(f"New series: {self.series_created}")
        return "  |  ".join(parts)


def is_supported_file(filepath: str) -> bool:
    lower = str(filepath).lower()
    return any(lower.endswith(ext) for ext in ALL_EXTENSIONS)


def scan_folder(folder: str, recursive: bool = True) -> List[str]:
    """Return all supported book files in a folder, sorted naturally."""
    root = Path(folder)
    if not root.is_dir():
        return []

    found: List[str] = []
    iterator = root.rglob("*") if recursive else root.glob("*")
    for path in iterator:
        try:
            if path.is_file() and is_supported_file(str(path)):
                found.append(str(path))
        except OSError:
            continue
    return sorted(found, key=lambda value: value.lower())


class LibraryImporter:
    """Imports files into the library while enriching them with metadata."""

    def __init__(self, database=None):
        self._db = database

    @property
    def db(self):
        if self._db is None:
            from database import db

            self._db = db
        return self._db

    def import_files(
        self,
        filepaths: Iterable[str],
        series_id: Optional[int] = None,
        title: Optional[str] = None,
        volume: Optional[str] = None,
        use_metadata: bool = True,
        progress=None,
    ) -> ImportResult:
        """Import individual files.

        Explicit ``series_id``/``title``/``volume`` values from the dialog take
        precedence over embedded ComicInfo.xml metadata.
        """
        paths = [str(path) for path in filepaths]
        result = ImportResult()

        for index, filepath in enumerate(paths, start=1):
            if progress is not None:
                try:
                    progress(index, len(paths), filepath)
                except Exception:
                    pass
            path = Path(filepath)
            if not path.is_file():
                result.failed += 1
                result.errors.append(f"File not found: {filepath}")
                continue
            if not is_supported_file(filepath):
                result.failed += 1
                result.errors.append(f"Unsupported format: {path.name}")
                continue

            if self.db.book_exists(filepath):
                result.skipped += 1
                continue

            metadata: Dict = {}
            if use_metadata:
                try:
                    metadata = read_metadata(filepath)
                except Exception as exc:  # metadata must never block an import
                    logger.warning(f"Metadata read failed for {filepath}: {exc}")

            resolved_series = series_id
            if resolved_series is None and metadata.get("series_name"):
                resolved_series = self._get_or_create_series(
                    str(metadata["series_name"]), result
                )

            book_title = title or metadata.get("title")
            book_volume = volume or metadata.get("volume")

            book_id = self.db.add_book(
                filepath,
                title=book_title,
                series_id=resolved_series,
                volume=str(book_volume) if book_volume is not None else None,
                metadata=metadata,
            )
            if book_id is None:
                result.skipped += 1
            else:
                result.added += 1

        logger.info(
            "Import finished: %s added, %s skipped, %s failed",
            result.added,
            result.skipped,
            result.failed,
        )
        return result

    def import_folder(
        self,
        folder: str,
        recursive: bool = True,
        series_id: Optional[int] = None,
        use_metadata: bool = True,
        progress=None,
    ) -> ImportResult:
        """Import every supported file inside a folder."""
        return self.import_files(
            scan_folder(folder, recursive=recursive),
            series_id=series_id,
            use_metadata=use_metadata,
            progress=progress,
        )

    def _get_or_create_series(self, name: str, result: ImportResult) -> Optional[int]:
        name = name.strip()
        if not name:
            return None
        existing = self.db.get_series_by_name(name)
        if existing:
            return existing["id"]
        series_id = self.db.create_series(name)
        if series_id:
            result.series_created += 1
        return series_id


importer = LibraryImporter()
