"""
Cover extraction module for various book formats.
Handles PDF, images, and archive files (CBZ, CBR, 7z, tar).
"""
import hashlib
import zipfile
import tarfile
import io
import os
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from config import (
    THUMBNAILS_DIR, ASSETS_DIR, THUMBNAIL_SIZE, THUMBNAIL_FORMAT, THUMBNAIL_QUALITY,
    SUPPORTED_EXTENSIONS
)
from utils.logger import logger
from utils.helpers import get_file_extension, get_filename_without_extension

import pdf_engine

# Optional imports

try:
    import rarfile
    HAS_RARFILE = True
except ImportError:
    HAS_RARFILE = False
    logger.warning("rarfile not installed. RAR/CBR support disabled.")

try:
    import py7zr
    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False
    logger.warning("py7zr not installed. 7z support disabled.")


class CoverExtractor:
    """Extracts and caches cover images from various book formats."""
    
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    
    def __init__(self, cache_dir: Path = THUMBNAILS_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_cover = self._load_default_cover()
    
    def _load_default_cover(self) -> Optional[Image.Image]:
        """Load the default cover image from assets."""
        default_path = ASSETS_DIR / "default_cover.png"
        if default_path.exists():
            try:
                return Image.open(default_path).convert('RGB')
            except Exception as e:
                logger.error(f"Failed to load default cover: {e}")
        return None
    
    def _get_cache_path(self, filepath: str) -> Path:
        """Generate a unique cache path for a file."""
        file_hash = hashlib.md5(filepath.encode()).hexdigest()
        return self.cache_dir / f"{file_hash}.jpg"
    
    def get_cover(self, filepath: str, book_id: Optional[int] = None, 
                  force_refresh: bool = False) -> Optional[str]:
        """
        Get the cover image path for a file.
        Returns the cached path or extracts and caches a new cover.
        """
        logger.debug(f"Getting cover for {filepath}")
        
        # First check for custom cover
        if book_id:
            from database import db
            custom_cover = db.get_custom_cover(book_id)
            if custom_cover and Path(custom_cover).exists():
                logger.debug(f"Using custom cover for book {book_id}: {custom_cover}")
                return custom_cover
        
        cache_path = self._get_cache_path(filepath)
        
        # Return cached version if exists and not forcing refresh
        if cache_path.exists() and not force_refresh:
            logger.debug(f"Using cached cover: {cache_path}")
            return str(cache_path)
        
        # Extract cover based on file type
        logger.debug("Extracting new cover...")
        cover_image = self._extract_cover(filepath)
        
        if cover_image:
            logger.debug("Cover extracted successfully")
            # Resize and save to cache
            try:
                cover_image = self._resize_cover(cover_image)
                cover_image.save(
                    cache_path, 
                    THUMBNAIL_FORMAT, 
                    quality=THUMBNAIL_QUALITY
                )
                logger.debug(f"Cover saved to cache: {cache_path}")
                return str(cache_path)
            except Exception as e:
                logger.error(f"Failed to save cover for {filepath}: {e}")
        
        # Generate fallback cover
        logger.debug("Generating fallback cover")
        fallback = self._generate_fallback_cover(filepath)
        if fallback:
            try:
                fallback.save(cache_path, THUMBNAIL_FORMAT, quality=THUMBNAIL_QUALITY)
                logger.debug("Fallback cover saved")
                return str(cache_path)
            except Exception as e:
                logger.error(f"Failed to save fallback cover: {e}")
        
        logger.debug(f"No cover generated for {filepath}")
        return None
    
    def _extract_cover(self, filepath: str) -> Optional[Image.Image]:
        """Extract cover image based on file type."""
        ext = get_file_extension(filepath)
        
        try:
            if ext == '.pdf':
                return self._extract_pdf_cover(filepath)
            elif ext in SUPPORTED_EXTENSIONS['images']:
                return self._extract_image_cover(filepath)
            elif ext in ['.cbz', '.zip']:
                return self._extract_zip_cover(filepath)
            elif ext in ['.cbr', '.rar']:
                return self._extract_rar_cover(filepath)
            elif ext in ('.7z', '.cb7'):
                return self._extract_7z_cover(filepath)
            elif ext in ['.tar', '.tar.gz', '.tgz']:
                return self._extract_tar_cover(filepath)
        except Exception as e:
            logger.error(f"Failed to extract cover from {filepath}: {e}")
        
        return None
    
    def _extract_pdf_cover(self, filepath: str) -> Optional[Image.Image]:
        """Extract the first page of a PDF as cover."""
        if not pdf_engine.is_available():
            return None
        return pdf_engine.render_first_page(filepath)

    def _extract_image_cover(self, filepath: str) -> Optional[Image.Image]:
        """Use the image file itself as cover."""
        try:
            return Image.open(filepath).convert('RGB')
        except Exception as e:
            logger.error(f"Image open error for {filepath}: {e}")
        return None
    
    def _extract_zip_cover(self, filepath: str) -> Optional[Image.Image]:
        """Extract the first image from a ZIP/CBZ archive."""
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                # Get all image files
                image_files = []
                for f in zf.namelist():
                    if Path(f).suffix.lower() in self.IMAGE_EXTENSIONS:
                        if not f.startswith('__MACOSX'):
                            image_files.append(f)
                
                # Sort to find cover
                image_files.sort()
                
                if image_files:
                    # Try to find cover by name
                    cover_keywords = ['cover', '01', '001', 'first', '0001', 'page001']
                    for keyword in cover_keywords:
                        for img_file in image_files:
                            if keyword.lower() in img_file.lower():
                                with zf.open(img_file) as img_file_obj:
                                    return Image.open(io.BytesIO(img_file_obj.read())).convert('RGB')
                    
                    # Otherwise use first image
                    with zf.open(image_files[0]) as img_file_obj:
                        return Image.open(io.BytesIO(img_file_obj.read())).convert('RGB')
        except Exception as e:
            logger.error(f"ZIP extraction error for {filepath}: {e}")
        
        return None
    
    def _extract_rar_cover(self, filepath: str) -> Optional[Image.Image]:
        """Extract the first image from a RAR/CBR archive."""
        if not HAS_RARFILE:
            logger.warning("rarfile not available for RAR extraction")
            return None
        
        try:
            # Configure UnRAR.exe path for Windows
            if os.name == 'nt':
                unrar_paths = [
                    r"C:\Program Files\WinRAR\UnRAR.exe",
                    r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
                    r"C:\Windows\UnRAR.exe",
                ]
                
                for path in unrar_paths:
                    if os.path.exists(path):
                        rarfile.UNRAR_TOOL = path
                        logger.debug(f"Using UnRAR tool: {path}")
                        break
                else:
                    logger.warning("UnRAR.exe not found. RAR extraction may fail.")
            
            with rarfile.RarFile(filepath, 'r') as rf:
                # Get all image files
                image_files = []
                for f in rf.infolist():
                    if not f.isdir():
                        ext = Path(f.filename).suffix.lower()
                        if ext in self.IMAGE_EXTENSIONS:
                            image_files.append(f.filename)
                
                # Sort to find cover
                image_files.sort()
                
                if image_files:
                    # Try to find cover by name
                    cover_keywords = ['cover', '01', '001', 'first', '0001', 'page001']
                    for keyword in cover_keywords:
                        for img_file in image_files:
                            if keyword.lower() in img_file.lower():
                                with rf.open(img_file) as img_file_obj:
                                    return Image.open(io.BytesIO(img_file_obj.read())).convert('RGB')
                    
                    # Otherwise use first image
                    with rf.open(image_files[0]) as img_file_obj:
                        return Image.open(io.BytesIO(img_file_obj.read())).convert('RGB')
        
        except rarfile.NeedFirstVolume:
            logger.error(f"Multi-volume RAR not supported: {filepath}")
        except rarfile.PasswordRequired:
            logger.error(f"Password protected RAR: {filepath}")
        except Exception as e:
            logger.error(f"RAR extraction error for {filepath}: {e}")
        
        return None
    
    def _extract_7z_cover(self, filepath: str) -> Optional[Image.Image]:
        """Extract the first image from a 7z archive."""
        if not HAS_PY7ZR:
            return None
        
        try:
            with py7zr.SevenZipFile(filepath, 'r') as sz:
                all_files = sz.getnames()
                image_files = sorted([
                    f for f in all_files
                    if Path(f).suffix.lower() in self.IMAGE_EXTENSIONS
                ])
                
                if image_files:
                    # Try to find cover by name
                    cover_keywords = ['cover', '01', '001', 'first', '0001', 'page001']
                    for keyword in cover_keywords:
                        for img_file in image_files:
                            if keyword.lower() in img_file.lower():
                                sz.extract(targets=[img_file])
                                extracted = sz.read([img_file])
                                for name, data in extracted.items():
                                    return Image.open(io.BytesIO(data.read())).convert('RGB')
                    
                    # Otherwise use first image
                    sz.extract(targets=[image_files[0]])
                    extracted = sz.read([image_files[0]])
                    for name, data in extracted.items():
                        return Image.open(io.BytesIO(data.read())).convert('RGB')
        except Exception as e:
            logger.error(f"7z extraction error for {filepath}: {e}")
        
        return None
    
    def _extract_tar_cover(self, filepath: str) -> Optional[Image.Image]:
        """Extract the first image from a tar archive."""
        try:
            with tarfile.open(filepath, 'r:*') as tf:
                image_files = sorted([
                    m for m in tf.getmembers()
                    if m.isfile() and Path(m.name).suffix.lower() in self.IMAGE_EXTENSIONS
                ], key=lambda x: x.name)
                
                if image_files:
                    # Try to find cover by name
                    cover_keywords = ['cover', '01', '001', 'first', '0001', 'page001']
                    for keyword in cover_keywords:
                        for img_file in image_files:
                            if keyword.lower() in img_file.name.lower():
                                f = tf.extractfile(img_file)
                                if f:
                                    return Image.open(io.BytesIO(f.read())).convert('RGB')
                    
                    # Otherwise use first image
                    f = tf.extractfile(image_files[0])
                    if f:
                        return Image.open(io.BytesIO(f.read())).convert('RGB')
        except Exception as e:
            logger.error(f"TAR extraction error for {filepath}: {e}")
        
        return None
    
    def _resize_cover(self, image: Image.Image) -> Image.Image:
        """Resize image to thumbnail size maintaining aspect ratio."""
        image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        
        # Create a new image with exact thumbnail size and paste
        thumb = Image.new('RGB', THUMBNAIL_SIZE, (40, 40, 40))
        
        # Center the image
        x = (THUMBNAIL_SIZE[0] - image.width) // 2
        y = (THUMBNAIL_SIZE[1] - image.height) // 2
        thumb.paste(image, (x, y))
        
        return thumb
    
    def _generate_fallback_cover(self, filepath: str) -> Image.Image:
        """Generate a fallback cover with filename text."""
        img = Image.new('RGB', THUMBNAIL_SIZE, (60, 60, 70))
        draw = ImageDraw.Draw(img)
        
        filename = get_filename_without_extension(filepath)
        
        # Try to use a basic font
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except:
            font = ImageFont.load_default()
        
        # Word wrap the filename
        max_width = THUMBNAIL_SIZE[0] - 20
        words = filename.replace('_', ' ').replace('-', ' ').split()
        lines = []
        current_line = ""
        
        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        
        # Draw text centered
        y = THUMBNAIL_SIZE[1] // 2 - (len(lines) * 18) // 2
        for line in lines[:8]:  # Max 8 lines
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (THUMBNAIL_SIZE[0] - text_width) // 2
            draw.text((x, y), line, fill=(200, 200, 200), font=font)
            y += 18
        
        # Draw file extension at bottom
        ext = get_file_extension(filepath).upper()
        bbox = draw.textbbox((0, 0), ext, font=font)
        ext_width = bbox[2] - bbox[0]
        draw.text(
            ((THUMBNAIL_SIZE[0] - ext_width) // 2, THUMBNAIL_SIZE[1] - 30),
            ext, fill=(150, 150, 150), font=font
        )
        
        return img
    
    def clear_cache(self, filepath: Optional[str] = None):
        """Clear cached covers. If filepath provided, clear only that file's cache."""
        if filepath:
            cache_path = self._get_cache_path(filepath)
            if cache_path.exists():
                cache_path.unlink()
                logger.info(f"Cleared cache for: {filepath}")
        else:
            for cache_file in self.cache_dir.glob("*.jpg"):
                cache_file.unlink()
            logger.info("Cleared all cover cache")


# Global instance
cover_extractor = CoverExtractor()