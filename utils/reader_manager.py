"""
Reader management: detect and launch popular comic/book readers.

Supports the most common comic readers on Windows, Linux and macOS and lets the
user add any external application as a custom reader. A reader can be assigned
globally, overridden per file type (archives / PDF / images), or the operating
system default can be used.

Detection is best-effort and never raises: a missing registry key or binary only
means that reader is reported as unavailable.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from utils.logger import logger

SYSTEM_READER_ID = "system"
FORMAT_GROUPS = ("archive", "pdf", "image")
FORMAT_LABELS = {
    "archive": "Comics (CBZ/CBR/CB7/CBT/ZIP/RAR/7z)",
    "pdf": "PDF documents",
    "image": "Images (JPG/PNG/WebP...)",
}


@dataclass
class ReaderInfo:
    """Description of an application that can open comic/book files."""

    id: str
    name: str
    executable: str = ""
    formats: Tuple[str, ...] = FORMAT_GROUPS
    source: str = "builtin"  # builtin | custom | detected
    arguments: Tuple[str, ...] = ()
    app_bundle: bool = False
    available: bool = False
    note: str = ""

    @property
    def is_system(self) -> bool:
        return self.id == SYSTEM_READER_ID

    def supports(self, format_group: str) -> bool:
        return "all" in self.formats or format_group in self.formats

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.executable,
            "formats": list(self.formats),
            "arguments": list(self.arguments),
            "app_bundle": self.app_bundle,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ReaderInfo":
        formats = tuple(data.get("formats") or FORMAT_GROUPS)
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or "Custom reader"),
            executable=str(data.get("path") or ""),
            formats=formats,
            source="custom",
            arguments=tuple(data.get("arguments") or ()),
            app_bundle=bool(data.get("app_bundle", False)),
            available=bool(data.get("path")) and Path(str(data.get("path"))).exists(),
        )


@dataclass(frozen=True)
class ReaderDefinition:
    """Static catalog entry for a known reader."""

    id: str
    name: str
    formats: Tuple[str, ...]
    windows: Tuple[str, ...] = ()
    commands: Tuple[str, ...] = ()
    mac_apps: Tuple[str, ...] = ()
    mac_commands: Tuple[str, ...] = ()
    arguments: Tuple[str, ...] = ()
    # Install folders whose file name depends on the version, such as the
    # portable "SumatraPDF-3.5.2-64.exe" or an ACBR folder named after its
    # version. Patterns are expanded with %VARS% and matched with glob.
    windows_globs: Tuple[str, ...] = ()
    # Registry keys that store the install folder of the application.
    windows_install_keys: Tuple[str, ...] = ()
    # Executable names to look for inside those folders.
    windows_install_exes: Tuple[str, ...] = ()


WINDOWS = sys.platform.startswith("win")
MACOS = sys.platform == "darwin"
LINUX = not WINDOWS and not MACOS


def _env_path(*parts: str) -> str:
    """Join environment variables such as %ProgramFiles%/Vendor/App.exe."""
    expanded = [os.path.expandvars(part) for part in parts]
    return str(Path(*expanded))


CATALOG: Tuple[ReaderDefinition, ...] = (
    ReaderDefinition(
        id="cdisplayex",
        name="CDisplayEx",
        formats=("archive", "pdf", "image"),
        windows=(
            _env_path("%ProgramFiles%", "CDisplayEx", "CDisplayEx.exe"),
            _env_path("%ProgramFiles(x86)%", "CDisplayEx", "CDisplayEx.exe"),
            _env_path("%LOCALAPPDATA%", "Programs", "CDisplayEx", "CDisplayEx.exe"),
            _env_path("%APPDATA%", "CDisplayEx", "CDisplayEx.exe"),
        ),
        commands=("CDisplayEx",),
    ),
    ReaderDefinition(
        id="yacreader",
        name="YACReader",
        formats=("archive", "pdf", "image"),
        windows=(
            _env_path("%ProgramFiles%", "YACReader", "YACReader.exe"),
            _env_path("%ProgramFiles(x86)%", "YACReader", "YACReader.exe"),
        ),
        commands=("yacreader", "YACReader"),
        mac_apps=("/Applications/YACReader.app",),
        mac_commands=("yacreader",),
    ),
    ReaderDefinition(
        id="comicrack",
        name="ComicRack",
        formats=("archive", "pdf"),
        windows=(
            _env_path("%ProgramFiles%", "ComicRack", "ComicRack.exe"),
            _env_path("%ProgramFiles(x86)%", "ComicRack", "ComicRack.exe"),
            _env_path("%LOCALAPPDATA%", "ComicRack", "ComicRack.exe"),
        ),
        commands=("ComicRack",),
    ),
    ReaderDefinition(
        id="mcomix",
        name="MComix",
        formats=("archive", "pdf", "image"),
        windows=(
            _env_path("%ProgramFiles%", "MComix", "MComix.exe"),
            _env_path("%ProgramFiles(x86)%", "MComix", "MComix.exe"),
        ),
        commands=("mcomix", "MComix", "comix"),
    ),
    ReaderDefinition(
        id="sumatrapdf",
        name="SumatraPDF",
        formats=("pdf", "archive"),
        windows=(
            _env_path("%ProgramFiles%", "SumatraPDF", "SumatraPDF.exe"),
            _env_path("%ProgramFiles(x86)%", "SumatraPDF", "SumatraPDF.exe"),
            _env_path("%LOCALAPPDATA%", "SumatraPDF", "SumatraPDF.exe"),
            _env_path("%ProgramFiles%", "SumatraPDF", "SumatraPDF-3.5.2-64.exe"),
            _env_path("%ProgramFiles%", "SumatraPDF", "SumatraPDF-3.4.6-64.exe"),
        ),
        commands=("SumatraPDF", "sumatrapdf"),
        # Portable builds are named after the version: SumatraPDF-3.5.2-64.exe
        windows_globs=(
            _env_path("%ProgramFiles%", "SumatraPDF", "SumatraPDF*.exe"),
            _env_path("%ProgramFiles(x86)%", "SumatraPDF", "SumatraPDF*.exe"),
            _env_path("%LOCALAPPDATA%", "SumatraPDF", "SumatraPDF*.exe"),
            _env_path("%LOCALAPPDATA%", "Programs", "SumatraPDF", "SumatraPDF*.exe"),
        ),
    ),
    ReaderDefinition(
        id="adobe-reader",
        name="Adobe Acrobat Reader",
        formats=("pdf",),
        windows=(
            _env_path("%ProgramFiles(x86)%", "Adobe", "Acrobat Reader DC", "Reader",
                      "AcroRd32.exe"),
            _env_path("%ProgramFiles%", "Adobe", "Acrobat Reader DC", "Reader",
                      "AcroRd32.exe"),
            _env_path("%ProgramFiles(x86)%", "Adobe", "Acrobat Reader", "Reader",
                      "AcroRd32.exe"),
            _env_path("%ProgramFiles%", "Adobe", "Acrobat Reader", "Reader",
                      "AcroRd32.exe"),
        ),
        commands=("AcroRd32", "acrobat", "acroread"),
        # Adobe stores the install folder per release (11.0, 2015, DC...) in
        # the registry instead of using a fixed path.
        windows_install_keys=(
            r"SOFTWARE\Adobe\Acrobat Reader",
            r"SOFTWARE\WOW6432Node\Adobe\Acrobat Reader",
        ),
        windows_install_exes=("Reader\AcroRd32.exe", "AcroRd32.exe"),
    ),
    ReaderDefinition(
        id="adobe-acrobat",
        name="Adobe Acrobat",
        formats=("pdf",),
        windows=(
            _env_path("%ProgramFiles%", "Adobe", "Acrobat DC", "Acrobat", "Acrobat.exe"),
            _env_path("%ProgramFiles(x86)%", "Adobe", "Acrobat DC", "Acrobat",
                      "Acrobat.exe"),
            _env_path("%ProgramFiles%", "Adobe", "Acrobat", "Acrobat", "Acrobat.exe"),
            _env_path("%ProgramFiles(x86)%", "Adobe", "Acrobat", "Acrobat",
                      "Acrobat.exe"),
        ),
        commands=("Acrobat",),
        windows_install_keys=(
            r"SOFTWARE\Adobe\Adobe Acrobat",
            r"SOFTWARE\WOW6432Node\Adobe\Adobe Acrobat",
        ),
        windows_install_exes=("Acrobat.exe", r"Acrobat\Acrobat.exe"),
    ),
    ReaderDefinition(
        id="acbr",
        name="ACBR Comic Book Reader",
        formats=("archive", "pdf", "image"),
        windows=(
            _env_path("%ProgramFiles%", "ACBR Comic Book Reader",
                      "ACBR Comic Book Reader.exe"),
            _env_path("%ProgramFiles(x86)%", "ACBR Comic Book Reader",
                      "ACBR Comic Book Reader.exe"),
            _env_path("%LOCALAPPDATA%", "Programs", "ACBR Comic Book Reader",
                      "ACBR Comic Book Reader.exe"),
            _env_path("%LOCALAPPDATA%", "Programs", "ACBR", "ACBR Comic Book Reader.exe"),
            _env_path("%ProgramFiles%", "ACBR", "ACBR Comic Book Reader.exe"),
            _env_path("%ProgramFiles%", "ACBR", "ACBR.exe"),
            _env_path("%ProgramFiles%", "ACBR Comic Book Reader", "ACBR.exe"),
        ),
        commands=("acbr", "ACBR"),
        # The portable build keeps the version in the folder name.
        windows_globs=(
            _env_path("%ProgramFiles%", "ACBR*", "ACBR Comic Book Reader.exe"),
            _env_path("%LOCALAPPDATA%", "Programs", "ACBR*",
                      "ACBR Comic Book Reader.exe"),
            _env_path("%ProgramFiles%", "ACBR*", "ACBR*.exe"),
            _env_path("%USERPROFILE%", "Desktop", "ACBR*", "ACBR Comic Book Reader.exe"),
            _env_path("%USERPROFILE%", "Downloads", "ACBR*",
                      "ACBR Comic Book Reader.exe"),
        ),
    ),
    ReaderDefinition(
        id="honeyview",
        name="Honeyview",
        formats=("image", "archive"),
        windows=(
            _env_path("%ProgramFiles%", "Honeyview", "Honeyview.exe"),
            _env_path("%ProgramFiles(x86)%", "Honeyview", "Honeyview.exe"),
        ),
    ),
    ReaderDefinition(
        id="comicseer",
        name="Comic Seer",
        formats=("archive", "pdf", "image"),
        windows=(
            _env_path("%ProgramFiles%", "Comic Seer", "ComicSeer.exe"),
            _env_path("%ProgramFiles(x86)%", "Comic Seer", "ComicSeer.exe"),
        ),
    ),
    ReaderDefinition(
        id="calibre",
        name="Calibre Viewer",
        formats=("pdf", "archive"),
        windows=(
            _env_path("%ProgramFiles%", "Calibre2", "ebook-viewer.exe"),
            _env_path("%ProgramFiles(x86)%", "Calibre2", "ebook-viewer.exe"),
        ),
        commands=("ebook-viewer",),
        mac_apps=("/Applications/calibre.app",),
        mac_commands=("ebook-viewer",),
    ),
    ReaderDefinition(
        id="qcomicbook",
        name="qComicBook",
        formats=("archive", "pdf", "image"),
        commands=("qcomicbook",),
    ),
    ReaderDefinition(
        id="okular",
        name="Okular",
        formats=("pdf", "archive", "image"),
        commands=("okular",),
    ),
    ReaderDefinition(
        id="evince",
        name="Evince",
        formats=("pdf",),
        commands=("evince",),
    ),
    ReaderDefinition(
        id="gwenview",
        name="Gwenview",
        formats=("image", "archive"),
        commands=("gwenview",),
    ),
    ReaderDefinition(
        id="eog",
        name="Eye of GNOME",
        formats=("image",),
        commands=("eog",),
    ),
    ReaderDefinition(
        id="nomacs",
        name="nomacs",
        formats=("image",),
        commands=("nomacs",),
    ),
    ReaderDefinition(
        id="feh",
        name="feh",
        formats=("image",),
        commands=("feh",),
    ),
    ReaderDefinition(
        id="simplecomic",
        name="Simple Comic",
        formats=("archive", "pdf", "image"),
        mac_apps=("/Applications/Simple Comic.app",),
    ),
    ReaderDefinition(
        id="macpreview",
        name="Preview",
        formats=("pdf", "image"),
        mac_apps=("/System/Applications/Preview.app",),
        arguments=("{file}",),
    ),
)


class ReaderManager:
    """Discovers readers and launches files with them."""

    def __init__(self, settings_obj=None):
        self._settings = settings_obj
        self._readers: List[ReaderInfo] = []
        self._loaded = False

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------
    @property
    def settings(self):
        if self._settings is None:
            from utils.settings import settings

            self._settings = settings
        return self._settings

    def _custom_readers(self) -> List[ReaderInfo]:
        readers = []
        for item in self.settings.get_custom_readers():
            try:
                reader = ReaderInfo.from_dict(item)
            except Exception as exc:  # corrupted settings must not crash
                logger.warning(f"Ignoring invalid custom reader entry: {exc}")
                continue
            if reader.id:
                readers.append(reader)
        return readers

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def refresh(self) -> List[ReaderInfo]:
        """(Re)detect installed readers."""
        detected: List[ReaderInfo] = [self._system_reader()]
        seen_ids = {SYSTEM_READER_ID}
        seen_paths = set()

        for definition in CATALOG:
            reader = self._resolve_definition(definition)
            if reader is None:
                continue
            key = reader.executable.lower()
            if key in seen_paths:
                continue
            seen_paths.add(key)
            seen_ids.add(reader.id)
            detected.append(reader)

        # Readers found through Windows "Open with" registrations.
        for path in self._windows_registered_executables():
            if path.lower() in seen_paths:
                continue
            name = Path(path).stem
            reader_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "detected"
            if reader_id in seen_ids:
                reader_id = f"{reader_id}-{len(detected)}"
            seen_ids.add(reader_id)
            seen_paths.add(path.lower())
            detected.append(
                ReaderInfo(
                    id=reader_id,
                    name=name,
                    executable=path,
                    source="detected",
                    available=True,
                )
            )

        custom = self._custom_readers()
        detected.extend(custom)

        self._readers = detected
        self._loaded = True
        logger.info(
            "Reader detection: %d available (%s)",
            len([r for r in detected if r.available]),
            ", ".join(r.name for r in detected if r.available) or "none",
        )
        return detected

    def _system_reader(self) -> ReaderInfo:
        return ReaderInfo(
            id=SYSTEM_READER_ID,
            name="System default application",
            formats=("all",),
            source="system",
            available=True,
            note="Let the operating system choose the application",
        )

    @staticmethod
    def _globbed_executable(definition: ReaderDefinition) -> str:
        """Find a portable build whose file name carries the version."""
        if not definition.windows_globs:
            return ""
        for pattern in definition.windows_globs:
            try:
                matches = sorted(glob.glob(os.path.expandvars(pattern)))
            except (OSError, ValueError):
                continue
            for match in matches:
                path = Path(match)
                if path.is_file() and ReaderManager.looks_like_reader(path):
                    return str(path)
        return ""

    @staticmethod
    def _registry_install_executable(definition: ReaderDefinition) -> str:
        r"""Read the install folder of an application from the registry.

        Adobe does not install to a fixed path: every release keeps its folder
        under ``HKLM\SOFTWARE\Adobe\Acrobat Reader\<release>\InstallPath``.
        """
        if not WINDOWS or not definition.windows_install_keys:
            return ""
        try:
            import winreg
        except ImportError:
            return ""

        hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
        folders: List[str] = []
        for hive in hives:
            for key_path in definition.windows_install_keys:
                try:
                    with winreg.OpenKey(hive, key_path) as root:
                        try:
                            value, _ = winreg.QueryValueEx(root, "InstallPath")
                            if isinstance(value, str):
                                folders.append(value)
                        except OSError:
                            pass
                        index = 0
                        while True:
                            try:
                                sub_name = winreg.EnumKey(root, index)
                            except OSError:
                                break
                            index += 1
                            try:
                                with winreg.OpenKey(root, sub_name) as entry:
                                    value, _ = winreg.QueryValueEx(entry, "InstallPath")
                                    if isinstance(value, str):
                                        folders.append(value)
                            except OSError:
                                continue
                except OSError:
                    continue

        for folder in folders:
            folder = os.path.expandvars(folder.strip().strip('"'))
            for exe in definition.windows_install_exes:
                # The catalog writes Windows separators; ``Path`` only splits
                # them on Windows, so normalise before joining.
                candidate = Path(folder) / exe.replace("\\", "/")
                if candidate.is_file():
                    return str(candidate)
        return ""

    def _resolve_definition(self, definition: ReaderDefinition) -> Optional[ReaderInfo]:
        executable = ""
        app_bundle = False

        if WINDOWS:
            for candidate in definition.windows:
                if candidate and Path(candidate).is_file():
                    executable = candidate
                    break
            if not executable:
                executable = self._globbed_executable(definition)
            if not executable:
                executable = self._registry_install_executable(definition)
        elif MACOS:
            for app in definition.mac_apps:
                if Path(app).exists():
                    executable = app
                    app_bundle = True
                    break
            if not executable:
                for command in definition.mac_commands:
                    found = shutil.which(command)
                    if found:
                        executable = found
                        break
        else:
            for command in definition.commands:
                found = shutil.which(command)
                if found:
                    executable = found
                    break

        if not executable and definition.commands:
            for command in definition.commands:
                found = shutil.which(command)
                if found:
                    executable = found
                    break

        if not executable:
            return None

        return ReaderInfo(
            id=definition.id,
            name=definition.name,
            executable=executable,
            formats=definition.formats,
            source="builtin",
            arguments=definition.arguments,
            app_bundle=app_bundle,
            available=True,
        )

    # Executables that show up in "Open with" lists without being readers.
    # Windows lets a program register itself for a file type, and a stray entry
    # (mstsc.exe was reported by a user) must not be offered as a comic reader.
    NOT_A_READER = (
        "mstsc.exe", "explorer.exe", "notepad.exe", "regedit.exe",
        "rundll32.exe", "cmd.exe", "powershell.exe", "wt.exe", "conhost.exe",
        "iexplore.exe", "msedge.exe", "chrome.exe", "firefox.exe",
        "winword.exe", "excel.exe", "powerpnt.exe", "7zfm.exe", "winrar.exe",
        "notepad++.exe", "code.exe",
    )

    # Comic extensions whose "Open with" registration proves a real reader.
    COMIC_EXTENSIONS = (".cbz", ".cbr", ".cb7", ".cbt", ".cba", ".pdf")

    @classmethod
    def looks_like_reader(cls, path) -> bool:
        """False for the system tools that end up in an "Open with" list.

        Windows stores every program that ever claimed a file type there, so
        Remote Desktop, Explorer or a text editor must not be offered as a
        comic reader.
        """
        # Backslashes are kept: a Windows path is checked on every platform in
        # the tests, and Path() on Linux would not split it.
        name = str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
        return name not in cls.NOT_A_READER

    # Executables that identify a comic/book reader, used by the registry scan.
    KNOWN_EXECUTABLES = (
        "CDisplayEx.exe",
        "YACReader.exe",
        "ComicRack.exe",
        "MComix.exe",
        "SumatraPDF.exe",
        "Honeyview.exe",
        "ComicSeer.exe",
        "ebook-viewer.exe",
        "CDisplay.exe",
        # Acrobat Reader / Acrobat, written by their installers under App Paths.
        "AcroRd32.exe",
        "Acrobat.exe",
        # ACBR (Electron build). Older versions shipped as ACBR.exe.
        "ACBR Comic Book Reader.exe",
        "ACBR.exe",
    )

    def _windows_registered_executables(self) -> List[str]:
        """Find reader executables installed anywhere on Windows.

        Three sources are combined because comic readers are frequently
        installed outside ``Program Files`` (portable builds, custom folders):

        1. ``App Paths`` keys - written by the installer, independent of location.
        2. ``Uninstall`` keys - ``DisplayIcon``/``InstallLocation`` of each app.
        3. ``Open with`` handlers registered for comic extensions.
        """
        if not WINDOWS:
            return []
        try:
            import winreg
        except ImportError:
            return []

        found: List[str] = []
        seen = set()

        def add(candidate: Optional[str]) -> None:
            if not candidate:
                return
            candidate = candidate.strip().strip('"')
            candidate = candidate.split(",")[0].strip()  # DisplayIcon "path,0"
            candidate = os.path.expandvars(candidate)
            if not candidate.lower().endswith(".exe"):
                return
            path = Path(candidate)
            if not path.is_file():
                return
            if not self.looks_like_reader(path):
                return
            key = str(path).lower()
            if key in seen:
                return
            seen.add(key)
            found.append(str(path))

        # 1) App Paths
        app_path_roots = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        )
        for hive, root in app_path_roots:
            for exe_name in self.KNOWN_EXECUTABLES:
                try:
                    with winreg.OpenKey(hive, f"{root}\\{exe_name}") as key:
                        value, _ = winreg.QueryValueEx(key, "")
                        add(value)
                except OSError:
                    continue

        # 2) Uninstall entries
        uninstall_roots = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        for hive, root in uninstall_roots:
            try:
                with winreg.OpenKey(hive, root) as base:
                    index = 0
                    while True:
                        try:
                            sub_name = winreg.EnumKey(base, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(base, sub_name) as entry:
                                display_name = ""
                                try:
                                    display_name, _ = winreg.QueryValueEx(entry, "DisplayName")
                                except OSError:
                                    pass
                                if display_name and not any(
                                    token in display_name.lower()
                                    for token in ("comic", "cdisplay", "mcomix", "yacreader",
                                                  "sumatra", "honeyview", "calibre",
                                                  "acrobat", "acbr", "pdf")
                                ):
                                    continue
                                for value_name in ("DisplayIcon", "InstallLocation"):
                                    try:
                                        value, _ = winreg.QueryValueEx(entry, value_name)
                                    except OSError:
                                        continue
                                    if value_name == "InstallLocation" and value:
                                        for exe_name in self.KNOWN_EXECUTABLES:
                                            add(str(Path(value) / exe_name))
                                    else:
                                        add(value)
                        except OSError:
                            continue
            except OSError:
                continue

        # 3) "Open with" handlers for comic extensions
        for extension in self.COMIC_EXTENSIONS:
            for hive in (winreg.HKEY_CLASSES_ROOT, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, f"{extension}\\OpenWithList") as key:
                        index = 0
                        while True:
                            try:
                                _, value, _ = winreg.EnumValue(key, index)
                            except OSError:
                                break
                            index += 1
                            if isinstance(value, str) and value.lower().endswith(".exe"):
                                add(self._registered_application_path(value))
                except OSError:
                    continue

        if found:
            logger.info("Windows registry found readers: %s", ", ".join(found))
        return found

    @staticmethod
    def _registered_application_path(exe_name: str) -> Optional[str]:
        try:
            import winreg
        except ImportError:
            return None

        for hive in (winreg.HKEY_CLASSES_ROOT, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(
                    hive, f"Applications\\{exe_name}\\shell\\open\\command"
                ) as key:
                    command, _ = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            match = re.match(r'^"?([^"]+?\.exe)"?', command.strip(), re.IGNORECASE)
            if match:
                path = os.path.expandvars(match.group(1))
                if Path(path).is_file():
                    return path
        return None

    def find_executable(self, exe_name: str) -> Optional[str]:
        """Locate an executable by name using PATH and the registry."""
        found = shutil.which(exe_name)
        if found:
            return found
        if WINDOWS:
            for path in self._windows_registered_executables():
                if Path(path).name.lower() == exe_name.lower():
                    return path
        return None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @property
    def readers(self) -> List[ReaderInfo]:
        if not self._loaded:
            self.refresh()
        return self._readers

    def available_readers(self, format_group: Optional[str] = None) -> List[ReaderInfo]:
        readers = [reader for reader in self.readers if reader.available]
        if format_group:
            readers = [reader for reader in readers if reader.supports(format_group)]
        return readers

    def get(self, reader_id: Optional[str]) -> Optional[ReaderInfo]:
        if not reader_id:
            return None
        for reader in self.readers:
            if reader.id == reader_id:
                return reader
        return None

    def get_reader_for_file(self, filepath: str) -> Optional[ReaderInfo]:
        """Resolve the configured reader for a file (None means system default)."""
        from config import format_group_for

        group = format_group_for(filepath)
        reader_id = self.settings.get_reader_for_format(group)
        if not reader_id or reader_id == SYSTEM_READER_ID:
            return None
        reader = self.get(reader_id)
        if reader and reader.available and reader.supports(group):
            return reader
        if reader and reader.available:
            return reader
        logger.warning(f"Configured reader '{reader_id}' is not available, falling back")
        return None

    # ------------------------------------------------------------------
    # Launching
    # ------------------------------------------------------------------
    def open_with(self, reader_id: str, filepath: str) -> Tuple[bool, str]:
        """Open *filepath* with a specific reader id. Returns (ok, message)."""
        if not Path(filepath).exists():
            return False, f"File not found: {filepath}"

        if reader_id == SYSTEM_READER_ID:
            return self.open_system_default(filepath)

        reader = self.get(reader_id)
        if reader is None:
            return False, "Reader not found"
        if not reader.available:
            return False, f"{reader.name} is not installed or its path is invalid"
        return self._launch(reader, filepath)

    def open_file(self, filepath: str) -> Tuple[bool, str]:
        """Open a file using the configured reader, or the system default."""
        reader = self.get_reader_for_file(filepath)
        if reader is None:
            return self.open_system_default(filepath)
        return self._launch(reader, filepath)

    def _launch(self, reader: ReaderInfo, filepath: str) -> Tuple[bool, str]:
        try:
            if reader.app_bundle:
                command = ["open", "-a", reader.executable, str(filepath)]
            elif reader.source == "system":
                return self.open_system_default(filepath)
            else:
                command = [reader.executable]
                command.extend(self._format_arguments(reader, filepath))
                if not any("{file}" in arg for arg in reader.arguments):
                    command.append(str(filepath))
                # No shell: avoids command injection and quoting bugs.
                if WINDOWS:
                    subprocess.Popen(command, close_fds=True)
                else:
                    subprocess.Popen(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                        close_fds=True,
                    )
                logger.info(f"Opened {filepath} with {reader.name}")
                return True, f"Opened with {reader.name}"
        except FileNotFoundError:
            logger.error(f"Reader is gone: {reader.executable}")
            return False, f"{reader.name} was not found at {reader.executable}"
        except OSError as exc:
            # 13 = permission denied, 115 = still copying, 267 = bad directory.
            if getattr(exc, "winerror", None) == 193:
                logger.error(f"Not an executable: {reader.executable}")
                return False, f"{reader.name} cannot be started (not an .exe)"
            if getattr(exc, "winerror", None) == 1223:
                return False, "The launch was cancelled"
            logger.error(f"Failed to open {filepath} with {reader.name}: {exc}")
            return False, str(exc)
        except Exception as exc:
            logger.error(f"Failed to open {filepath} with {reader.name}: {exc}")
            return False, str(exc)

    @staticmethod
    def _format_arguments(reader: ReaderInfo, filepath: str) -> List[str]:
        return [arg.replace("{file}", str(filepath)) for arg in reader.arguments]

    def open_system_default(self, filepath: str) -> Tuple[bool, str]:
        """Open a file with the operating system's default application."""
        if not Path(filepath).exists():
            return False, f"File not found: {filepath}"
        try:
            if WINDOWS:
                os.startfile(filepath)  # type: ignore[attr-defined]
            elif MACOS:
                subprocess.Popen(
                    ["open", str(filepath)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            else:
                opener = shutil.which("xdg-open")
                if not opener:
                    return False, "xdg-open was not found on this system"
                subprocess.Popen(
                    [opener, str(filepath)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            logger.info(f"Opened {filepath} with the system default application")
            return True, "Opened with the system default application"
        except Exception as exc:
            logger.error(f"System default open failed for {filepath}: {exc}")
            return False, str(exc)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def add_custom_reader(
        self,
        name: str,
        path: str,
        formats: Sequence[str] = FORMAT_GROUPS,
        arguments: Sequence[str] = (),
    ) -> Optional[ReaderInfo]:
        """Register an external application as a custom reader."""
        path = str(Path(path).expanduser())
        if not Path(path).exists():
            logger.warning(f"Custom reader path does not exist: {path}")
            return None

        base_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "custom"
        existing = {reader.id for reader in self._custom_readers()}
        reader_id = f"custom-{base_id}"
        counter = 2
        while reader_id in existing:
            reader_id = f"custom-{base_id}-{counter}"
            counter += 1

        app_bundle = MACOS and path.endswith(".app")
        data = {
            "id": reader_id,
            "name": name.strip() or Path(path).stem,
            "path": path,
            "formats": list(formats) or list(FORMAT_GROUPS),
            "arguments": list(arguments),
            "app_bundle": app_bundle,
        }
        self.settings.add_custom_reader(data)
        self._loaded = False
        logger.info(f"Added custom reader '{data['name']}' ({path})")
        return ReaderInfo.from_dict(data)

    def remove_custom_reader(self, reader_id: str) -> bool:
        """Remove a custom reader and clean up references to it."""
        removed = self.settings.remove_custom_reader(reader_id)
        if removed:
            self._loaded = False
        return removed


# Module-level shared instance (settings are loaded lazily).
reader_manager = ReaderManager()
