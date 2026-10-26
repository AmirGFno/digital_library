"""
updater.py - find, download and apply updates for the installed edition.

The installed build puts an ``install_info.json`` marker next to its executable.
That marker tells the app it may update itself in place.

Every release publishes a small ``*-update.zip`` that only carries the files
that changed since the previous release, and says in its file name which
version it upgrades from::

    DigitalLibrary-2.4.3-from-2.4.2-windows-x64-update.zip

So an install on 2.4.0 that asks for updates finds three packages (2.4.0→2.4.1,
2.4.1→2.4.2, 2.4.2→2.4.3), downloads those three small files instead of one big
one, verifies every published SHA-256, merges them into a single archive and
hands that to a short PowerShell helper. The helper waits for the app to exit,
replaces the files (and removes the ones that disappeared) and starts the new
version.

A release whose update package has no ``from-`` part is a full package: it can
be applied on any version and is used when a gap in the chain leaves no other
way to reach the newest release.

A portable copy has no marker: it never rewrites itself and only points the
user at the release page.

Nothing in this module needs Qt, so it can be exercised by the unit tests
without a display.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import config
from config import APP_VERSION
from utils.logger import logger

REPOSITORY = "AmirGFno/digital_library"
RELEASES_API = (
    f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=40"
)
RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
INSTALL_MARKER = config.INSTALL_MARKER
UPDATE_ASSET_SUFFIX = "-update.zip"
CHECKSUM_ASSET_NAME = "SHA256.txt"
UPDATE_MANIFEST_NAME = "update.json"
# DigitalLibrary-2.4.3-from-2.4.2-windows-x64-update.zip
_DELTA_NAME_RE = re.compile(r"-from-v?(\d+(?:\.\d+){0,3})-windows-x64-update\.zip$", re.I)
REQUEST_TIMEOUT = 10
CHUNK_SIZE = 128 * 1024
MAX_DOWNLOAD_BYTES = 400 * 1024 * 1024
UPDATE_FOLDER = "updates"

ProgressCallback = Callable[[int, int], None]


class UpdateError(Exception):
    """Something went wrong while checking, downloading or applying."""


# ----------------------------------------------------------------------
# Versions
# ----------------------------------------------------------------------
def parse_version(text: object) -> tuple:
    """Turn ``v2.4.1`` / ``2.4`` into a comparable tuple of numbers."""
    numbers = re.findall(r"\d+", str(text or ""))
    if not numbers:
        return ()
    return tuple(int(number) for number in numbers[:4])


def normalize_version(text: object) -> str:
    """``v2.4.1`` -> ``2.4.1``; keeps the numeric part only."""
    numbers = re.findall(r"\d+", str(text or ""))
    return ".".join(str(int(number)) for number in numbers[:3])


def is_newer(candidate: object, current: object = APP_VERSION) -> bool:
    """True when ``candidate`` is a higher version than ``current``."""
    new = parse_version(candidate)
    old = parse_version(current)
    if not new:
        return False
    length = max(len(new), len(old))
    new += (0,) * (length - len(new))
    old += (0,) * (length - len(old))
    return new > old


# ----------------------------------------------------------------------
# Installation markers
# ----------------------------------------------------------------------
def installation_dir() -> Path:
    """Folder that holds the executable (and the installer marker)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def executable_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return installation_dir() / "main.py"


def read_install_info(directory: Optional[Path] = None) -> Dict:
    """Contents of ``install_info.json`` or an empty dict."""
    folder = Path(directory) if directory else installation_dir()
    path = folder / INSTALL_MARKER
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def is_installed_copy(directory: Optional[Path] = None) -> bool:
    """True for the setup-installed edition (source runs are never installed)."""
    if directory is None:
        return config.is_installed_copy()
    return (Path(directory) / INSTALL_MARKER).is_file()


def download_folder() -> Path:
    """Per-user folder for downloaded update packages."""
    return config._user_data_dir() / UPDATE_FOLDER


# ----------------------------------------------------------------------
# GitHub release
# ----------------------------------------------------------------------
@dataclass
class UpdateInfo:
    version: str
    tag: str
    notes: str
    page_url: str
    asset_url: str = ""
    asset_name: str = ""
    asset_size: int = 0
    checksum_url: str = ""
    published: str = ""
    # Version this package upgrades from; empty for a full package.
    from_version: str = ""
    manifest_from: str = ""

    @property
    def can_install_in_place(self) -> bool:
        return bool(self.asset_url)

    @property
    def is_delta(self) -> bool:
        return bool(self.from_version)

    @property
    def size_text(self) -> str:
        return size_text(self.asset_size)

    @property
    def steps_text(self) -> str:
        if self.from_version:
            return f"{self.from_version} → {self.version}"
        return self.version


