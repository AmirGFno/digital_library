"""
settings.py - مدیریت تنظیمات کاربر
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

from config import BASE_DIR, DATA_DIR


class Settings:
    """مدیریت تنظیمات برنامه"""
    
    def __init__(self):
        self.settings_file = DATA_DIR / "settings.json"
        self.default_settings = {
            'reader': {
                'enabled': False,
                'path': r"C:\Program Files\CDisplayEx\CDisplayEx.exe",
                'name': "CDisplayEx",
                'use_system_default': False
            },
            'view': {
                'columns': 4,
                'theme': 'dark'
            }
        }
        self.settings = self._load_settings()
    
    def _load_settings(self) -> Dict[str, Any]:
        """بارگذاری تنظیمات از فایل"""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # Merge with default settings
                    return self._merge_settings(self.default_settings, loaded)
            except Exception as e:
                print(f"Error loading settings: {e}")
                return self.default_settings.copy()
        return self.default_settings.copy()
    
    def _merge_settings(self, default: Dict, loaded: Dict) -> Dict:
        """ادغام تنظیمات پیش‌فرض و بارگذاری شده"""
        result = default.copy()
        
        for key, value in loaded.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_settings(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def save(self) -> bool:
        """ذخیره تنظیمات در فایل"""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving settings: {e}")
            return False
    
    # Reader settings
    def get_reader_settings(self) -> Dict:
        """دریافت تنظیمات خواننده"""
        return self.settings.get('reader', {})
    
    def set_reader_settings(self, enabled: bool, path: str = "", name: str = "", 
                           use_system_default: bool = False):
        """تنظیم برنامه خواننده"""
        self.settings['reader'] = {
            'enabled': enabled,
            'path': path,
            'name': name,
            'use_system_default': use_system_default
        }
        self.save()
    
    def get_reader_path(self) -> Optional[str]:
        """دریافت مسیر reader"""
        reader = self.settings.get('reader', {})
        if reader.get('enabled', False) and not reader.get('use_system_default', False):
            path = reader.get('path', '')
            if path and os.path.exists(path):
                return path
        return None
    
    def is_custom_reader_enabled(self) -> bool:
        """آیا reader سفارشی فعال است؟"""
        reader = self.settings.get('reader', {})
        return reader.get('enabled', False) and not reader.get('use_system_default', False)
    
    def use_system_default(self) -> bool:
        """آیا از برنامه پیش‌فرض سیستم استفاده شود؟"""
        reader = self.settings.get('reader', {})
        return reader.get('use_system_default', False)
    
    # View settings
    def get_columns(self) -> int:
        """دریافت تعداد ستون‌ها"""
        return self.settings.get('view', {}).get('columns', 4)
    
    def set_columns(self, columns: int):
        """تنظیم تعداد ستون‌ها"""
        if 'view' not in self.settings:
            self.settings['view'] = {}
        self.settings['view']['columns'] = columns
        self.save()


# Global instance
settings = Settings()