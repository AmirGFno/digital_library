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
    errors: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.added + self.skipped + self.failed

    def summary(self) -> str:
        parts = [f"افزوده شد: {self.added}"]
        if self.skipped:
            parts.append(f"تکراری: {self.skipped}")
        if self.failed:
            parts.append(f"ناموفق: {self.failed}")
        if self.series_created:
            parts.append(f"سری جدید: {self.series_created}")
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
    for filepath in group.files:
        duplicate = False
        if path_index is not None:
            duplicate = normalize_path(filepath) in path_index
        elif database is not None:
            duplicate = database.find_duplicate(filepath) is not None
        if duplicate:
            duplicates.append(filepath)
        else:
            new_files.append(filepath)

    group.new_files = new_files
    group.duplicates = duplicates
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
                result.errors.append(f"فایل پیدا نشد: {filepath}")
                continue
            if not is_supported_file(filepath):
                result.failed += 1
                result.errors.append(f"قالب پشتیبانی نمی‌شود: {path.name}")
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
            series_id = self._prepare_series(requested_name, result)

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

                book_id = self.db.add_book(
                    assignment.filepath,
                    title=title,
                    series_id=series_id,
                    volume=assignment.volume,
                    metadata=metadata,
                )
                if book_id is None:
                    result.skipped += 1
                else:
                    result.added += 1

        result.skipped += plan.duplicate_count
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
            book_id = self.db.add_book(
                assignment.filepath,
                title=title,
                series_id=series_id,
                volume=assignment.volume,
                metadata=metadata,
            )
            if book_id is None:
                result.skipped += 1
            else:
                result.added += 1
        result.skipped += plan.duplicate_count
        return result

    def sync_library_folder(self, folder: str, progress: Optional[ProgressCallback] = None):
        """Silent synchronisation used on startup and by "Sync now"."""
        plan = build_folder_plan_with_db(folder, database=self.db, mode="auto")
        if not plan.groups:
            return ImportResult()
        names = {group.key: group.default_name for group in plan.groups}
        return self.import_plan(plan, names, progress=progress)

    def _prepare_series(self, name: Optional[str], result: ImportResult) -> Optional[int]:
        if not name or not str(name).strip():
            return None
        name = str(name).strip()
        existing = self.db.get_series_by_name_ci(name)
        if existing:
            return existing["id"]
        series_id = self.db.create_series(name)
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