def size_text(size: int) -> str:
    """``1234567`` -> ``1.2 MB`` (kilobytes for tiny packages)."""
    try:
        size = int(size)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


@dataclass
class _Asset:
    name: str
    url: str
    size: int = 0

    @classmethod
    def from_json(cls, payload: Dict) -> "_Asset":
        return cls(
            name=str(payload.get("name") or ""),
            url=str(payload.get("browser_download_url") or ""),
            size=int(payload.get("size") or 0),
        )


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"DigitalLibrary-Updater/{APP_VERSION}",
        },
    )


def _open(url: str, opener=None, timeout: int = REQUEST_TIMEOUT):
    opener = opener or urllib.request.urlopen
    return opener(_request(url), timeout=timeout)


def _download_asset(
    asset: _Asset, destination: Path, progress: Optional[ProgressCallback] = None, opener=None
) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    logger.info("Downloading update package %s", asset.url)
    try:
        with _open(asset.url, opener) as response:
            try:
                total = int(response.headers.get("Content-Length") or asset.size or 0)
            except (TypeError, ValueError):
                total = asset.size
            if total > MAX_DOWNLOAD_BYTES:
                raise UpdateError("The update package is unexpectedly large.")
            done = 0
            with open(temporary, "wb") as handle:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if done > MAX_DOWNLOAD_BYTES:
                        raise UpdateError("The update package is unexpectedly large.")
                    if progress:
                        try:
                            progress(done, total)
                        except Exception:  # a broken callback must not stop the download
                            logger.debug("Update progress callback failed", exc_info=True)
    except UpdateError:
        temporary.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc

    os.replace(temporary, destination)
    return destination


def _checksum_for(checksum_url: str, asset_name: str, opener=None) -> str:
    if not checksum_url:
        return ""
    try:
        with _open(checksum_url, opener) as response:
            text = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"Could not read the checksum file: {exc}") from exc
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == asset_name:
            return parts[0].lower()
    raise UpdateError("The checksum file does not mention the update package.")


def download_update(
    info: UpdateInfo,
    destination_dir: Optional[Path] = None,
    progress: Optional[ProgressCallback] = None,
    opener=None,
) -> Path:
    """Download the update package and verify its published SHA-256."""
    if not info.can_install_in_place:
        raise UpdateError("This release has no update package.")
    folder = Path(destination_dir) if destination_dir else download_folder()
    asset = _Asset(info.asset_name, info.asset_url, info.asset_size)
    archive = _download_asset(asset, folder / info.asset_name, progress=progress, opener=opener)
    expected = _checksum_for(info.checksum_url, info.asset_name, opener=opener)
    if expected and not verify_sha256(archive, expected):
        archive.unlink(missing_ok=True)
        raise UpdateError("The downloaded package is damaged (checksum mismatch).")
    logger.info("Update package ready: %s", archive)
    return archive


def download_chain(
    path_spec: UpdatePath,
    destination_dir: Optional[Path] = None,
    progress: Optional[ProgressCallback] = None,
    opener=None,
) -> List[Path]:
    """Download every package the plan needs, as one progress stream."""
    packages = list(path_spec.steps)
    if not packages and path_spec.full_package is not None:
        packages = [path_spec.full_package]
    if not packages:
        raise UpdateError("There is nothing to download for this update.")

    total = sum(int(package.asset_size or 0) for package in packages)
    downloaded_before = 0
    archives: List[Path] = []
    for index, package in enumerate(packages, start=1):
        def report(done: int, size: int, base: int = downloaded_before, step=index):
            if progress is None:
                return
            if total > 0:
                progress(min(base + done, total), total)
            else:
                progress(done, size or 0)

        logger.info(
            "Updating %s (%s/%s)", package.steps_text, index, len(packages)
        )
        archive = download_update(
            package, destination_dir, progress=report, opener=opener
        )
        archives.append(archive)
        downloaded_before += int(package.asset_size or 0)
    return archives


