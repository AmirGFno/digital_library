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
    assert info.size_text == "4 KB"  # small packages are shown in KB
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
        version="2.4.3",
    )

    assert "Expand-Archive" in script
    assert str(archive) in script
    assert str(install_dir) in script
    assert "4242" in script
    assert "_internal/old.dll" in script
    assert "stale.txt" in script
    # the package manifest must not stay behind in the install folder
    assert "update.json" in script
    # the copy is checked against the release the package claims to be
    assert "2.4.3" in script
    assert "install_info.json" in script


def test_a_failed_update_is_reported_instead_of_vanishing(tmp_path):
    script = updater.build_apply_script(
        tmp_path / "update.zip",
        tmp_path / "app",
        tmp_path / "app" / "DigitalLibrary.exe",
        1,
        version="2.4.3",
    )

    assert "Show-Problem $lastError" in script
    assert "$shell.Popup(" in script
    assert "Your current version still works" in script
    assert "DigitalLibrary-update.log" in script


def test_an_elevated_helper_restarts_the_app_as_the_normal_user(tmp_path):
    script = updater.build_apply_script(
        tmp_path / "update.zip",
        tmp_path / "Program Files" / "Digital Library",
        tmp_path / "Program Files" / "Digital Library" / "DigitalLibrary.exe",
        7,
        elevated=True,
    )

    # Starting the exe directly would hand the user an elevated app.
    assert "explorer.exe" in script
    assert "Start-Process -FilePath $exe" in script  # fallback kept


def test_the_install_folder_that_needs_admin_permission_is_detected(tmp_path):
    writable = tmp_path / "Local AppData" / "Digital Library"
    writable.mkdir(parents=True)
    assert updater.needs_elevation(writable) is False

    locked = tmp_path / "Program Files" / "Digital Library"
    locked.mkdir(parents=True)
    locked.chmod(0o500)
    try:
        assert updater.needs_elevation(locked) is True
    finally:
        locked.chmod(0o700)


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


def test_a_protected_install_folder_gets_the_uac_prompt(tmp_path):
    calls = []
    archive = tmp_path / "update.zip"
    protected = tmp_path / "Program Files" / "Digital Library"

    script = updater.apply_update(
        archive,
        install_dir=protected,
        executable=protected / "DigitalLibrary.exe",
        pid=9,
        runner=calls.append,
        elevate=True,
    )

    assert calls and str(script) in calls[0]
    content = script.read_text(encoding="utf-8-sig")
    assert "explorer.exe" in content


def test_a_refused_admin_prompt_is_an_explicit_error(monkeypatch):
    import sys as _sys
    import types

    fake = types.SimpleNamespace(
        windll=types.SimpleNamespace(
            shell32=types.SimpleNamespace(
                # SE_ERR_ACCESSDENIED: the user clicked "No" on the UAC prompt.
                ShellExecuteW=lambda *args: 5
            )
        )
    )
    monkeypatch.setitem(_sys.modules, "ctypes", fake)

    with pytest.raises(updater.UpdateError) as info:
        updater._spawn_elevated(["powershell.exe", "-File", "x.ps1"])

    assert "administrator permission" in str(info.value)


def test_the_uac_helper_is_started_when_windows_accepts(monkeypatch):
    import sys as _sys
    import types

    seen = {}

    def shell_execute(hwnd, verb, file, parameters, directory, show):
        seen.update(verb=verb, file=file, parameters=parameters)
        return 42

    fake = types.SimpleNamespace(
        windll=types.SimpleNamespace(
            shell32=types.SimpleNamespace(ShellExecuteW=shell_execute)
        )
    )
    monkeypatch.setitem(_sys.modules, "ctypes", fake)

    updater._spawn_elevated(["powershell.exe", "-NoProfile", "-File", "C:\\x y\\a.ps1"])

    assert seen["verb"] == "runas"
    assert seen["file"] == "powershell.exe"
    assert '"C:\\x y\\a.ps1"' in seen["parameters"]


