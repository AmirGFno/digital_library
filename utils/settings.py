"""
settings.py - persistent user settings.

Stored as JSON in ``data/settings.json`` next to the application. Writes are
atomic so a crash can never leave a truncated settings file behind.

The reader configuration is intentionally backward compatible with older
versions of the app (the previous single ``path``/``use_system_default`` format
is migrated automatically to a custom reader entry).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR
from utils.logger import logger

SYSTEM_READER_ID = "system"


class Settings:
    """Application settings with atomic persistence."""

    def __init__(self, settings_path: Optional[Path] = None):
        self.settings_file = Path(settings_path) if settings_path else DATA_DIR / "settings.json"
        self.default_settings: Dict[str, Any] = {
            "reader": {
                "default": SYSTEM_READER_ID,
                "per_format": {"archive": "", "pdf": "", "image": ""},
                "custom": [],
            },
            "view": {
                "columns": 4,
                "theme": "dark",
                "sort": "series",
                "filter": "all",
                "format": "all",
                "favorites_only": False,
                "mark_read_on_open": True,
                "window_geometry": "",
                "splitter_state": "",
            },
            "library": {
                "last_import_folder": "",
            },
            "app": {
                "version": "2.1.0",
            },
        }
        self.settings = self._load_settings()

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------
    def _load_settings(self) -> Dict[str, Any]:
        if not self.settings_file.exists():
            return self._copy_defaults(self.default_settings)
        try:
            with open(self.settings_file, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise ValueError("settings root must be an object")
            merged = self._merge_settings(self.default_settings, loaded)
            return self._migrate_reader_settings(merged)
        except Exception as exc:
            logger.error(f"Failed to load settings ({exc}); using defaults")
            return self._copy_defaults(self.default_settings)

    @staticmethod
    def _copy_defaults(value):
        return json.loads(json.dumps(value))

    def _merge_settings(self, default: Dict, loaded: Dict) -> Dict:
        result = self._copy_defaults(default)
        for key, value in loaded.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_settings(result[key], value)
            else:
                result[key] = value
        return result

    def _migrate_reader_settings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Upgrade the legacy single-custom-reader settings format."""
        reader = data.get("reader", {})
        legacy_path = reader.pop("path", "")
        legacy_name = reader.pop("name", "")
        legacy_system = reader.pop("use_system_default", None)
        reader.pop("enabled", None)

        custom = reader.get("custom")
        if not isinstance(custom, list):
            custom = []
            reader["custom"] = custom

        if legacy_path and isinstance(legacy_path, str) and Path(legacy_path).exists():
            if not any(item.get("path") == legacy_path for item in custom):
                custom.append(
                    {
                        "id": "custom-migrated",
                        "name": legacy_name or Path(legacy_path).stem,
                        "path": legacy_path,
                        "formats": ["archive", "pdf", "image"],
                        "arguments": [],
                        "app_bundle": legacy_path.endswith(".app"),
                    }
                )
                if legacy_system is False:
                    reader["default"] = "custom-migrated"
        if not reader.get("default"):
            reader["default"] = SYSTEM_READER_ID
        reader.setdefault("per_format", {"archive": "", "pdf": "", "image": ""})
        return data

    def save(self) -> bool:
        """Atomically persist settings; returns True on success."""
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(
                prefix="settings-", suffix=".tmp", dir=str(self.settings_file.parent)
            )
            with os.fdopen(handle, "w", encoding="utf-8") as temp_file:
                json.dump(self.settings, temp_file, indent=4, ensure_ascii=False)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, self.settings_file)
            return True
        except Exception as exc:
            logger.error(f"Error saving settings: {exc}")
            return False

    # ------------------------------------------------------------------
    # Reader settings
    # ------------------------------------------------------------------
    def get_reader_settings(self) -> Dict:
        return self.settings.get("reader", {})

    def set_reader_settings(
        self,
        enabled: bool,
        path: str = "",
        name: str = "",
        use_system_default: bool = False,
    ):
        """Legacy API kept for backwards compatibility."""
        if use_system_default or not enabled:
            self.set_default_reader(SYSTEM_READER_ID)
            return
        custom = self.settings.setdefault("reader", {}).setdefault("custom", [])
        reader_id = "custom-migrated"
        for item in custom:
            if item.get("id") == reader_id:
                item.update({"name": name or Path(path).stem, "path": path})
                break
        else:
            custom.append(
                {
                    "id": reader_id,
                    "name": name or Path(path).stem,
                    "path": path,
                    "formats": ["archive", "pdf", "image"],
                    "arguments": [],
                    "app_bundle": path.endswith(".app"),
                }
            )
        self.set_default_reader(reader_id)

    def get_default_reader_id(self) -> str:
        reader = self.settings.setdefault("reader", {})
        value = reader.get("default") or SYSTEM_READER_ID
        return str(value)

    def set_default_reader(self, reader_id: str):
        self.settings.setdefault("reader", {})["default"] = reader_id or SYSTEM_READER_ID
        self.save()

    def get_reader_for_format(self, format_group: str) -> str:
        """Reader id configured for a format group (empty = use global default)."""
        reader = self.settings.get("reader", {})
        per_format = reader.get("per_format") or {}
        value = per_format.get(format_group) or ""
        return str(value) or self.get_default_reader_id()

    def set_reader_for_format(self, format_group: str, reader_id: str):
        per_format = self.settings.setdefault("reader", {}).setdefault("per_format", {})
        per_format[format_group] = reader_id or ""
        self.save()

    def get_custom_readers(self) -> List[Dict]:
        custom = self.settings.get("reader", {}).get("custom", [])
        return custom if isinstance(custom, list) else []

    def add_custom_reader(self, reader: Dict) -> bool:
        custom = self.settings.setdefault("reader", {}).setdefault("custom", [])
        custom = [item for item in custom if item.get("id") != reader.get("id")]
        custom.append(reader)
        self.settings["reader"]["custom"] = custom
        return self.save()

    def remove_custom_reader(self, reader_id: str) -> bool:
        reader = self.settings.setdefault("reader", {})
        custom = [item for item in reader.get("custom", []) if item.get("id") != reader_id]
        reader["custom"] = custom
        if reader.get("default") == reader_id:
            reader["default"] = SYSTEM_READER_ID
        per_format = reader.setdefault("per_format", {})
        for group, value in list(per_format.items()):
            if value == reader_id:
                per_format[group] = ""
        return self.save()

    def get_reader_path(self) -> Optional[str]:
        """Legacy helper: path of the configured custom reader, if any."""
        reader_id = self.get_default_reader_id()
        for item in self.get_custom_readers():
            if item.get("id") == reader_id:
                path = item.get("path", "")
                return path if path and Path(path).exists() else None
        return None

    def is_custom_reader_enabled(self) -> bool:
        return self.get_default_reader_id() != SYSTEM_READER_ID

    def use_system_default(self) -> bool:
        return self.get_default_reader_id() == SYSTEM_READER_ID

    # ------------------------------------------------------------------
    # View / window state
    # ------------------------------------------------------------------
    def get_columns(self) -> int:
        try:
            return int(self.settings.get("view", {}).get("columns", 4))
        except (TypeError, ValueError):
            return 4

    def set_columns(self, columns: int):
        self.settings.setdefault("view", {})["columns"] = int(columns)
        self.save()

    def get_view(self, key: str, default: Any = None) -> Any:
        return self.settings.get("view", {}).get(key, default)

    def set_view(self, key: str, value: Any, save: bool = True):
        self.settings.setdefault("view", {})[key] = value
        if save:
            self.save()

    def set_many_view(self, values: Dict[str, Any]):
        view = self.settings.setdefault("view", {})
        view.update(values)
        self.save()

    def get_last_import_folder(self) -> str:
        return str(self.settings.get("library", {}).get("last_import_folder", ""))

    def set_last_import_folder(self, folder: str):
        self.settings.setdefault("library", {})["last_import_folder"] = folder
        self.save()


# Global instance
settings = Settings()