def merge_deltas(
    packages: Sequence[Path], output: Path, version: str = ""
) -> Dict:
    """Combine step packages into one archive that can be extracted once.

    Later packages win, so applying the merged archive gives exactly the same
    files as applying the packages one after another. The files that have to
    disappear when the last package is applied are collected as well.
    """
    packages = [Path(package) for package in packages]
    if not packages:
        raise UpdateError("There is no package to merge.")

    entries: Dict[str, tuple] = {}
    removed = set()
    last_manifest: Dict = {}
    for package in packages:
        manifest = read_update_manifest(package)
        try:
            with zipfile.ZipFile(package) as bundle:
                names = [
                    name
                    for name in bundle.namelist()
                    if not name.endswith("/") and name != UPDATE_MANIFEST_NAME
                ]
        except (OSError, zipfile.BadZipFile) as exc:
            raise UpdateError(f"The downloaded package is unreadable: {exc}") from exc

        for name in names:
            entries[name] = (package, name)
            removed.discard(name)
        for name in manifest.get("removed") or []:
            relative = str(name).replace("\\", "/").strip("/")
            if relative:
                removed.add(relative)
                entries.pop(relative, None)
        if manifest:
            last_manifest = manifest

    if not entries:
        raise UpdateError("The downloaded packages are empty.")

    removed -= set(entries)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as target:
            for name in sorted(entries):
                package, inner = entries[name]
                with zipfile.ZipFile(package) as bundle, bundle.open(inner) as source:
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    with target.open(info, "w") as destination:
                        while True:
                            chunk = source.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            destination.write(chunk)
            manifest_out = {
                "version": version or str(last_manifest.get("version") or ""),
                "from_version": str(
                    (last_manifest.get("from_version") if len(packages) == 1 else "")
                    or ""
                ),
                "files": last_manifest.get("files") or {},
                "removed": sorted(removed),
                "merged_packages": len(packages),
                "merged_versions": [package.name for package in packages],
            }
            target.writestr(
                UPDATE_MANIFEST_NAME,
                json.dumps(manifest_out, indent=1, sort_keys=True) + "\n",
            )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, output)
    logger.info(
        "Merged %s package(s) into %s (%s removed)",
        len(packages),
        output,
        len(removed),
    )
    return {
        "archive": str(output),
        "files": len(entries),
        "removed": sorted(removed),
        "packages": len(packages),
    }


def download_and_merge(
    path_spec: UpdatePath,
    destination_dir: Optional[Path] = None,
    progress: Optional[ProgressCallback] = None,
    opener=None,
) -> Path:
    """The whole download half of an update: fetch every step, merge, return one zip."""
    folder = Path(destination_dir) if destination_dir else download_folder()
    archives = download_chain(path_spec, folder, progress=progress, opener=opener)
    merged = folder / "merged-update.zip"
    merge_deltas(archives, merged, version=path_spec.target)
    if len(archives) > 1:
        for archive in archives:
            # The merged archive holds everything the steps carried.
            Path(archive).unlink(missing_ok=True)
    return merged


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> bool:
    if not expected:
        return True
    try:
        actual = sha256_file(Path(path))
    except OSError:
        return False
    return actual == str(expected).strip().lower()


