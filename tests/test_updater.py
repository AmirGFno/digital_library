"""The update engine: version math, GitHub answers, checksums and patching."""
import hashlib
import importlib.util
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from utils import updater

ROOT = Path(__file__).resolve().parents[1]


def load_packager():
    spec = importlib.util.spec_from_file_location(
        "build_update_package", ROOT / "scripts" / "build_update_package.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packager = load_packager()


class FakeResponse:
    def __init__(self, payload: bytes):
        self._stream = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int = -1):
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def fake_opener(routes, requested=None):
    def opener(request, timeout=10):
        url = request.full_url
        if requested is not None:
            requested.append(url)
        if url not in routes:
            raise updater.urllib.error.URLError(f"no route for {url}")
        payload = routes[url]
        return FakeResponse(payload if isinstance(payload, bytes) else json.dumps(payload).encode())

    return opener


def release_payload(version="2.5.0", with_update=True):
    assets = [
        {
            "name": f"DigitalLibrary-{version}-windows-x64.exe",
            "browser_download_url": "https://example.test/portable.exe",
            "size": 1000,
        },
        {
            "name": "SHA256.txt",
            "browser_download_url": "https://example.test/SHA256.txt",
            "size": 90,
        },
    ]
    if with_update:
        assets.append(
            {
                "name": f"DigitalLibrary-{version}-windows-x64-update.zip",
                "browser_download_url": "https://example.test/update.zip",
                "size": 4321,
            }
        )
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://example.test/releases/v{version}",
        "body": "New things\nand fixes",
        "published_at": "2026-10-26T10:00:00Z",
        "assets": assets,
    }


# ----------------------------------------------------------------------
# Versions
# ----------------------------------------------------------------------
def test_versions_are_compared_as_numbers():
    assert updater.is_newer("2.10.0", "2.9.9")
    assert updater.is_newer("2.4.1", "2.4")
    assert not updater.is_newer("2.4.0", "2.4.0")
    assert not updater.is_newer("2.3.9", "2.4.0")
    assert not updater.is_newer("", "2.4.0")
    assert updater.normalize_version("v2.4.1") == "2.4.1"
    assert updater.normalize_version("release-2.4") == "2.4"


# ----------------------------------------------------------------------
# The release answer
# ----------------------------------------------------------------------
def test_the_newest_release_points_at_the_update_package():
    info = updater.fetch_latest_release(
        opener=fake_opener({updater.RELEASES_API: release_payload()})
    )

    assert info.version == "2.5.0"
    assert info.tag == "v2.5.0"
    assert info.can_install_in_place
    assert info.asset_name.endswith("-update.zip")
    assert info.checksum_url == "https://example.test/SHA256.txt"
    assert "New things" in info.notes
    assert info.size_text == "0.0 MB"  # 4321 bytes rounds down
    assert updater.is_newer(info.version)


def test_a_release_without_an_update_package_cannot_update_in_place():
    info = updater.fetch_latest_release(
        opener=fake_opener({updater.RELEASES_API: release_payload(with_update=False)})
    )
    assert not info.can_install_in_place
    assert info.page_url.endswith("/releases/v2.5.0")


def test_a_broken_answer_is_an_update_error():
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest_release(
            opener=fake_opener({updater.RELEASES_API: {"message": "rate limited"}})
        )


def test_an_offline_check_never_raises_anything_else():
    def offline(request, timeout=10):
        raise updater.urllib.error.URLError("name resolution failed")

    with pytest.raises(updater.UpdateError):
        updater.fetch_latest_release(opener=offline)


# ----------------------------------------------------------------------
# Download + checksum
# ----------------------------------------------------------------------
_package_counter = {"value": 0}


def _make_package(tmp_path, files, version="2.5.0", previous=None):
    _package_counter["value"] += 1
    dist = tmp_path / f"dist-{version}-{_package_counter['value']}"
    for name, payload in files.items():
        path = dist / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    output = tmp_path / f"update-{version}.zip"
    packager.build_package(dist, version, output, previous)
    return output


def test_the_checksum_file_is_parsed():
    digest = "a" * 64
    text = f"{digest}  DigitalLibrary-2.5.0-windows-x64-update.zip\nffff  other.zip\n"
    parsed = updater.parse_checksum_text(text)
    assert parsed["DigitalLibrary-2.5.0-windows-x64-update.zip"] == digest
    assert "other.zip" not in parsed