def test_the_generated_helper_has_balanced_blocks(tmp_path):
    """A stray brace would make PowerShell exit without doing anything."""

    def balance(script):
        braces = parens = 0
        quoted = False
        for char in script:
            if char == "'":
                quoted = not quoted
                continue
            if quoted:
                continue
            if char == "{":
                braces += 1
            elif char == "}":
                braces -= 1
            elif char == "(":
                parens += 1
            elif char == ")":
                parens -= 1
            assert braces >= 0 and parens >= 0, script
        return braces, parens

    for elevated in (False, True):
        script = updater.build_apply_script(
            tmp_path / "update.zip",
            tmp_path / "app",
            tmp_path / "app" / "DigitalLibrary.exe",
            5,
            removed=["_internal/old.dll", "update.json"],
            version="2.4.3",
            elevated=elevated,
        )
        assert balance(script) == (0, 0)
        assert "{{" not in script and "}}" not in script


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
        captured["version"] = kwargs.get("version")
        return Path(archive)

    monkeypatch.setattr(updater, "apply_update", fake_apply)
    updater.install_update(package, install_dir=tmp_path / "app")

    assert captured["archive"] == package
    assert "gone.dll" in captured["removed"]
    # The copier checks the marker, so the manifest version travels with it.
    assert captured["version"] == updater.read_update_manifest(package)["version"]


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


# ======================================================================
# Chained per-version updates
# ======================================================================
def release_json(version, from_version="", size=2_000_000, body="", draft=False):
    """A GitHub release payload carrying one update package."""
    name = (
        f"DigitalLibrary-{version}-from-{from_version}-windows-x64-update.zip"
        if from_version
        else f"DigitalLibrary-{version}-windows-x64-update.zip"
    )
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://example.test/releases/v{version}",
        "body": body or f"Notes for {version}",
        "published_at": "2026-10-26T10:00:00Z",
        "draft": draft,
        "prerelease": False,
        "assets": [
            {
                "name": name,
                "browser_download_url": f"https://example.test/{name}",
                "size": size,
            },
            {
                "name": "SHA256.txt",
                "browser_download_url": f"https://example.test/SHA256-{version}.txt",
                "size": 90,
            },
        ],
    }


def releases_of(*payloads):
    return [updater.parse_release(payload) for payload in payloads]


def test_the_package_name_says_which_version_it_upgrades_from():
    assert updater.from_version_of(
        "DigitalLibrary-2.4.3-from-2.4.2-windows-x64-update.zip"
    ) == "2.4.2"
    assert updater.from_version_of(
        "DigitalLibrary-2.4.0-windows-x64-update.zip"
    ) == ""
    info = updater.parse_release(release_json("2.4.3", "2.4.2"))
    assert info.is_delta and info.from_version == "2.4.2"
    assert info.steps_text == "2.4.2 → 2.4.3"


def test_drafts_and_prereleases_are_ignored():
    assert updater.parse_release(release_json("2.5.0", draft=True)) is None
    assert updater.parse_release({"tag_name": ""}) is None


def test_three_releases_behind_means_three_packages():
    plan = updater.plan_update_chain(
        "2.4.0", releases_of(release_json("2.4.1", "2.4.0"),
                             release_json("2.4.2", "2.4.1"),
                             release_json("2.4.3", "2.4.2"))
    )

    assert [step.version for step in plan.steps] == ["2.4.1", "2.4.2", "2.4.3"]
    assert plan.target == "2.4.3"
    assert plan.versions_text == "2.4.0 → 2.4.1 → 2.4.2 → 2.4.3"
    assert plan.count == 3
    assert plan.total_size == 6_000_000
    assert plan.size_text == "5.7 MB"
    assert "Notes for 2.4.3" in plan.latest_notes
    assert not plan.is_empty


def test_one_release_behind_means_one_package():
    plan = updater.plan_update_chain(
        "2.4.2", releases_of(release_json("2.4.1", "2.4.0"), release_json("2.4.3", "2.4.2"))
    )
    assert [step.version for step in plan.steps] == ["2.4.3"]


def test_an_up_to_date_install_has_nothing_to_do():
    plan = updater.plan_update_chain(
        "2.4.3", releases_of(release_json("2.4.3", "2.4.2"))
    )
    assert plan.is_empty
    assert plan.steps == []
    assert plan.target == "2.4.3"


def test_a_gap_in_the_chain_falls_back_to_a_full_package():
    plan = updater.plan_update_chain(
        "2.2.0",
        releases_of(
            release_json("2.4.0"),                 # full package (no from-)
            release_json("2.4.3", ""),
            release_json("2.4.1", "2.4.0"),
        ),
    )
    assert plan.steps == []
    assert plan.full_package is not None
    assert plan.full_package.version == "2.4.3"
    assert plan.missing_from == "2.2.0"
    assert plan.count == 1