def parse_checksum_text(text: str) -> Dict[str, str]:
    checksums: Dict[str, str] = {}
    for line in str(text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            checksums[parts[-1].lstrip("*")] = parts[0].lower()
    return checksums


def from_version_of(asset_name: str) -> str:
    """``...-from-2.4.2-windows-x64-update.zip`` -> ``2.4.2`` (else ``""``)."""
    match = _DELTA_NAME_RE.search(str(asset_name or ""))
    return normalize_version(match.group(1)) if match else ""


def parse_release(payload: Dict) -> Optional[UpdateInfo]:
    """Turn one GitHub release payload into an :class:`UpdateInfo`."""
    if not isinstance(payload, dict) or not payload.get("tag_name"):
        return None
    if payload.get("draft") or payload.get("prerelease"):
        return None

    assets = [
        _Asset.from_json(item)
        for item in payload.get("assets") or []
        if isinstance(item, dict)
    ]
    update_asset = next(
        (item for item in assets if item.name.endswith(UPDATE_ASSET_SUFFIX)), None
    )
    checksum_asset = next(
        (item for item in assets if item.name == CHECKSUM_ASSET_NAME), None
    )
    return UpdateInfo(
        version=normalize_version(payload.get("tag_name")),
        tag=str(payload.get("tag_name")),
        notes=str(payload.get("body") or "")[:6000],
        page_url=str(payload.get("html_url") or RELEASE_PAGE),
        asset_url=update_asset.url if update_asset else "",
        asset_name=update_asset.name if update_asset else "",
        asset_size=update_asset.size if update_asset else 0,
        checksum_url=checksum_asset.url if checksum_asset else "",
        published=str(payload.get("published_at") or ""),
        from_version=from_version_of(update_asset.name) if update_asset else "",
    )


def fetch_releases(opener=None, timeout: int = REQUEST_TIMEOUT) -> List[UpdateInfo]:
    """Every published release that carries something to download."""
    try:
        with _open(RELEASES_API, opener, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"Could not reach the update server: {exc}") from exc

    if isinstance(payload, dict):
        # An error object from the API rather than a list of releases.
        payload = [payload]
    if not isinstance(payload, list):
        raise UpdateError("The update server returned an unexpected answer.")

    releases = []
    for item in payload:
        info = parse_release(item)
        if info is not None and info.version:
            releases.append(info)
    if not releases:
        raise UpdateError("No published release was found.")
    releases.sort(key=lambda release: parse_version(release.version), reverse=True)
    return releases


def fetch_latest_release(opener=None, timeout: int = REQUEST_TIMEOUT) -> UpdateInfo:
    """The newest published release."""
    return fetch_releases(opener, timeout)[0]


@dataclass
class UpdatePath:
    """How to get from the installed version to the newest one."""

    target: str = ""
    steps: List[UpdateInfo] = None
    full_package: Optional[UpdateInfo] = None
    missing_from: str = ""

    def __post_init__(self):
        if self.steps is None:
            self.steps = []

    @property
    def is_empty(self) -> bool:
        return not self.steps and self.full_package is None

    @property
    def latest_notes(self) -> str:
        if self.steps:
            return self.steps[-1].notes
        if self.full_package is not None:
            return self.full_package.notes
        return ""

    @property
    def total_size(self) -> int:
        packages = self.steps or ([self.full_package] if self.full_package else [])
        return sum(int(package.asset_size or 0) for package in packages)

    @property
    def size_text(self) -> str:
        return size_text(self.total_size)

    @property
    def versions_text(self) -> str:
        """``2.4.0 → 2.4.1 → 2.4.2`` for the dialog."""
        chain = [step.version for step in self.steps]
        if self.full_package is not None and not chain:
            return self.full_package.version
        if chain:
            chain.insert(0, self.steps[0].from_version or "")
        return " → ".join(part for part in chain if part)

    @property
    def count(self) -> int:
        return len(self.steps) or (1 if self.full_package else 0)


def plan_update_chain(
    current_version: str, releases: Sequence[UpdateInfo]
) -> UpdatePath:
    """Pick the shortest chain of packages that reaches the newest release.

    Every release names the version it upgrades from, so the chain can be built
    from the release list alone - without downloading a single package first.
    """
    published = [release for release in releases if release.version]
    if not published:
        return UpdatePath()

    latest = published[0]
    for release in published[1:]:
        if parse_version(release.version) > parse_version(latest.version):
            latest = release
    target = normalize_version(latest.version)
    if not is_newer(target, current_version):
        return UpdatePath(target=target)

    usable = [release for release in published if release.can_install_in_place]
    by_from = {}
    for release in usable:
        if release.from_version:
            key = normalize_version(release.from_version)
            known = by_from.get(key)
            if known is None or parse_version(release.version) > parse_version(known.version):
                by_from[key] = release
    full_packages = [release for release in usable if not release.from_version]

    steps: List[UpdateInfo] = []
    version = normalize_version(current_version)
    seen = set()
    while is_newer(target, version):
        step = by_from.get(version)
        if step is None or step.version in seen:
            best_full = next(
                (
                    package
                    for package in full_packages
                    if normalize_version(package.version) == target
                ),
                None,
            )
            return UpdatePath(
                target=target, steps=[], full_package=best_full, missing_from=version
            )
        seen.add(step.version)
        steps.append(step)
        version = normalize_version(step.version)
        if len(steps) > 100:  # a cycle would otherwise loop forever
            break
    return UpdatePath(target=target, steps=steps)


# ----------------------------------------------------------------------
# Applying the update in place
# ----------------------------------------------------------------------
def _ps_quote(value: object) -> str:
    """Single-quoted PowerShell literal."""
    return "'" + str(value).replace("'", "''") + "'"


def needs_elevation(directory: Optional[Path] = None) -> bool:
    """True when this user cannot write to the install folder.

    The setup program installs under ``Program Files``, which a normally
    started app may not modify; the update then has to ask Windows for
    administrator permission.
    """
    folder = Path(directory) if directory else installation_dir()
    probe = folder / f".dl-write-test-{os.getpid()}"
    try:
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return False
    except OSError:
        return True


def build_apply_script(
    archive: Path,
    install_dir: Path,
    executable: Path,
    pid: int,
    removed: Sequence[str] = (),
    version: str = "",
    elevated: bool = False,
) -> str:
    """PowerShell helper that swaps the files once the app has exited.

    Every outcome is visible: a failure pops up a message with the log path
    instead of silently reopening the old version, and the copy step checks
    that the new files really carry the expected version.
    """
    # The package carries its own manifest; it must not stay in the install
    # folder after it has been applied.
    files_to_remove = list(dict.fromkeys([*removed, UPDATE_MANIFEST_NAME]))
    removed_lines = "\n".join(f"    {_ps_quote(item)}" for item in files_to_remove) or ""
    if elevated:
        # An elevated process would start an elevated app; hand the restart
        # back to the shell so the app keeps running as the normal user.
        restart = """$explorer = Join-Path $env:WINDIR 'explorer.exe'
if (Test-Path -LiteralPath $explorer) {
    Write-Log 'starting the app through the shell'
    Start-Process -FilePath $explorer -ArgumentList ('"' + $exe + '"')
} else {
    Start-Process -FilePath $exe -WorkingDirectory $target
}"""
    else:
        restart = "Start-Process -FilePath $exe -WorkingDirectory $target"

    return f"""# Digital Library in-place update helper.
$ErrorActionPreference = 'SilentlyContinue'
$log = Join-Path $env:TEMP 'DigitalLibrary-update.log'
function Write-Log($message) {{
    Add-Content -LiteralPath $log -Value ("{{0}} {{1}}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message)
}}
function Show-Problem($message) {{
    Write-Log ("problem: " + $message)
    try {{
        $shell = New-Object -ComObject WScript.Shell
        $shell.Popup(("The update could not be installed.`n`n" + $message + "`n`nYour current version still works. Log: " + $log), 0, 'Digital Library', 16) | Out-Null
    }} catch {{ }}
}}
Write-Log 'update helper started'

$targetPid = {int(pid)}
for ($i = 0; $i -lt 900; $i++) {{
    if (-not (Get-Process -Id $targetPid -ErrorAction SilentlyContinue)) {{ break }}
    Start-Sleep -Milliseconds 200
}}
Start-Sleep -Milliseconds 600

$archive = {_ps_quote(archive)}
$target = {_ps_quote(install_dir)}
$exe = {_ps_quote(executable)}
$expected = {_ps_quote(version)}

$copied = $false
$lastError = ''
for ($attempt = 0; $attempt -lt 6; $attempt++) {{
    try {{
        Expand-Archive -LiteralPath $archive -DestinationPath $target -Force -ErrorAction Stop
        $copied = $true
        break
    }} catch {{
        $lastError = $_.Exception.Message
        Write-Log ("extract failed: " + $lastError)
        Start-Sleep -Seconds 2
    }}
}}

$ok = $copied
if ($copied) {{
    Write-Log 'new files copied'
    $removedFiles = @(
{removed_lines}
    )
    foreach ($relative in $removedFiles) {{
        if ([string]::IsNullOrWhiteSpace($relative)) {{ continue }}
        $old = Join-Path $target $relative
        if (Test-Path -LiteralPath $old) {{
            Remove-Item -LiteralPath $old -Force
            Write-Log ("removed " + $relative)
        }}
    }}
    if ($expected) {{
        $marker = Join-Path $target 'install_info.json'
        $installed = ''
        if (Test-Path -LiteralPath $marker) {{
            try {{
                $installed = (Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json).version
            }} catch {{
                $installed = ''
            }}
        }}
        if ($installed -ne $expected) {{
            $ok = $false
            $lastError = "the copied files report version '" + $installed + "' instead of '" + $expected + "'"
            Write-Log $lastError
        }}
    }}
}}

if ($ok) {{
    Write-Log 'update finished'
    Remove-Item -LiteralPath $archive -Force
}} else {{
    if (-not $lastError) {{
        $lastError = 'the files could not be replaced'
    }}
    Show-Problem $lastError
}}

if (Test-Path -LiteralPath $exe) {{
    {restart.replace(chr(10), chr(10) + "    ")}
}}
"""


def _spawn_elevated(command: List[str]) -> None:
    """Start the helper through the Windows UAC prompt ("runas")."""
    import ctypes

    parameters = subprocess.list2cmdline([str(item) for item in command[1:]])
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(command[0]), parameters, None, 0
    )
    if result <= 32:
        if result == 5:
            raise UpdateError(
                "The update needs administrator permission. Windows asked for "
                "it, but the request was refused, so nothing was changed."
            )
        raise UpdateError(
            "The update helper could not start (Windows error "
            f"{int(result)}). Download the setup program from the releases page."
        )


