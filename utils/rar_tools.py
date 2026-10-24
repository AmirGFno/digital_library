"""
Locate the external tool that RAR/CBR archives need.

RAR is a proprietary format: pure Python can list the entries of an archive but
cannot decompress them. ``rarfile`` therefore shells out to one of ``unrar``,
``unar``, ``bsdtar`` or ``7z``. On Windows those tools are usually installed
(WinRAR ships ``UnRAR.exe``, 7-Zip ships ``7z.exe``) but never in PATH, so the
application has to find them itself — otherwise CBR files show no cover at all.

This module searches, in order:

1. the path saved by the user in the reader settings (``rar_tool``)
2. the directories of WinRAR / 7-Zip / NanaZip installed through the registry
3. the usual installation folders (Program Files, LocalAppData, ...)
4. PATH

The result is cached; :func:`configure_rarfile` also resets ``rarfile``'s own
tool cache, because ``rarfile`` caches the *first* (possibly failed) lookup for
the whole process, which used to make CBR extraction fail until a restart.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from utils.logger import logger

WINDOWS = os.name == "nt"

#: executable name -> rarfile attribute that must point at it
TOOL_ATTRIBUTES = {
    "unrar": "UNRAR_TOOL",
    "unar": "UNAR_TOOL",
    "bsdtar": "BSDTAR_TOOL",
    "7z": "SEVENZIP_TOOL",
    "7zz": "SEVENZIP2_TOOL",
    "7za": "SEVENZIP_TOOL",
}

_TOOL_NAMES: Dict[str, List[str]] = {
    "unrar": ["UnRAR.exe", "unrar.exe", "unrar"],
    "unar": ["unar.exe", "unar"],
    "bsdtar": ["bsdtar.exe", "bsdtar"],
    "7z": ["7z.exe", "7zz.exe", "7za.exe", "7z", "7zz"],
}

_TOOL_DIRECTORIES = [
    ("%ProgramFiles%", "WinRAR"),
    ("%ProgramFiles(x86)%", "WinRAR"),
    ("%ProgramW6432%", "WinRAR"),
    ("%ProgramFiles%", "7-Zip"),
    ("%ProgramFiles(x86)%", "7-Zip"),
    ("%ProgramW6432%", "7-Zip"),
    ("%LOCALAPPDATA%", "Programs", "WinRAR"),
    ("%LOCALAPPDATA%", "Programs", "7-Zip"),
    ("%LOCALAPPDATA%", "7-Zip"),
    ("%LOCALAPPDATA%", "Microsoft", "WinGet", "Packages"),
    ("%ProgramFiles%", "NanaZip"),
    ("%ProgramFiles%", "PeaZip"),
]

_registry_cache: Optional[List[str]] = None
_active_tool: Optional[Dict[str, str]] = None


def _expand(parts) -> Path:
    return Path(*[os.path.expandvars(str(part)) for part in parts])


def _registry_directories() -> List[str]:
    """Directories recorded by the WinRAR / 7-Zip installers in the registry."""
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache

    directories: List[str] = []
    if not WINDOWS:
        _registry_cache = directories
        return directories

    try:
        import winreg  # noqa: PLC0415 - Windows only
    except ImportError:  # pragma: no cover - non Windows
        _registry_cache = directories
        return directories

    roots = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]
    keys = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WinRAR.exe",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\7zFM.exe",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\7z.exe",
        r"SOFTWARE\WinRAR",
        r"SOFTWARE\7-Zip",
        r"SOFTWARE\WOW6432Node\WinRAR",
        r"SOFTWARE\WOW6432Node\7-Zip",
    ]
    for root in roots:
        for key_path in keys:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    for value_name in ("", "Path", "InstallPath", "exe64", "exe32"):
                        try:
                            value, _ = winreg.QueryValueEx(key, value_name)
                        except OSError:
                            continue
                        if not isinstance(value, str) or not value:
                            continue
                        candidate = Path(value)
                        directory = candidate.parent if candidate.suffix else candidate
                        if directory.is_dir():
                            directories.append(str(directory))
            except OSError:
                continue

    # Uninstall entries know where WinRAR / 7-Zip really live.
    uninstall_roots = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    for root in roots:
        for key_path in uninstall_roots:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    count = winreg.QueryInfoKey(key)[0]
                    for index in range(count):
                        try:
                            name = winreg.EnumKey(key, index)
                            with winreg.OpenKey(key, name) as sub_key:
                                values = {}
                                for value_index in range(winreg.QueryInfoKey(sub_key)[1]):
                                    value_name, value, _ = winreg.EnumValue(sub_key, value_index)
                                    values[value_name] = value
                        except OSError:
                            continue
                        display = str(values.get("DisplayName") or "").lower()
                        if not any(token in display for token in ("winrar", "7-zip", "7zip", "nanazip")):
                            continue
                        location = values.get("InstallLocation") or values.get("DisplayIcon")
                        if not location:
                            continue
                        candidate = Path(str(location).strip('"'))
                        directory = candidate.parent if candidate.suffix else candidate
                        if directory.is_dir():
                            directories.append(str(directory))
            except OSError:
                continue

    _registry_cache = directories
    return directories


def _candidate_paths() -> List[Path]:
    """Every plausible location of a RAR capable tool, best first."""
    paths: List[Path] = []

    for parts in _TOOL_DIRECTORIES:
        directory = _expand(parts)
        for exe_name in ("UnRAR.exe", "7z.exe", "7zz.exe", "7za.exe"):
            paths.append(directory / exe_name)

    for directory in _registry_directories():
        for exe_name in ("UnRAR.exe", "unrar.exe", "7z.exe", "7zz.exe", "7za.exe", "bsdtar.exe"):
            paths.append(Path(directory) / exe_name)

    if WINDOWS:
        # Windows 10/11 ship libarchive based tar (bsdtar), which reads RAR.
        system_root = os.environ.get("SystemRoot") or r"C:\Windows"
        paths.append(Path(system_root) / "System32" / "tar.exe")

    return paths


def _usable(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def find_tool(preferred: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Return ``{"tool": name, "path": path}`` for the best available tool."""
    if preferred and Path(preferred).is_file():
        return {"tool": _tool_name_for(preferred), "path": str(Path(preferred))}

    for path in _candidate_paths():
        if _usable(path):
            return {"tool": _tool_name_for(path), "path": str(path)}

    # Finally trust PATH.
    for name, executables in (("unrar", ["unrar"]), ("7z", ["7z", "7zz", "7za"]),
                              ("bsdtar", ["bsdtar"]), ("unar", ["unar"])):
        for executable in executables:
            found = shutil.which(executable)
            if found:
                return {"tool": name, "path": found}

    return None


