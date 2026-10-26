"""
Cover extraction module for various book formats.
Handles PDF, images, and archive files (CBZ, CBR, 7z, tar).
"""
import hashlib
import zipfile
import tarfile
import io
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont

from config import (
    THUMBNAILS_DIR, ASSETS_DIR, THUMBNAIL_SIZE, THUMBNAIL_FORMAT, THUMBNAIL_QUALITY,
    SUPPORTED_EXTENSIONS
)
from utils.logger import logger
from utils.helpers import (
    get_file_extension,
    get_filename_without_extension,
    natural_sort_key,
)

import pdf_engine
from utils import rar_tools

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
    
    IMAGE_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff'
    }

    # Bumped whenever the way the cover page is chosen changes. It is part of
    # the cache key, so covers built by an older rule are rebuilt once.
    COVER_ALGORITHM_VERSION = 2
    
    def __init__(self, cache_dir: Path = THUMBNAILS_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Placeholders live apart from the real cache so they are regenerated as
        # soon as a missing RAR tool becomes available.
        self._fallback_dir = Path(cache_dir).parent / "fallback_covers"
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
    
    def _get_cache_path(self, filepath: str, fingerprint: str = "") -> Path:
        """Generate a unique cache path for a file.

        The size and modification time are part of the key so that a file that
        was replaced (a better scan of the same comic) gets a fresh cover instead
        of showing the old one forever.
        """
        key = f"v{self.COVER_ALGORITHM_VERSION}|{filepath}|{fingerprint}"
        file_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{file_hash}.jpg"

    @staticmethod
    def _legacy_cache_names(filepath: str, fingerprint: str) -> List[str]:
        """Cache file names this book could have before the ordering fix.

        The key used to be ``path`` and later ``path|fingerprint``; both were
        replaced by a versioned key, so those leftovers are removed once the
        new cover exists instead of sitting in the thumbnails folder forever.
        """
        keys = [filepath]
        if fingerprint:
            keys.append(f"{filepath}|{fingerprint}")
        return [f"{hashlib.md5(key.encode()).hexdigest()}.jpg" for key in keys]

    def _drop_legacy_covers(self, filepath: str, fingerprint: str, keep: Path) -> None:
        for name in self._legacy_cache_names(filepath, fingerprint):
            for directory in (self.cache_dir, self._fallback_dir):
                stale = directory / name
                if stale != keep and stale.is_file():
                    try:
                        stale.unlink()
                    except OSError:
                        logger.debug(f"Could not remove stale cover {stale}")

    @staticmethod
    def _fingerprint(filepath: str) -> str:
        try:
            stat = Path(filepath).stat()
            return f"{stat.st_size}:{int(stat.st_mtime)}"
        except OSError:
            return ""
    
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
        
        fingerprint = self._fingerprint(filepath)
        cache_path = self._get_cache_path(filepath, fingerprint)
        
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
                # The cache can be cleared (or removed by cleanup tools) while
                # the app is running; never lose a cover over a missing folder.
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cover_image.save(
                    cache_path, 
                    THUMBNAIL_FORMAT, 
                    quality=THUMBNAIL_QUALITY
                )
                logger.debug(f"Cover saved to cache: {cache_path}")
                self._drop_legacy_covers(filepath, fingerprint, cache_path)
                return str(cache_path)
            except Exception as e:
                logger.error(f"Failed to save cover for {filepath}: {e}")
        
        # Generate fallback cover. It is *deliberately not cached*: once the user
        # installs WinRAR/7-Zip the real cover must appear on the next start,
        # which never happened while placeholders were written to the cache.
        logger.debug("Generating fallback cover")
        fallback = self._generate_fallback_cover(filepath)
        if fallback:
            try:
                self._fallback_dir.mkdir(parents=True, exist_ok=True)
                fallback_path = self._fallback_dir / cache_path.name
                fallback.save(fallback_path, THUMBNAIL_FORMAT, quality=THUMBNAIL_QUALITY)
                logger.debug("Fallback cover saved")
                self._drop_legacy_covers(filepath, fingerprint, fallback_path)
                return str(fallback_path)
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
            elif ext in ['.tar', '.tar.gz', '.tgz', '.cbt']:
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
        """Extract the first page of a ZIP/CBZ archive as the cover."""
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                names = [info.filename for info in zf.infolist() if not info.is_dir()]
                for name in self._cover_candidates(names):
                    try:
                        with zf.open(name) as handle:
                            return Image.open(io.BytesIO(handle.read())).convert('RGB')
                    except Exception as exc:
                        # A damaged page must not cost the whole cover.
                        logger.debug(f"Skipping unreadable page {name}: {exc}")
                        continue
        except Exception as e:
            logger.error(f"ZIP extraction error for {filepath}: {e}")

        return None
    
    def _extract_rar_cover(self, filepath: str) -> Optional[Image.Image]:
        """Extract the first image from a RAR/CBR archive.

        Many files called ``.cbr`` are really ZIP archives, so a ZIP attempt is
        made first. For genuine RAR archives an external tool (UnRAR, 7-Zip or
        bsdtar) is required; it is looked up through :mod:`utils.rar_tools`
        instead of assuming WinRAR lives in ``Program Files``.
        """
        if zipfile.is_zipfile(filepath):
            logger.info(f"{Path(filepath).name} is a ZIP archive with a .cbr name")
            cover = self._extract_zip_cover(filepath)
            if cover is not None:
                return cover

        if not HAS_RARFILE:
            return None

        for attempt in range(2):
            try:
                tool = rar_tools.configure_rarfile(force=attempt > 0)
                if tool is None:
                    logger.warning(
                        f"Cannot read {Path(filepath).name}: no RAR tool installed "
                        "(WinRAR / 7-Zip / bsdtar)"
                    )
                    return None

                with rarfile.RarFile(filepath, "r") as archive:
                    names = [
                        info.filename
                        for info in archive.infolist()
                        if not info.isdir()
                    ]
                    if not names:
                        return None
                    for name in self._cover_candidates(names):
                        try:
                            with archive.open(name) as handle:
                                return Image.open(io.BytesIO(handle.read())).convert("RGB")
                        except Exception as exc:
                            logger.debug(f"Skipping unreadable page {name}: {exc}")
                            continue
                return None

            except rarfile.NeedFirstVolume:
                logger.error(f"Multi-volume RAR not supported: {filepath}")
                return None
            except rarfile.PasswordRequired:
                logger.error(f"Password protected RAR: {filepath}")
                return None
            except rarfile.RarCannotExec:
                # The cached tool did not work; rediscover once, then give up.
                logger.warning(
                    f"RAR tool failed for {Path(filepath).name}; trying another one"
                )
                rar_tools.configure_rarfile(force=True)
                continue
            except Exception as exc:
                if attempt == 0:
                    logger.warning(f"RAR extraction failed ({exc}); retrying with rediscovery")
                    rar_tools.configure_rarfile(force=True)
                    continue
                logger.error(f"RAR extraction error for {filepath}: {exc}")
                return None

        return None

    @staticmethod
    def _normalize_entry(name: str) -> str:
        """Archive entry name with forward slashes and no "./" noise."""
        normalized = str(name).replace("\\", "/").strip()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized.lstrip("/")

    @staticmethod
    def _is_page_name(name: str) -> bool:
        """True for a real comic page, false for folders and archive clutter."""
        normalized = CoverExtractor._normalize_entry(name)
        if not normalized or normalized.endswith("/"):
            return False
        parts = [part for part in normalized.split("/") if part]
        if any(part == "__MACOSX" for part in parts):
            return False
        filename = parts[-1]
        if filename.startswith("."):
            # .DS_Store, macOS resource forks (._page.jpg) and hidden files.
            return False
        if filename.lower() in {"thumbs.db", "desktop.ini"}:
            return False
        return Path(filename).suffix.lower() in CoverExtractor.IMAGE_EXTENSIONS

    @staticmethod
    def _page_sort_key(name: str) -> tuple:
        """Reading order: 1.jpg, 2.jpg, 10.jpg - never plain alphabetical.

        The whole relative path is compared naturally, so pages inside folders
        keep their chapter order as well.
        """
        normalized = CoverExtractor._normalize_entry(name)
        return (natural_sort_key(normalized), normalized.lower())

    @staticmethod
    def _cover_candidates(names: List[str]) -> List[str]:
        """Order archive entries the way a comic reader opens them.

        The first page of the comic is the cover. Only a page literally named
        "cover" is moved in front of it, which is the convention readers such
        as Komga and Kavita follow.
        """
        pages = [name for name in names if CoverExtractor._is_page_name(name)]
        pages.sort(key=CoverExtractor._page_sort_key)
        named_cover = [
            name for name in pages
            if Path(CoverExtractor._normalize_entry(name)).stem.strip().lower()
            == "cover"
        ]
        if named_cover:
            return named_cover + [name for name in pages if name not in named_cover]
        return pages

    def _extract_7z_cover(self, filepath: str) -> Optional[Image.Image]:
        """Extract the first page of a 7z archive as the cover."""
        if not HAS_PY7ZR:
            return None

        try:
            with py7zr.SevenZipFile(filepath, 'r') as sz:
                names = sz.getnames()
            for name in self._cover_candidates(names):
                folder = tempfile.mkdtemp(prefix="dl-7z-")
                try:
                    # One page at a time, unpacked in a scratch folder: py7zr
                    # streams sequentially and its reading API differs between
                    # releases, while ``extract`` is stable.
                    with py7zr.SevenZipFile(filepath, 'r') as sz:
                        sz.extract(path=folder, targets=[name])
                    extracted = Path(
                        folder, *PurePosixPath(name.replace("\\", "/")).parts
                    )
                    if not extracted.is_file():
                        continue
                    with Image.open(extracted) as image:
                        return image.convert('RGB')
                except Exception as exc:
                    logger.debug(f"Skipping unreadable page {name}: {exc}")
                    continue
                finally:
                    shutil.rmtree(folder, ignore_errors=True)
        except Exception as e:
            logger.error(f"7z extraction error for {filepath}: {e}")

        return None
    
    def _extract_tar_cover(self, filepath: str) -> Optional[Image.Image]:
        """Extract the first page of a tar archive as the cover."""
        try:
            with tarfile.open(filepath, 'r:*') as tf:
                members = {m.name: m for m in tf.getmembers() if m.isfile()}
                for name in self._cover_candidates(list(members)):
                    try:
                        handle = tf.extractfile(members[name])
                        if handle is None:
                            continue
                        return Image.open(io.BytesIO(handle.read())).convert('RGB')
                    except Exception as exc:
                        logger.debug(f"Skipping unreadable page {name}: {exc}")
                        continue
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
            removed = 0
            for directory in (self.cache_dir, self._fallback_dir):
                if not directory.exists():
                    continue
                fingerprint = self._fingerprint(filepath)
                wanted = {
                    self._get_cache_path(filepath).stem,
                    self._get_cache_path(filepath, fingerprint).stem,
                }
                wanted.update(
                    Path(name).stem
                    for name in self._legacy_cache_names(filepath, fingerprint)
                )
                for cache_file in directory.glob("*"):
                    if not cache_file.is_file():
                        continue
                    if cache_file.stem in wanted:
                        cache_file.unlink()
                        removed += 1
            if removed:
                logger.info(f"Cleared cache for: {filepath}")
        else:
            for directory in (self.cache_dir, self._fallback_dir):
                if not directory.exists():
                    continue
                for cache_file in directory.glob("*.jpg"):
                    cache_file.unlink()
            logger.info("Cleared all cover cache")


# Global instance
cover_extractor = CoverExtractor()