def _spawn_detached(command: List[str]) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    subprocess.Popen(
        command,
        creationflags=flags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def apply_update(
    archive: Path,
    install_dir: Optional[Path] = None,
    removed: Sequence[str] = (),
    pid: Optional[int] = None,
    executable: Optional[Path] = None,
    runner: Optional[Callable[[List[str]], None]] = None,
    version: str = "",
    elevate: Optional[bool] = None,
) -> Path:
    """Start the helper that installs ``archive`` after this process exits.

    When the folder needs administrator rights (an install under Program
    Files) the helper is started with a UAC prompt *before* the app closes, so
    a refusal is reported in the dialog instead of leaving a half-closed app
    and an unchanged version. ``runner`` is injected by the tests so no
    process is ever started there.
    """
    folder = Path(install_dir) if install_dir else installation_dir()
    exe = Path(executable) if executable else executable_path()
    process_id = os.getpid() if pid is None else int(pid)
    need_admin = needs_elevation(folder) if elevate is None else bool(elevate)
    script = build_apply_script(
        Path(archive),
        folder,
        exe,
        process_id,
        removed,
        version=version,
        elevated=need_admin,
    )

    target = Path(tempfile.mkdtemp(prefix="dl-update-")) / "apply-update.ps1"
    # Windows PowerShell reads a BOM as UTF-8; without it non-ASCII install
    # paths would be mangled.
    target.write_text(script, encoding="utf-8-sig")

    if runner is None:
        if sys.platform != "win32":
            raise UpdateError("In-place updates are only used on Windows.")
        runner = _spawn_elevated if need_admin else _spawn_detached
    runner(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(target),
        ]
    )
    logger.info(
        "Update helper started (%s, administrator=%s)", target, need_admin
    )
    return target


