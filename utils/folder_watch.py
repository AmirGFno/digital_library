"""
Detect folders that appeared in the library root and are not a series yet.

The user asked for this explicitly: when a new folder shows up inside the comics
folder, the application should ask whether it should be added as a series. This
module only *finds* such folders — asking the question is the window's job.

A folder is offered once. Every answer ("yes" or "no") is remembered in
``library.answered_folders`` so the same question never comes back.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from utils.logger import logger


def _normalized(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve()).lower()
    except OSError:
        return str(value).lower()


def _contains_books(folder: Path) -> bool:
    """True when the folder (or one of its subfolders) holds a supported file."""
    from importer import is_supported_file

    try:
        for path in folder.rglob("*"):
            try:
                if path.is_file() and is_supported_file(str(path)):
                    return True
            except OSError:
                continue
    except OSError:
        return False
    return False


def find_unmanaged_folders(
    root: str,
    known_folders: Sequence[Optional[str]] = (),
    ignored_folders: Sequence[str] = (),
    limit: int = 25,
) -> List[str]:
    """Return immediate subfolders of *root* that should be offered as a series.

    * folders already linked to a series (``known_folders``) are skipped
    * folders the user already answered about (``ignored_folders``) are skipped
    * folders without any comic/book file are skipped
    * hidden folders (starting with a dot) are skipped
    """
    root_path = Path(root).expanduser()
    if not root_path.is_dir():
        return []

    known = {_normalized(folder) for folder in known_folders if folder}
    ignored = {_normalized(folder) for folder in ignored_folders if folder}

    candidates: List[str] = []
    try:
        children = sorted(root_path.iterdir(), key=lambda item: item.name.lower())
    except OSError as exc:
        logger.warning(f"Could not list {root_path}: {exc}")
        return []

    for child in children:
        if len(candidates) >= limit:
            break
        try:
            if not child.is_dir() or child.name.startswith((".", "_", "$")):
                continue
        except OSError:
            continue
        normalized = _normalized(str(child))
        if normalized in known or normalized in ignored:
            continue
        if not _contains_books(child):
            continue
        candidates.append(str(child))
    return candidates


def remember_answer(folder: str, answered: Iterable[str]) -> List[str]:
    """Return the new ``answered_folders`` list with *folder* added once."""
    target = _normalized(folder)
    result = list(answered or [])
    if all(_normalized(item) != target for item in result):
        result.append(str(folder))
    # Keep the list bounded so settings never grow without limit.
    return result[-500:]