def _tool_name_for(path: str) -> str:
    name = Path(path).stem.lower()
    if name.startswith("unrar"):
        return "unrar"
    if name in ("7z", "7zz", "7za"):
        return "7z"
    if name.startswith("bsdtar") or name == "tar":
        return "bsdtar"
    if name.startswith("unar"):
        return "unar"
    return "unrar"


def _can_run(path: str) -> bool:
    """Quick sanity check that the executable really starts."""
    if not WINDOWS:
        # Avoid starting unrar in the background during tests.
        return Path(path).is_file()
    try:
        result = subprocess.run(
            [path, "i"], capture_output=True, timeout=8, text=True
        )
        return result.returncode in (0, 1, 7, 10)
    except Exception:
        try:
            result = subprocess.run(
                [path, "--version"], capture_output=True, timeout=8, text=True
            )
            return result.returncode == 0
        except Exception:
            return False


def configure_rarfile(force: bool = False) -> Optional[Dict[str, str]]:
    """Point ``rarfile`` at the discovered tool. Returns the tool information."""
    global _active_tool

    try:
        import rarfile
    except ImportError:  # pragma: no cover - rarfile is a hard requirement
        logger.warning("rarfile is not installed; CBR files cannot be opened")
        return None

    if _active_tool and not force:
        return _active_tool

    preferred = ""
    try:
        from utils.settings import settings

        preferred = str(settings.settings.get("reader", {}).get("rar_tool", "") or "")
    except Exception:
        preferred = ""

    tool = find_tool(preferred or None)
    if not tool:
        logger.warning(
            "No UnRAR/7-Zip/bsdtar found: CBR covers need WinRAR or 7-Zip installed"
        )
        _active_tool = None
        return None

    attribute = TOOL_ATTRIBUTES.get(tool["tool"])
    if attribute:
        setattr(rarfile, attribute, tool["path"])

    # rarfile caches its first lookup for the whole process; without this reset a
    # failed startup detection would keep failing even after the tool is found.
    try:
        rarfile.tool_setup(force=True)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"rarfile tool_setup failed: {exc}")

    _active_tool = tool
    logger.info(f"RAR support: {tool['tool']} ({tool['path']})")
    return tool


def active_tool() -> Optional[Dict[str, str]]:
    """Information about the tool in use, discovering it on first call."""
    return _active_tool or configure_rarfile()


def rar_support_available() -> bool:
    return active_tool() is not None


def describe_support() -> str:
    """Human readable status used in the reader settings dialog."""
    if sys.platform == "darwin":
        extra = "macOS ships `bsdtar`; install `unar` if covers stay empty."
    elif WINDOWS:
        extra = "Install WinRAR or 7-Zip to read CBR files."
    else:
        extra = "Install `unrar`, `p7zip` or `unar` to read CBR files."

    tool = active_tool()
    if tool:
        return f"RAR support: {tool['tool']} — {tool['path']}"
    return f"RAR support: not available. {extra}"
