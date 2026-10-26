"""
Configuration settings for the Digital Library application.

Paths are resolved so that the application works both from source and as a
frozen (PyInstaller) executable:

* Writable data (database, settings, covers, logs) always lives next to the
  executable / project root, so the app stays portable.
* Read-only resources (bundled icons, default cover) are loaded from the
  PyInstaller extraction directory when frozen.
"""
import os
import sys
from pathlib import Path

APP_NAME = "Digital Library"
APP_VERSION = "2.4.0"

# The setup installer drops this marker next to the executable. It is what
# tells the app apart from the portable single-file build: only an installed
# copy may replace its own files and must keep user data outside Program Files.
INSTALL_MARKER = "install_info.json"


def _app_dir() -> Path:
    """Directory where user data should be stored (next to the exe/source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resource_dir() -> Path:
    """Directory containing bundled read-only resources."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _app_dir()


def _user_data_dir() -> Path:
    """Per-user fallback used when the application folder is read-only."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return Path(base) / "DigitalLibrary"


def _is_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


APP_DIR = _app_dir()
RESOURCE_DIR = _resource_dir()


def is_installed_copy(directory: Path | None = None) -> bool:
    """True when this executable came from the setup installer.

    A source checkout is never an installed copy, even if a stray marker file
    exists: replacing files only makes sense for a packaged build.
    """
    if directory is None:
        if not getattr(sys, "frozen", False):
            return False
        folder = APP_DIR
    else:
        folder = Path(directory)
    return (folder / INSTALL_MARKER).is_file()


INSTALLED_COPY = is_installed_copy()

# Portable by default (data lives next to the executable); installed copies in
# read-only locations fall back to the per-user data directory. An installed
# copy always uses the per-user folder: updates rewrite the program files, so
# the library must never live inside the installation folder.
if INSTALLED_COPY:
    BASE_DIR = _user_data_dir()
else:
    BASE_DIR = APP_DIR if _is_writable(APP_DIR / "data") else _user_data_dir()

DATA_DIR = BASE_DIR / "data"
THUMBNAILS_DIR = BASE_DIR / "thumbnails"
LOGS_DIR = BASE_DIR / "logs"
CUSTOM_COVERS_DIR = BASE_DIR / "custom_covers"

ASSETS_DIR = RESOURCE_DIR / "assets"

# Database
DATABASE_PATH = DATA_DIR / "library.db"

# Thumbnail settings
THUMBNAIL_SIZE = (200, 280)
THUMBNAIL_FORMAT = "JPEG"
THUMBNAIL_QUALITY = 85

# UI settings
DEFAULT_COLUMNS = 4
CARD_WIDTH = 208
CARD_HEIGHT = 322
COVER_HEIGHT = 250

# Supported file extensions
SUPPORTED_EXTENSIONS = {
    "pdf": [".pdf"],
    "images": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"],
    "archives": [
        ".cbz", ".cbr", ".cb7", ".cbt", ".zip", ".rar", ".7z", ".tar", ".tar.gz", ".tgz"
    ],
}

ALL_EXTENSIONS = []
for _exts in SUPPORTED_EXTENSIONS.values():
    ALL_EXTENSIONS.extend(_exts)

# Extension groups used by the "open with" logic
FORMAT_GROUPS = {
    "archive": [".cbz", ".cbr", ".cb7", ".cbt", ".zip", ".rar", ".7z", ".tar", ".tar.gz", ".tgz"],
    "pdf": [".pdf"],
    "image": SUPPORTED_EXTENSIONS["images"],
}

# Create directories if they don't exist
for directory in [DATA_DIR, THUMBNAILS_DIR, ASSETS_DIR, LOGS_DIR, CUSTOM_COVERS_DIR]:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        # A read-only resource directory (e.g. _MEIPASS) must never crash startup.
        pass


def format_group_for(filepath: str) -> str:
    """Return 'archive', 'pdf', 'image' or 'other' for a file path."""
    lower = str(filepath).lower()
    for group, extensions in FORMAT_GROUPS.items():
        if any(lower.endswith(ext) for ext in extensions):
            return group
    return "other"
