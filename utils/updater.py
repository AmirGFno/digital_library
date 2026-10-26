"""
updater.py - find, download and apply updates for the installed edition.

The installed build puts an ``install_info.json`` marker next to its executable.
That marker tells the app it may update itself in place: it asks GitHub for the
newest release, downloads the small ``*-update.zip`` that holds only the files
which changed, verifies the published SHA-256 checksum and hands the archive to
a short PowerShell helper. The helper waits for the app to exit, replaces the
files (and removes the ones that disappeared) and starts the new version.

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
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
INSTALL_MARKER = config.INSTALL_MARKER
UPDATE_ASSET_SUFFIX = "-update.zip"
CHECKSUM_ASSET_NAME = "SHA256.txt"
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

    @property
    def can_install_in_place(self) -> bool:
        return bool(self.asset_url)

    @property
    def size_text(self) -> str:
        if self.asset_size <= 0:
            return ""
        megabytes = self.asset_size / (1024 * 1024)
        return f"{megabytes:.1f} MB"


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


def fetch_latest_release(opener=None, timeout: int = REQUEST_TIMEOUT) -> UpdateInfo:
    """Ask GitHub for the newest published release (raises UpdateError)."""
    try:
        with _open(RELEASES_API, opener, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"Could not reach the update server: {exc}") from exc

    if not isinstance(payload, dict) or not payload.get("tag_name"):
        raise UpdateError("The update server returned an unexpected answer.")

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
    body = str(payload.get("body") or "")
    return UpdateInfo(
        version=normalize_version(payload.get("tag_name")),
        tag=str(payload.get("tag_name")),
        notes=body[:6000],
        page_url=str(payload.get("html_url") or RELEASE_PAGE),
        asset_url=update_asset.url if update_asset else "",
        asset_name=update_asset.name if update_asset else "",
        asset_size=update_asset.size if update_asset else 0,
        checksum_url=checksum_asset.url if checksum_asset else "",
        published=str(payload.get("published_at") or ""),
    )


# ----------------------------------------------------------------------
# Applying the update in place
# ----------------------------------------------------------------------
def _ps_quote(value: object) -> str:
    """Single-quoted PowerShell literal."""
    return "'" + str(value).replace("'", "''") + "'"


def build_apply_script(
    archive: Path,
    install_dir: Path,
    executable: Path,
    pid: int,
    removed: Sequence[str] = (),
) -> str:
    """PowerShell helper that swaps the files once the app has exited."""
    removed_lines = "\n".join(f"    {_ps_quote(item)}" for item in removed) or ""
    return f"""# Digital Library in-place update helper.
$ErrorActionPreference = 'SilentlyContinue'
$log = Join-Path $env:TEMP 'DigitalLibrary-update.log'
function Write-Log($message) {{
    Add-Content -LiteralPath $log -Value ("{{0}} {{1}}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message)
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

$ok = $false
for ($attempt = 0; $attempt -lt 6; $attempt++) {{
    try {{
        Expand-Archive -LiteralPath $archive -DestinationPath $target -Force -ErrorAction Stop
        $ok = $true
        break
    }} catch {{
        Write-Log ("extract failed: " + $_.Exception.Message)
        Start-Sleep -Seconds 2
    }}
}}

if ($ok) {{
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
    Remove-Item -LiteralPath $archive -Force
    Write-Log 'update finished'
}} else {{
    Write-Log 'update failed, starting the previous version'
}}

if (Test-Path -LiteralPath $exe) {{
    Start-Process -FilePath $exe -WorkingDirectory $target
}}
"""


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
) -> Path:
    """Start the helper that installs ``archive`` after this process exits.

    Returns the generated script path. ``runner`` is injected by the tests so
    no process is ever started there.
    """
    folder = Path(install_dir) if install_dir else installation_dir()
    exe = Path(executable) if executable else executable_path()
    process_id = os.getpid() if pid is None else int(pid)
    script = build_apply_script(Path(archive), folder, exe, process_id, removed)

    target = Path(tempfile.mkdtemp(prefix="dl-update-")) / "apply-update.ps1"
    # Windows PowerShell reads a BOM as UTF-8; without it non-ASCII install
    # paths would be mangled.
    target.write_text(script, encoding="utf-8-sig")

    if runner is None:
        if sys.platform != "win32":
            raise UpdateError("In-place updates are only used on Windows.")
        runner = _spawn_detached
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
    logger.info("Update helper started (%s)", target)
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
    return apply_update(archive, install_dir=install_dir, removed=removed)


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