def read_update_manifest(archive: Path) -> Dict:
    """The ``update.json`` inside a patch package (empty dict when missing)."""
    try:
        with zipfile.ZipFile(Path(archive)) as bundle:
            if "update.json" not in bundle.namelist():
                return {}
            payload = json.loads(bundle.read("update.json").decode("utf-8"))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        logger.warning("Could not read the update manifest: %s", exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def install_update(archive: Path, install_dir: Optional[Path] = None) -> Path:
    """Apply a downloaded package, including the files it removes."""
    manifest = read_update_manifest(archive)
    removed = [str(item) for item in manifest.get("removed") or [] if str(item).strip()]
    version = str(manifest.get("version") or "")
    return apply_update(
        archive, install_dir=install_dir, removed=removed, version=version
    )


def cleanup_downloads(folder: Optional[Path] = None) -> None:
    """Remove packages left behind by an older attempt."""
    directory = Path(folder) if folder else download_folder()
    if not directory.is_dir():
        return
    for path in directory.glob("*.zip"):
        try:
            path.unlink()
        except OSError:
            logger.debug("Could not remove %s", path, exc_info=True)


# ----------------------------------------------------------------------
# Deferring a prompt
# ----------------------------------------------------------------------
def was_deferred_recently(
    version: str, deferred_version: str, deferred_at: str, hours: int = 24
) -> bool:
    """True when the same version was postponed less than ``hours`` ago."""
    if not version or normalize_version(version) != normalize_version(deferred_version):
        return False
    try:
        moment = datetime.fromisoformat(str(deferred_at))
    except (TypeError, ValueError):
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - moment < timedelta(hours=hours)


def release_notes_summary(notes: str, limit: int = 2400) -> str:
    """Plain text release notes, trimmed for the dialog."""
    text = str(notes or "").strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n…"
    return text


def iter_files(directory: Path) -> Iterable[Path]:
    for path in sorted(Path(directory).rglob("*")):
        if path.is_file():
            yield path
