"""
Utilities package for Digital Library.
"""

from .logger import logger, setup_logger
from .helpers import (
    open_file_with_default_app,
    get_file_extension,
    get_filename_without_extension,
    format_file_size,
    sanitize_filename,
    extract_first_number,
    extract_numbers,
    natural_sort_key,
    copy_image_to_custom_covers,
    natural_sort_key_for_books,
    sort_books_naturally,
    extract_volume_number_from_text
)
from .settings import settings

__all__ = [
    'logger',
    'setup_logger',
    'open_file_with_default_app',
    'get_file_extension',
    'get_filename_without_extension',
    'format_file_size',
    'sanitize_filename',
    'extract_first_number',
    'extract_numbers',
    'natural_sort_key',
    'copy_image_to_custom_covers',
    'natural_sort_key_for_books',
    'sort_books_naturally',
    'extract_volume_number_from_text',
    'settings'
]