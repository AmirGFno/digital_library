"""
Helper utilities for the application.
"""
import sys
import subprocess
import re
import shutil
from pathlib import Path
from typing import Optional, List

# Import logger
try:
    from .logger import logger
except ImportError:
    from utils.logger import logger


def open_file_with_default_app(filepath: str) -> bool:
    """Open a file with the configured reader (or the system default)."""
    try:
        from utils.reader_manager import reader_manager

        ok, _message = reader_manager.open_file(filepath)
        return ok
    except Exception as e:
        logger.error(f"Failed to open file {filepath}: {e}")
        return False


def open_file_with_reader(reader_id: str, filepath: str):
    """Open a file with a specific reader id. Returns (ok, message)."""
    from utils.reader_manager import reader_manager

    return reader_manager.open_with(reader_id, filepath)


def open_containing_folder(filepath: str) -> bool:
    """Reveal a file in the system file manager."""
    path = Path(filepath)
    folder = path.parent
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                return False
            subprocess.Popen([opener, str(folder)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        logger.error(f"Failed to open containing folder for {filepath}: {e}")
        return False


def human_size(size_bytes) -> str:
    """Format a byte count, returning '-' for unknown values."""
    try:
        return format_file_size(int(size_bytes))
    except (TypeError, ValueError):
        return "-"


def get_file_extension(filepath: str) -> str:
    """Get the lowercase file extension (``.tar.gz`` stays intact)."""
    lower = str(filepath).lower()
    if lower.endswith(".tar.gz"):
        return ".tar.gz"
    return Path(filepath).suffix.lower()


def get_filename_without_extension(filepath: str) -> str:
    """Get the filename without extension."""
    return Path(filepath).stem


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe file system usage."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename.strip()


def extract_numbers(text: str) -> List[int]:
    """Extract all numbers from text."""
    return [int(num) for num in re.findall(r'\d+', text)]


def extract_first_number(text: str) -> Optional[int]:
    """Extract the first number from text."""
    numbers = re.findall(r'\d+', text)
    return int(numbers[0]) if numbers else None


def natural_sort_key(s: str) -> List:
    """
    Key function for natural sorting.
    Example: "Vol. 10" -> ["vol. ", 10]
    """
    def convert(text):
        return int(text) if text.isdigit() else text.lower()
    
    def alphanum_key(key):
        return [convert(c) for c in re.split('([0-9]+)', key)]
    
    return alphanum_key(s)


def copy_image_to_custom_covers(source_path: str, book_id: int) -> Optional[str]:
    """Copy an image to custom covers directory with proper naming."""
    try:
        from config import CUSTOM_COVERS_DIR
        
        # Create directory if it doesn't exist
        CUSTOM_COVERS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Create filename
        ext = Path(source_path).suffix.lower()
        new_filename = f"book_{book_id}_cover{ext}"
        new_path = CUSTOM_COVERS_DIR / new_filename
        
        # Copy file
        shutil.copy2(source_path, new_path)
        
        return str(new_path)
    except Exception as e:
        logger.error(f"Failed to copy image to custom covers: {e}")
        return None


def natural_sort_key_for_books(book: dict) -> tuple:
    """
    Key function for natural sorting of books.
    Returns: (series_name, volume_num, volume_text, title)
    """
    # Handle all values safely
    series = book.get('series_name')
    if series is None:
        series = ''
    
    volume_num = book.get('volume_num')
    if volume_num is None:
        # Try to extract from volume text
        volume = book.get('volume')
        if volume:
            numbers = re.findall(r'\d+', str(volume))
            volume_num = int(numbers[0]) if numbers else 999999
        else:
            volume_num = 999999
    
    volume_text = book.get('volume')
    if volume_text is None:
        volume_text = ''
    
    title = book.get('title') or book.get('filepath')
    if title is None:
        title = ''
    
    return (series, volume_num, volume_text, title.lower())


def sort_books_naturally(books: list) -> list:
    """Sort books using natural sorting with safe handling of None values."""
    try:
        return sorted(books, key=natural_sort_key_for_books)
    except Exception as e:
        # Fallback to simple sorting if natural sort fails
        logger.warning(f"Natural sort failed: {e}, using fallback sorting")
        
        def fallback_key(book):
            # Convert all values to strings for safe comparison
            series = book.get('series_name', '')
            if series is None:
                series = ''
            
            volume_num = book.get('volume_num', 999999)
            if volume_num is None:
                volume_num = 999999
            
            volume = book.get('volume', '')
            if volume is None:
                volume = ''
            
            title = book.get('title', '') or book.get('filepath', '')
            if title is None:
                title = ''
            
            return (series, volume_num, volume, title.lower())
        
        return sorted(books, key=fallback_key)


def extract_volume_number_from_text(text: str) -> Optional[int]:
    """Extract the first number from text."""
    if not text:
        return None
    numbers = re.findall(r'\d+', str(text))
    return int(numbers[0]) if numbers else None