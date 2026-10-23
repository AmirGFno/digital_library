"""
Configuration settings for the Digital Library application.
"""
import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
THUMBNAILS_DIR = BASE_DIR / "thumbnails"
ASSETS_DIR = BASE_DIR / "assets"
LOGS_DIR = BASE_DIR / "logs"
CUSTOM_COVERS_DIR = BASE_DIR / "custom_covers"

# Database
DATABASE_PATH = DATA_DIR / "library.db"

# Thumbnail settings
THUMBNAIL_SIZE = (200, 280)
THUMBNAIL_FORMAT = "JPEG"
THUMBNAIL_QUALITY = 85

# UI settings
DEFAULT_COLUMNS = 4
CARD_WIDTH = 180
CARD_HEIGHT = 280
COVER_HEIGHT = 220

# Supported file extensions
SUPPORTED_EXTENSIONS = {
    'pdf': ['.pdf'],
    'images': ['.jpg', '.jpeg', '.png', '.gif', '.webp'],
    'archives': ['.cbz', '.cbr', '.zip', '.rar', '.7z', '.tar', '.tar.gz', '.tgz']
}

ALL_EXTENSIONS = []
for exts in SUPPORTED_EXTENSIONS.values():
    ALL_EXTENSIONS.extend(exts)

# Create directories if they don't exist
for directory in [DATA_DIR, THUMBNAILS_DIR, ASSETS_DIR, LOGS_DIR, CUSTOM_COVERS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)