def test_the_download_is_verified_against_the_published_hash(tmp_path):
    package = _make_package(tmp_path, {"DigitalLibrary.exe": b"app", "f.dll": b"x" * 100})
    data = package.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    routes = {
        "https://example.test/update.zip": data,
        "https://example.test/SHA256.txt": (
            f"{digest}  DigitalLibrary-2.5.0-windows-x64-update.zip\n"
        ).encode(),
    }
    info = updater.fetch_latest_release(
        opener=fake_opener({**routes, updater.RELEASES_API: release_payload()})
    )
    progress = []

    path = updater.download_update(
        info,
        tmp_path / "downloads",
        progress=lambda done, total: progress.append((done, total)),
        opener=fake_opener(routes),
    )

    assert path.read_bytes() == data
    assert progress and progress[-1][0] == len(data)
    assert progress[-1][1] == len(data)


def test_a_damaged_download_is_deleted_and_rejected(tmp_path):
    routes = {
        "https://example.test/update.zip": b"not the published file",
        "https://example.test/SHA256.txt": (
            f"{'0' * 64}  DigitalLibrary-2.5.0-windows-x64-update.zip\n"
        ).encode(),
    }
    info = updater.fetch_latest_release(
        opener=fake_opener({**routes, updater.RELEASES_API: release_payload()})
    )

    with pytest.raises(updater.UpdateError):
        updater.download_update(info, tmp_path / "downloads", opener=fake_opener(routes))

    assert not list((tmp_path / "downloads").glob("*.zip"))


# ----------------------------------------------------------------------
# The PowerShell helper
# ----------------------------------------------------------------------
def test_the_helper_waits_for_the_app_and_swaps_the_files(tmp_path):
    archive = tmp_path / "update.zip"
    install_dir = tmp_path / "Program Files" / "Digital Library"
    script = updater.build_apply_script(
        archive,
        install_dir,
        install_dir / "DigitalLibrary.exe",
        4242,
        removed=["_internal/old.dll", "stale.txt"],
    )

    assert "Expand-Archive" in script
    assert str(archive) in script
    assert str(install_dir) in script
    assert "4242" in script
    assert "_internal/old.dll" in script
    assert "stale.txt" in script
    assert script.count("Start-Process") == 1


def test_paths_with_quotes_cannot_break_the_helper(tmp_path):
    script = updater.build_apply_script(
        tmp_path / "it's an update.zip",
        tmp_path / "O'Brien",
        tmp_path / "O'Brien" / "DigitalLibrary.exe",
        1,
    )
    assert "it''s an update.zip" in script
    assert "O''Brien" in script


def test_apply_update_starts_powershell_with_the_generated_script(tmp_path):
    calls = []
    archive = tmp_path / "update.zip"
    install_dir = tmp_path / "app"

    script = updater.apply_update(
        archive,
        install_dir=install_dir,
        executable=install_dir / "DigitalLibrary.exe",
        pid=777,
        runner=calls.append,
    )

    assert calls and calls[0][0] == "powershell.exe"
    assert "-ExecutionPolicy" in calls[0]
    assert str(script) in calls[0]
    assert script.read_bytes().startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    content = script.read_text(encoding="utf-8-sig")
    assert "Expand-Archive" in content and "777" in content


def test_installing_reads_the_removed_files_from_the_package(tmp_path, monkeypatch):
    package = _make_package(
        tmp_path,
        {"DigitalLibrary.exe": b"new", "fresh.dll": b"new"},
        previous=_make_package(
            tmp_path, {"DigitalLibrary.exe": b"old", "gone.dll": b"old"}
        ),
    )
    captured = {}

    def fake_apply(archive, install_dir=None, removed=(), **kwargs):
        captured["removed"] = list(removed)
        captured["archive"] = Path(archive)
        return Path(archive)

    monkeypatch.setattr(updater, "apply_update", fake_apply)
    updater.install_update(package, install_dir=tmp_path / "app")

    assert captured["archive"] == package
    assert "gone.dll" in captured["removed"]


# ----------------------------------------------------------------------
# Patch packages
# ----------------------------------------------------------------------
def test_the_first_package_contains_every_file(tmp_path):
    dist = tmp_path / "dist"
    (dist / "_internal").mkdir(parents=True)
    (dist / "DigitalLibrary.exe").write_bytes(b"app")
    (dist / "_internal" / "Qt6Core.dll").write_bytes(b"qt")

    output = tmp_path / "first.zip"
    summary = packager.build_package(dist, "2.4.0", output)

    assert summary["full_payload"] is True
    assert summary["files_total"] == 2
    assert summary["files_shipped"] == 3  # both files + the install marker
    with zipfile.ZipFile(output) as bundle:
        names = bundle.namelist()
        manifest = json.loads(bundle.read("update.json"))
    assert "DigitalLibrary.exe" in names
    assert "_internal/Qt6Core.dll" in names
    assert "install_info.json" in names
    assert manifest["version"] == "2.4.0"
    assert manifest["removed"] == []
    assert set(manifest["files"]) == {
        "DigitalLibrary.exe",
        "_internal/Qt6Core.dll",
        "install_info.json",
    }