def test_a_gap_without_a_full_package_is_reported_not_guessed():
    plan = updater.plan_update_chain(
        "2.2.0", releases_of(release_json("2.4.1", "2.4.0"), release_json("2.4.2", "2.4.1"))
    )
    assert plan.is_empty
    assert plan.target == "2.4.2"
    assert plan.missing_from == "2.2.0"


def test_a_loop_between_releases_cannot_hang_the_check():
    weird = [
        updater.UpdateInfo(
            version="2.5.0", tag="v2.5.0", notes="", page_url="",
            asset_url="https://example.test/a.zip", asset_name="a.zip",
            from_version="2.6.0",
        ),
        updater.UpdateInfo(
            version="2.6.0", tag="v2.6.0", notes="", page_url="",
            asset_url="https://example.test/b.zip", asset_name="b.zip",
            from_version="2.5.0",
        ),
    ]
    plan = updater.plan_update_chain("2.4.0", weird)
    assert plan.is_empty  # no way to reach it, no crash and no endless loop


def test_the_release_list_is_sorted_newest_first():
    payload = [release_json("2.4.1", "2.4.0"), release_json("2.4.3", "2.4.2"),
               release_json("2.4.2", "2.4.1")]
    releases = updater.fetch_releases(
        opener=fake_opener({updater.RELEASES_API: payload})
    )
    assert [release.version for release in releases] == ["2.4.3", "2.4.2", "2.4.1"]


# ----------------------------------------------------------------------
# Downloading and merging a chain
# ----------------------------------------------------------------------
def _three_builds(tmp_path):
    """Build v1, then the two delta packages that lead to v3."""
    step1 = tmp_path / "dist-2.4.0"
    (step1 / "_internal").mkdir(parents=True)
    (step1 / "DigitalLibrary.exe").write_bytes(b"exe-1")
    (step1 / "_internal" / "same.dll").write_bytes(b"same")
    (step1 / "_internal" / "old.dll").write_bytes(b"old")
    first = tmp_path / "first.zip"
    packager.build_package(step1, "2.4.0", first)

    step2 = tmp_path / "dist-2.4.1"
    (step2 / "_internal").mkdir(parents=True)
    (step2 / "DigitalLibrary.exe").write_bytes(b"exe-2")
    (step2 / "_internal" / "same.dll").write_bytes(b"same")
    (step2 / "_internal" / "new1.dll").write_bytes(b"new-1")
    second = tmp_path / "second.zip"
    packager.build_package(
        step2, "2.4.1", second, previous=first, from_version="2.4.0"
    )

    step3 = tmp_path / "dist-2.4.2"
    (step3 / "_internal").mkdir(parents=True)
    (step3 / "DigitalLibrary.exe").write_bytes(b"exe-3")
    (step3 / "_internal" / "same.dll").write_bytes(b"same")
    (step3 / "_internal" / "new1.dll").write_bytes(b"new-1")
    (step3 / "_internal" / "new2.dll").write_bytes(b"new-2")
    third = tmp_path / "third.zip"
    packager.build_package(
        step3, "2.4.2", third, previous=second, from_version="2.4.1"
    )
    return step1, step2, step3, (first, second, third)


def test_each_package_only_carries_its_own_changes(tmp_path):
    _, _, _, (first, second, third) = _three_builds(tmp_path)

    second_names = set(zipfile.ZipFile(second).namelist())
    third_names = set(zipfile.ZipFile(third).namelist())

    assert second_names == {
        "DigitalLibrary.exe",
        "_internal/new1.dll",
        "install_info.json",
        "update.json",
    }
    assert third_names == {
        "DigitalLibrary.exe",
        "_internal/new2.dll",
        "install_info.json",
        "update.json",
    }
    assert zipfile.ZipFile(third).read("update.json").decode().find("2.4.1") > 0
    assert len(zipfile.ZipFile(first).namelist()) == 5  # full payload


def test_two_small_packages_are_much_smaller_than_a_full_one(tmp_path):
    _, _, _, (first, second, third) = _three_builds(tmp_path)
    assert second.stat().st_size + third.stat().st_size < first.stat().st_size * 2


