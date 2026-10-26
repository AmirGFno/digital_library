"""
Import pipeline.

One code path for every way a comic can enter the library: the "Add books"
dialog, drag & drop, the folder preview dialog and the automatic sync of the
library folder.

Responsibilities
----------------
* scan folders and decide which folder belongs to which series
* skip files that are already in the library (by path *or* content fingerprint)
* clean advertising noise out of names
* assign unique, gap-free volume numbers (:mod:`volume_planner`)
* read ComicInfo.xml / PDF metadata
* report exactly what happened (new / skipped / failed)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from comic_metadata import read_metadata
from config import ALL_EXTENSIONS
from database import compute_file_hash, normalize_path
from utils.logger import logger
from utils.text_cleaner import clean_file_stem, clean_name, clean_series_name
from volume_planner import VolumeAssignment, plan_volumes, volume_span

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class ImportResult:
    """Summary of an import operation."""

    added: int = 0
    skipped: int = 0
    failed: int = 0
    series_created: int = 0
    renamed: int = 0
    relinked: int = 0
    removed: int = 0
    series_removed: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.added + self.skipped + self.failed

    @property
    def changed(self) -> bool:
        return bool(
            self.added
            or self.relinked
            or self.removed
            or self.series_removed
            or self.series_created
        )

    def summary(self) -> str:
        parts = [f"{self.added} added"]
        if self.relinked:
            parts.append(f"{self.relinked} moved file(s) followed")
        if self.removed:
            parts.append(f"{self.removed} removed (file missing)")
        if self.skipped:
            parts.append(f"{self.skipped} already in library")
        if self.failed:
            parts.append(f"{self.failed} failed")
        if self.series_created:
            parts.append(f"{self.series_created} new series")
        if self.series_removed:
            parts.append(f"{self.series_removed} empty series removed")
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


# --------------------------------------------------------------------- plans
@dataclass
class FolderGroup:
    """A folder that becomes one series."""

    key: str
    default_name: str
    folder: Path
    files: List[str] = field(default_factory=list)
    new_files: List[str] = field(default_factory=list)
    duplicates: List[str] = field(default_factory=list)
    # filepath -> existing book id, for files already in the library
    duplicate_books: Dict[str, int] = field(default_factory=dict)
    assignments: List[VolumeAssignment] = field(default_factory=list)

    @property
    def volume_range(self) -> str:
        return volume_span(self.assignments)


@dataclass
class FolderPlan:
    """Everything the preview dialog needs before an import starts."""

    root: Path
    mode: str
    groups: List[FolderGroup] = field(default_factory=list)

    @property
    def new_count(self) -> int:
        return sum(len(group.new_files) for group in self.groups)

    @property
    def duplicate_count(self) -> int:
        return sum(len(group.duplicates) for group in self.groups)

    @property
    def total_count(self) -> int:
        return sum(len(group.files) for group in self.groups)


def detect_folder_mode(folder: str) -> str:
    """``subfolders`` when immediate subfolders contain comics, else ``single``."""
    root = Path(folder)
    if not root.is_dir():
        return "single"
    for child in root.iterdir():
        try:
            if not child.is_dir() or child.name.startswith("."):
                continue
        except OSError:
            continue
        if any(is_supported_file(str(path)) for path in child.rglob("*") if path.is_file()):
            return "subfolders"
    return "single"


def build_folder_plan(
    folder: str,
    mode: str = "auto",
    clean_names: bool = True,
    max_groups: int = 500,
) -> FolderPlan:
    """Collect files, split them by series folder and plan their volumes."""
    from database import db as default_db

    return build_folder_plan_with_db(
        folder,
        database=default_db,
        mode=mode,
        clean_names=clean_names,
        max_groups=max_groups,
    )


def build_folder_plan_with_db(
    folder: str,
    database=None,
    mode: str = "auto",
    clean_names: bool = True,
    max_groups: int = 500,
) -> FolderPlan:
    """Same as :func:`build_folder_plan` but with an injectable database."""
    root = Path(folder).expanduser()
    if mode == "auto":
        mode = detect_folder_mode(str(root))

    files = scan_folder(str(root), recursive=True)
    plan = FolderPlan(root=root, mode=mode)

    if not files:
        return plan

    groups: Dict[str, FolderGroup] = {}
    for filepath in files:
        path = Path(filepath)
        if mode == "single":
            folder_path = root
        else:
            try:
                relative = path.relative_to(root)
            except ValueError:
                relative = Path(path.name)
            folder_path = root / relative.parts[0] if len(relative.parts) > 1 else root
            if folder_path == root / path.name:
                folder_path = root
        key = str(folder_path)
        if key not in groups:
            if len(groups) >= max_groups:
                key = str(root)
                folder_path = root
            raw_name = folder_path.name if folder_path != root else root.name
            name = clean_series_name(raw_name) if clean_names else raw_name
            groups[key] = FolderGroup(
                key=key, default_name=name or raw_name, folder=folder_path
            )
        groups[key].files.append(filepath)

    path_index = hash_index = None
    if database is not None:
        path_index, hash_index = database.get_library_index()

    for group in groups.values():
        _analyse_group(group, database, path_index, hash_index)

    plan.groups = sorted(groups.values(), key=lambda group: group.default_name.lower())
    return plan


def _analyse_group(group: FolderGroup, database, path_index=None, hash_index=None) -> None:
    """Split new/duplicate files and compute the volume assignment."""
    series = None
    if database is not None:
        series = database.get_series_by_name_ci(group.default_name)
    existing_numbers = (
        database.get_series_volume_numbers(series["id"]) if series and database else set()
    )

    new_files: List[str] = []
    duplicates: List[str] = []
    duplicate_books: Dict[str, int] = {}
    for filepath in group.files:
        book_id = None
        if path_index is not None:
            book_id = path_index.get(normalize_path(filepath))
        elif database is not None:
            existing = database.find_duplicate(filepath)
            book_id = existing["id"] if existing else None
        if book_id:
            duplicates.append(filepath)
            duplicate_books[filepath] = book_id
        else:
            new_files.append(filepath)

    group.new_files = new_files
    group.duplicates = duplicates
    group.duplicate_books = duplicate_books
    group.assignments = plan_volumes(new_files, existing_numbers)


# --------------------------------------------------------------------- import
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

    # ------------------------------------------------------------------
    # Single / multi file import (Add books dialog, drag & drop of files)
    # ------------------------------------------------------------------
    def import_files(
        self,
        filepaths: Iterable[str],
        series_id: Optional[int] = None,
        title: Optional[str] = None,
        volume: Optional[str] = None,
        use_metadata: bool = True,
        clean_names: bool = True,
        progress: Optional[ProgressCallback] = None,
    ) -> ImportResult:
        """Import individual files.

        Explicit ``title``/``volume`` values from the dialog take precedence over
        the values found in file names and embedded metadata.
        """
        paths = [str(path) for path in filepaths]
        result = ImportResult()

        path_index, hash_index = self.db.get_library_index()
        existing_numbers = self.db.get_series_volume_numbers(series_id)
        pending: List[str] = []
        seen_hashes = set()
        for index, filepath in enumerate(paths, start=1):
            if progress is not None:
                _safe_progress(progress, index, len(paths), filepath)

            path = Path(filepath)
            if not path.is_file():
                result.failed += 1
                result.errors.append(f"File not found: {filepath}")
                continue
            if not is_supported_file(filepath):
                result.failed += 1
                result.errors.append(f"Unsupported format: {path.name}")
                continue

            fingerprint = compute_file_hash(filepath)
            if normalize_path(filepath) in path_index or (
                fingerprint and (fingerprint in hash_index or fingerprint in seen_hashes)
            ):
                result.skipped += 1
                logger.info(f"Skipping duplicate: {filepath}")
                continue

            if fingerprint:
                seen_hashes.add(fingerprint)
            path_index[normalize_path(filepath)] = -1
            pending.append(filepath)

        assignments: Dict[str, VolumeAssignment] = {}
        if series_id is not None and volume is None:
            for assignment in plan_volumes(pending, existing_numbers):
                assignments[assignment.filepath] = assignment

        for filepath in pending:
            metadata = self._read_metadata(filepath, use_metadata)
            resolved_title = title
            if resolved_title is None:
                metadata_title = metadata.get("title")
                resolved_title = (
                    clean_name(str(metadata_title)) if metadata_title else None
                ) or (clean_file_stem(filepath) if clean_names else Path(filepath).stem)

            resolved_volume = volume
            if resolved_volume is None and filepath in assignments:
                resolved_volume = assignments[filepath].volume
            if resolved_volume is None and metadata.get("volume") is not None:
                resolved_volume = str(metadata["volume"])

            # Files carrying a ComicInfo.xml series name join (or create) it.
            resolved_series = series_id
            if resolved_series is None and metadata.get("series_name"):
                resolved_series = self._prepare_series(
                    clean_name(str(metadata["series_name"]))
                    if clean_names
                    else str(metadata["series_name"]),
                    result,
                )

            book_id = self.db.add_book(
                filepath,
                title=resolved_title,
                series_id=resolved_series,
                volume=resolved_volume,
                metadata=metadata,
            )
            if book_id is None:
                result.skipped += 1
            else:
                result.added += 1
                if resolved_title and resolved_title != Path(filepath).stem:
                    result.renamed += 1

        logger.info(
            "Import finished: %s added, %s skipped, %s failed",
            result.added,
            result.skipped,
            result.failed,
        )
        return result

    # ------------------------------------------------------------------
    # Folder import using a prepared plan
    # ------------------------------------------------------------------
    def import_plan(
        self,
        plan: FolderPlan,
        series_names: Optional[Dict[str, Optional[str]]] = None,
        use_metadata: bool = True,
        clean_names: bool = True,
        progress: Optional[ProgressCallback] = None,
    ) -> ImportResult:
        """Execute a :class:`FolderPlan` (already previewed by the user)."""
        series_names = series_names or {}
        result = ImportResult()

        total = plan.new_count
        done = 0
        for group in plan.groups:
            requested_name = series_names.get(group.key, group.default_name)
            if not group.new_files and not self._adoptable_duplicates(group):
                # Nothing to import and nothing to put back: do not leave an
                # empty series behind.
                continue
            series_id = self._prepare_series(
                requested_name, result, folder=group.folder
            )

            existing_numbers = self.db.get_series_volume_numbers(series_id)
            assignments = plan_volumes(group.new_files, existing_numbers)

            for assignment in assignments:
                done += 1
                if progress is not None:
                    _safe_progress(progress, done, total, assignment.filepath)

                metadata = self._read_metadata(assignment.filepath, use_metadata)
                title = None
                if metadata.get("title"):
                    title = clean_name(str(metadata["title"])) if clean_names else str(
                        metadata["title"]
                    )
                if not title:
                    title = (
                        clean_file_stem(assignment.filepath)
                        if clean_names
                        else Path(assignment.filepath).stem
                    )

                # The same comic may already be in the library under a
                # different path (a move, a rename, a copy). The fingerprint
                # catches those, so the library never shows it twice.
                file_hash = compute_file_hash(assignment.filepath)
                existing = self.db.find_duplicate(
                    assignment.filepath, file_hash=file_hash
                )
                if existing:
                    result.skipped += 1
                    logger.info(
                        "Skipped duplicate content: %s (already as %s)",
                        assignment.filepath,
                        existing.get("filepath"),
                    )
                    continue

                book_id = self.db.add_book(
                    assignment.filepath,
                    title=title,
                    series_id=series_id,
                    volume=assignment.volume,
                    metadata=metadata,
                    file_hash=file_hash,
                )
                if book_id is None:
                    result.skipped += 1
                else:
                    result.added += 1

            relinked = self._relink_duplicates(group, series_id)
            result.relinked += relinked
            result.skipped += max(0, len(group.duplicates) - relinked)

        logger.info(
            "Folder import: %s added, %s duplicates skipped, %s failed",
            result.added,
            result.skipped,
            result.failed,
        )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def import_folder(
        self,
        folder: str,
        recursive: bool = True,
        series_id: Optional[int] = None,
        use_metadata: bool = True,
        mode: str = "auto",
        clean_names: bool = True,
        progress: Optional[ProgressCallback] = None,
    ) -> ImportResult:
        """Import a whole folder (no interactive preview)."""
        plan = build_folder_plan_with_db(
            folder, database=self.db, mode=mode, clean_names=clean_names
        )
        names = {
            group.key: (group.default_name if series_id is None else None)
            for group in plan.groups
        }
        if series_id is not None:
            # Everything goes into one existing series.
            plan.groups = [
                FolderGroup(
                    key="__all__",
                    default_name="",
                    folder=plan.root,
                    files=[f for group in plan.groups for f in group.files],
                    new_files=[f for group in plan.groups for f in group.new_files],
                    duplicates=[f for group in plan.groups for f in group.duplicates],
                )
            ]
            names = {"__all__": None}
            return self._import_into_series(
                plan, series_id, use_metadata, clean_names, progress
            )
        return self.import_plan(
            plan, names, use_metadata=use_metadata, clean_names=clean_names,
            progress=progress,
        )

    def _import_into_series(
        self,
        plan: FolderPlan,
        series_id: int,
        use_metadata: bool,
        clean_names: bool,
        progress: Optional[ProgressCallback],
    ) -> ImportResult:
        result = ImportResult()
        group = plan.groups[0] if plan.groups else None
        if group is None:
            return result

        existing = self.db.get_series_volume_numbers(series_id)
        assignments = plan_volumes(group.new_files, existing)
        for index, assignment in enumerate(assignments, start=1):
            if progress is not None:
                _safe_progress(progress, index, len(assignments), assignment.filepath)
            metadata = self._read_metadata(assignment.filepath, use_metadata)
            title = None
            if metadata.get("title"):
                title = clean_name(str(metadata["title"])) if clean_names else str(
                    metadata["title"]
                )
            if not title:
                title = (
                    clean_file_stem(assignment.filepath)
                    if clean_names
                    else Path(assignment.filepath).stem
                )
            file_hash = compute_file_hash(assignment.filepath)
            if self.db.find_duplicate(assignment.filepath, file_hash=file_hash):
                result.skipped += 1
                continue
            book_id = self.db.add_book(
                assignment.filepath,
                title=title,
                series_id=series_id,
                volume=assignment.volume,
                metadata=metadata,
                file_hash=file_hash,
            )
            if book_id is None:
                result.skipped += 1
            else:
                result.added += 1
        result.skipped += plan.duplicate_count
        return result

    def sync_library_folder(
        self,
        folder: str,
        progress: Optional[ProgressCallback] = None,
        remove_missing: bool = True,
    ) -> ImportResult:
        """Silent synchronisation used on startup and by "Sync now".

        Besides importing new files it removes library entries whose file was
        deleted from disk, so the library always mirrors the folder.
        """
        result = ImportResult()

        # 1. Files that were moved inside the library keep their record (and so
        #    keep their reading state, rating and cover) instead of coming back
        #    as a second copy.
        result.relinked = self.db.relink_moved_books(folder)
        self.db.relink_series_folders(folder)

        # 2. Files that really are gone leave the library. Records inside the
        #    library folder are checked even when their folder disappeared too.
        if remove_missing:
            result.removed = self.db.remove_missing_books(library_root=folder)
            result.series_removed = self.db.prune_empty_series(library_root=folder)

        plan = build_folder_plan_with_db(folder, database=self.db, mode="auto")
        if not plan.groups:
            return result
        names = {group.key: group.default_name for group in plan.groups}
        imported = self.import_plan(plan, names, progress=progress)
        imported.removed += result.removed
        imported.relinked += result.relinked
        imported.series_removed += result.series_removed
        return imported

    def remove_missing_files(self, library_root: Optional[str] = None) -> int:
        """Drop library entries for files that no longer exist on disk."""
        return self.db.remove_missing_books(library_root=library_root)

    def _adoptable_duplicates(self, group: FolderGroup) -> int:
        """Duplicates that are free to join this folder's series."""
        count = 0
        for filepath, book_id in group.duplicate_books.items():
            book = self.db.get_book(book_id)
            if not book or not Path(filepath).exists():
                continue
            if book.get("series_id") and self.db.get_series(book["series_id"]):
                continue
            count += 1
        return count

    def _relink_duplicates(
        self, group: FolderGroup, series_id: Optional[int]
    ) -> int:
        """Put files that are already in the library back into their series.

        This is what makes a deleted series recoverable: the folder is imported
        again, the files are recognised as known, and instead of being ignored
        they are moved back into the (re)created series with fresh volume
        numbers.
        """
        if series_id is None or not group.duplicate_books:
            return 0

        pending: List[str] = []
        for filepath, book_id in group.duplicate_books.items():
            book = self.db.get_book(book_id)
            if not book:
                continue
            if book.get("series_id") == series_id:
                continue
            # A book that still belongs to another series keeps it: only
            # series-less books (a deleted series, a plain import) are adopted.
            if book.get("series_id") and self.db.get_series(book["series_id"]):
                continue
            if not Path(filepath).exists():
                continue
            pending.append(filepath)

        if not pending:
            return 0

        existing_numbers = self.db.get_series_volume_numbers(series_id)
        assignments = plan_volumes(pending, existing_numbers)
        skipped_numbers = set(existing_numbers)
        relinked = 0
        for assignment in assignments:
            if assignment.number in skipped_numbers:
                continue
            skipped_numbers.add(assignment.number)
            book_id = group.duplicate_books[assignment.filepath]
            if self.db.attach_book_to_series(
                book_id, series_id, assignment.volume
            ):
                relinked += 1
        if relinked:
            logger.info(
                "Restored %s file(s) into series %s", relinked, series_id
            )
        return relinked

    def _prepare_series(
        self,
        name: Optional[str],
        result: ImportResult,
        folder: Optional[Path] = None,
    ) -> Optional[int]:
        if not name or not str(name).strip():
            return None
        name = str(name).strip()
        existing = self.db.get_series_by_name_ci(name)
        if existing:
            if folder is not None and not existing.get("folder"):
                self.db.set_series_folder(existing["id"], str(folder))
            return existing["id"]
        series_id = self.db.create_series(name, folder=str(folder) if folder else None)
        if series_id:
            result.series_created += 1
        return series_id

    def _get_or_create_series(self, name: str, result: ImportResult) -> Optional[int]:
        return self._prepare_series(name, result)

    @staticmethod
    def _read_metadata(filepath: str, use_metadata: bool) -> Dict:
        if not use_metadata:
            return {}
        try:
            return read_metadata(filepath)
        except Exception as exc:  # metadata must never block an import
            logger.warning(f"Metadata read failed for {filepath}: {exc}")
            return {}


def _safe_progress(callback: ProgressCallback, index: int, total: int, filepath: str) -> None:
    try:
        callback(index, total, filepath)
    except Exception:  # a broken progress dialog must not abort the import
        pass


importer = LibraryImporter()