def test_the_next_package_only_ships_what_changed(tmp_path):
    first = _make_package(
        tmp_path,
        {
            "DigitalLibrary.exe": b"app-1",
            "_internal/Qt6Core.dll": b"qt-1",
            "_internal/stale.dll": b"stale",
            "_internal/keep.dll": b"same",
        },
        version="2.4.0",
    )

    moved = tmp_path / "new"
    (moved / "_internal").mkdir(parents=True)
    (moved / "DigitalLibrary.exe").write_bytes(b"app-2")  # changed
    (moved / "_internal" / "Qt6Core.dll").write_bytes(b"qt-1")  # same
    (moved / "_internal" / "new.dll").write_bytes(b"brand new")  # added
    output = tmp_path / "second.zip"

    summary = packager.build_package(moved, "2.4.1", output, previous=first)

    assert summary["files_shipped"] == 3  # exe, new.dll and install_info.json
    assert summary["files_removed"] == 2  # stale.dll and keep.dll
    with zipfile.ZipFile(output) as bundle:
        names = set(bundle.namelist())
        manifest = json.loads(bundle.read("update.json"))
    assert names == {
        "DigitalLibrary.exe",
        "_internal/new.dll",
        "install_info.json",
        "update.json",
    }
    assert manifest["removed"] == ["_internal/keep.dll", "_internal/stale.dll"]
    assert manifest["files"]["_internal/Qt6Core.dll"] == hashlib.sha256(b"qt-1").hexdigest()


def test_applying_a_package_reproduces_the_new_build(tmp_path):
    old = tmp_path / "old"
    (old / "_internal").mkdir(parents=True)
    (old / "DigitalLibrary.exe").write_bytes(b"app-1")
    (old / "_internal" / "old.dll").write_bytes(b"old")

    new = tmp_path / "new"
    (new / "_internal").mkdir(parents=True)
    (new / "DigitalLibrary.exe").write_bytes(b"app-2")
    (new / "_internal" / "added.dll").write_bytes(b"added")

    first = tmp_path / "first.zip"
    packager.build_package(old, "2.4.0", first)
    second = tmp_path / "second.zip"
    summary = packager.build_package(new, "2.4.1", second, previous=first)

    # Simulate what the PowerShell helper does with the installed folder.
    with zipfile.ZipFile(second) as bundle:
        bundle.extractall(old)
        manifest = json.loads(bundle.read("update.json"))
    for name in manifest["removed"]:
        (old / name).unlink(missing_ok=True)

    assert (old / "DigitalLibrary.exe").read_bytes() == b"app-2"
    assert (old / "_internal" / "added.dll").read_bytes() == b"added"
    assert not (old / "_internal" / "old.dll").exists()
    assert json.loads((old / "install_info.json").read_text())["version"] == "2.4.1"
    assert summary["files_shipped"] == 3


# ----------------------------------------------------------------------
# Installation and deferring
# ----------------------------------------------------------------------
def test_the_install_marker_is_what_makes_a_copy_installed(tmp_path):
    assert not updater.is_installed_copy(tmp_path)
    (tmp_path / "install_info.json").write_text('{"installed": true}', encoding="utf-8")
    assert updater.is_installed_copy(tmp_path)
    assert updater.read_install_info(tmp_path)["installed"] is True


def test_a_postponed_version_is_not_offered_again_for_a_day():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat()
    old = (now - timedelta(hours=30)).isoformat()

    assert updater.was_deferred_recently("2.5.0", "2.5.0", recent)
    assert not updater.was_deferred_recently("2.5.0", "2.5.0", old)
    assert not updater.was_deferred_recently("2.5.0", "2.4.9", recent)
    assert not updater.was_deferred_recently("2.5.0", "2.5.0", "")
    assert not updater.was_deferred_recently("2.5.0", "2.5.0", "not a date")


def test_release_notes_are_trimmed_for_the_dialog():
    notes = updater.release_notes_summary("x" * 5000, limit=100)
    assert len(notes) <= 120
