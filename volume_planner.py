"""
Volume numbering for imported comics.

Rules implemented here (as requested by the library owner):

1. Numbers written in file names ("Batman 001", "جلد ۳", "#12") become the
   volume number.
2. A series never contains duplicate volume numbers. When a number is already
   taken the next free number is used, and so on until an empty slot is found.
3. When the file names of a series do not carry usable numbers (fewer than 60 %
   of them), volumes are assigned chronologically by file modification date.
4. Numbers already present in the database are respected, so importing a folder
   again only fills the gaps for the new files.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from utils.helpers import natural_sort_key
from utils.text_cleaner import extract_volume_number, looks_like_volume_series

# Share of files that must carry a number before the name-based mode is used.
NAME_CONFIDENCE_THRESHOLD = 0.6


@dataclass
class VolumeAssignment:
    """Volume decided for one file."""

    filepath: str
    volume: str
    number: int
    source: str  # "filename" | "filled" | "chronological"

    @property
    def was_inferred(self) -> bool:
        return self.source != "filename"


def _natural_key(filepath: str):
    return natural_sort_key(Path(filepath).stem.lower())


def _mtime(filepath: str) -> float:
    try:
        return Path(filepath).stat().st_mtime
    except OSError:
        return 0.0


def _next_free(number: int, used: Set[int]) -> int:
    while number in used:
        number += 1
    return number


def plan_volumes(
    filepaths: Sequence[str],
    existing_numbers: Iterable[int] = (),
    use_filenames: bool = True,
    threshold: float = NAME_CONFIDENCE_THRESHOLD,
) -> List[VolumeAssignment]:
    """Return ordered volume assignments for *filepaths*.

    The returned list is sorted in the order the books should be read.
    """
    files = [str(path) for path in filepaths]
    if not files:
        return []

    used: Set[int] = {int(number) for number in existing_numbers if number is not None}
    assignments: List[VolumeAssignment] = []

    stems = {filepath: Path(filepath).stem for filepath in files}
    detected: Dict[str, Optional[int]] = {
        filepath: extract_volume_number(stems[filepath]) for filepath in files
    }

    name_mode = use_filenames and looks_like_volume_series(
        (stems[filepath] for filepath in files), threshold=threshold
    )

    if name_mode:
        def sort_key(filepath: str):
            number = detected[filepath]
            # Files without a detectable number go last, ordered by name.
            return (0, number, _natural_key(filepath)) if number is not None else (1, 0, _natural_key(filepath))

        for filepath in sorted(files, key=sort_key):
            candidate = detected[filepath]
            if candidate is None:
                number = _next_free(1, used)
                source = "filled"
            elif candidate in used:
                number = _next_free(candidate + 1, used)
                source = "filled"
            else:
                number = candidate
                source = "filename"
            used.add(number)
            assignments.append(
                VolumeAssignment(filepath, str(number), number, source)
            )
    else:
        ordered = sorted(files, key=lambda path: (_mtime(path), _natural_key(path)))
        number = _next_free(1, used)
        for filepath in ordered:
            while number in used:
                number += 1
            used.add(number)
            assignments.append(
                VolumeAssignment(filepath, str(number), number, "chronological")
            )
            number += 1

    return assignments


def volume_span(assignments: Sequence[VolumeAssignment]) -> str:
    """Human readable range such as ``1–12`` for a preview."""
    numbers = [assignment.number for assignment in assignments]
    if not numbers:
        return "-"
    low, high = min(numbers), max(numbers)
    if low == high:
        return str(low)
    return f"{low}-{high}"