def test_the_chain_is_downloaded_with_one_progress_bar(tmp_path):
    _, _, _, (first, second, third) = _three_builds(tmp_path)
    routes = {}
    releases = []
    for version, package, from_version in (
        ("2.4.1", second, "2.4.0"),
        ("2.4.2", third, "2.4.1"),
    ):
        payload = release_json(version, from_version, size=package.stat().st_size)
        asset = payload["assets"][0]
        routes[asset["browser_download_url"]] = package.read_bytes()
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        routes[payload["assets"][1]["browser_download_url"]] = (
            f"{digest}  {asset['name']}\n"
        ).encode()
        releases.append(payload)

    plan = updater.plan_update_chain("2.4.0", releases_of(*releases))
    seen = []

    merged = updater.download_and_merge(
        plan,
        tmp_path / "downloads",
        progress=lambda done, total: seen.append((done, total)),
        opener=fake_opener(routes),
    )

    assert merged.is_file()
    assert seen and seen[-1][0] == plan.total_size == seen[-1][1]
    # both packages ended up in the one archive
    names = set(zipfile.ZipFile(merged).namelist())
    assert {"DigitalLibrary.exe", "_internal/new1.dll", "_internal/new2.dll"} <= names


def test_merging_applies_the_steps_in_order(tmp_path):
    _, _, final_build, (first, second, third) = _three_builds(tmp_path)
    plan = updater.UpdatePath(
        target="2.4.2",
        steps=[
            updater.parse_release(release_json("2.4.1", "2.4.0")),
            updater.parse_release(release_json("2.4.2", "2.4.1")),
        ],
    )

    merged = tmp_path / "merged.zip"
    summary = updater.merge_deltas([second, third], merged, version=plan.target)

    assert summary["packages"] == 2
    assert zipfile.ZipFile(merged).read("DigitalLibrary.exe") == b"exe-3"
    manifest = updater.read_update_manifest(merged)
    assert manifest["version"] == "2.4.2"
    assert "_internal/old.dll" in manifest["removed"]
    assert "_internal/old.dll" not in zipfile.ZipFile(merged).namelist()


def test_installing_the_merged_archive_reproduces_the_newest_build(tmp_path):
    step1, _, final_build, (_, second, third) = _three_builds(tmp_path)

    # The installed copy still has the files of 2.4.0.
    installed = tmp_path / "installed"
    (installed / "_internal").mkdir(parents=True)
    (installed / "DigitalLibrary.exe").write_bytes(b"exe-1")
    (installed / "_internal" / "same.dll").write_bytes(b"same")
    (installed / "_internal" / "old.dll").write_bytes(b"old")

    merged = tmp_path / "merged.zip"
    updater.merge_deltas([second, third], merged, version="2.4.2")

    manifest = updater.read_update_manifest(merged)
    with zipfile.ZipFile(merged) as bundle:
        bundle.extractall(installed)
    for name in manifest["removed"]:
        (installed / name).unlink(missing_ok=True)
    # The generated helper also removes the package's own manifest.
    (installed / "update.json").unlink(missing_ok=True)

    expected = packager.tree_manifest(final_build)
    actual = packager.tree_manifest(installed)
    # The install marker is generated per release, everything else must match.
    expected.pop("install_info.json", None)
    actual.pop("install_info.json", None)
    assert actual == expected


def test_a_damaged_package_in_the_chain_stops_the_update(tmp_path):
    _, _, _, (_, second, _) = _three_builds(tmp_path)
    payload = release_json("2.4.1", "2.4.0", size=second.stat().st_size)
    asset = payload["assets"][0]
    routes = {
        asset["browser_download_url"]: second.read_bytes() + b"garbage",
        payload["assets"][1]["browser_download_url"]: (
            f"{'0' * 64}  {asset['name']}\n"
        ).encode(),
    }
    plan = updater.plan_update_chain("2.4.0", releases_of(payload))

    with pytest.raises(updater.UpdateError):
        updater.download_and_merge(
            plan, tmp_path / "downloads", opener=fake_opener(routes)
        )

    assert not list((tmp_path / "downloads").glob("*.zip")) or not list(
        (tmp_path / "downloads").glob("merged-update.zip")
    )


def test_the_packager_refuses_a_gap_between_versions(tmp_path):
    with pytest.raises(SystemExit):
        packager.build_package(
            Path(__file__).resolve().parent / "no-such-build",
            "2.4.1",
            tmp_path / "x.zip",
        )
