"""Volume assignment algorithm tests."""
import os
from pathlib import Path

from volume_planner import plan_volumes, volume_span


def touch(tmp_path: Path, name: str, mtime: float = 1_600_000_000) -> str:
    path = tmp_path / name
    path.write_bytes(b"x")
    os.utime(path, (mtime, mtime))
    return str(path)


def numbers(assignments):
    return [assignment.number for assignment in assignments]


def test_numbers_from_filenames(tmp_path):
    files = [
        touch(tmp_path, "Batman 003.cbz"),
        touch(tmp_path, "Batman 001.cbz"),
        touch(tmp_path, "Batman 002.cbz"),
    ]
    assignments = plan_volumes(files)
    assert numbers(assignments) == [1, 2, 3]
    assert [Path(a.filepath).name for a in assignments] == [
        "Batman 001.cbz",
        "Batman 002.cbz",
        "Batman 003.cbz",
    ]
    assert all(a.source == "filename" for a in assignments)


def test_duplicate_numbers_are_pushed_to_next_free_slot(tmp_path):
    files = [
        touch(tmp_path, "Comic 001.cbz"),
        touch(tmp_path, "Comic 001 (copy).cbz"),
        touch(tmp_path, "Comic 001 (copy 2).cbz"),
    ]
    assignments = plan_volumes(files)
    assert numbers(assignments) == [1, 2, 3]


def test_duplicate_skips_existing_next_number(tmp_path):
    files = [
        touch(tmp_path, "Comic 001.cbz"),
        touch(tmp_path, "Comic 001 (copy).cbz"),
        touch(tmp_path, "Comic 002.cbz"),
    ]
    assignments = plan_volumes(files)
    assert numbers(assignments) == [1, 2, 3]
    # 002 keeps its own number, the duplicate moves past it
    by_name = {Path(a.filepath).name: a.number for a in assignments}
    assert by_name["Comic 002.cbz"] == 3 or by_name["Comic 002.cbz"] == 2
    assert len(set(numbers(assignments))) == 3


def test_existing_series_numbers_are_respected(tmp_path):
    files = [touch(tmp_path, "Saga 001.cbz"), touch(tmp_path, "Saga 002.cbz")]
    assignments = plan_volumes(files, existing_numbers={1, 2})
    assert numbers(assignments) == [3, 4]


def test_falls_back_to_chronological_order(tmp_path):
    files = [
        touch(tmp_path, "Intro.cbz", mtime=1_700_000_000),
        touch(tmp_path, "Bonus.cbz", mtime=1_600_000_000),
        touch(tmp_path, "Notes.cbz", mtime=1_500_000_000),
    ]
    assignments = plan_volumes(files)
    assert [Path(a.filepath).name for a in assignments] == [
        "Notes.cbz",
        "Bonus.cbz",
        "Intro.cbz",
    ]
    assert numbers(assignments) == [1, 2, 3]
    assert all(a.source == "chronological" for a in assignments)


def test_mixed_names_keep_numbered_files_in_place(tmp_path):
    files = [
        touch(tmp_path, "Batman 002.cbz"),
        touch(tmp_path, "Batman 003.cbz"),
        touch(tmp_path, "Batman Special.cbz"),
        touch(tmp_path, "Batman 004.cbz"),
    ]
    assignments = plan_volumes(files)
    assert len(set(numbers(assignments))) == 4
    special = next(a for a in assignments if "Special" in a.filepath)
    assert special.source in ("filled", "chronological")


def test_chronological_skips_used_numbers(tmp_path):
    files = [touch(tmp_path, "a.cbz", 1), touch(tmp_path, "b.cbz", 2)]
    assignments = plan_volumes(files, existing_numbers={1, 2, 3})
    assert numbers(assignments) == [4, 5]


def test_volume_span(tmp_path):
    files = [touch(tmp_path, f"X {index:03d}.cbz") for index in (1, 2, 5)]
    assert volume_span(plan_volumes(files)) == "1-5"
