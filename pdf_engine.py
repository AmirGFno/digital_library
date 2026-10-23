"""
Lightweight PDF backend.

PDF support is limited to two things in this application: rendering the first
page as a cover and reading basic metadata/page counts. ``pypdfium2`` (PDFium,
BSD/Apache licensed) does both with a fraction of the size of PyMuPDF, which
keeps the packaged executable small.

PyMuPDF is still used as an optional fallback for developers who already have it
installed, but it is not required.
"""
from __future__ import annotations

import io
from typing import Dict, Optional

from utils.logger import logger

try:  # preferred, small backend
    import pypdfium2 as _pdfium

    HAS_PDFIUM = True
except Exception:  # pragma: no cover - optional dependency
    _pdfium = None
    HAS_PDFIUM = False

try:  # optional, heavier fallback
    import pymupdf as _fitz  # modern name, no deprecation warning

    HAS_PYMUPDF = True
except Exception:  # pragma: no cover - optional dependency
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            import fitz as _fitz  # older PyMuPDF releases only ship this name

        HAS_PYMUPDF = True
    except Exception:
        _fitz = None
        HAS_PYMUPDF = False

if not HAS_PDFIUM and not HAS_PYMUPDF:
    logger.warning("No PDF backend available; PDF covers will use the fallback image.")


def is_available() -> bool:
    """True when PDF files can be read at all."""
    return HAS_PDFIUM or HAS_PYMUPDF


def get_page_count(filepath: str) -> int:
    """Number of pages in a PDF, or 0 when it cannot be read."""
    if HAS_PDFIUM:
        try:
            document = _pdfium.PdfDocument(filepath)
            try:
                return len(document)
            finally:
                document.close()
        except Exception as exc:
            logger.debug(f"pypdfium2 page count failed for {filepath}: {exc}")

    if HAS_PYMUPDF:
        try:
            with _fitz.open(filepath) as document:
                return int(document.page_count)
        except Exception as exc:
            logger.debug(f"PyMuPDF page count failed for {filepath}: {exc}")

    return 0


def get_metadata(filepath: str) -> Dict[str, object]:
    """Return {'title', 'author'} for a PDF (missing keys are omitted)."""
    raw: Dict[str, str] = {}

    if HAS_PDFIUM:
        try:
            document = _pdfium.PdfDocument(filepath)
            try:
                raw = document.get_metadata_dict() or {}
            finally:
                document.close()
        except Exception as exc:
            logger.debug(f"pypdfium2 metadata failed for {filepath}: {exc}")

    if not raw and HAS_PYMUPDF:
        try:
            with _fitz.open(filepath) as document:
                info = document.metadata or {}
                raw = {"Title": info.get("title", ""), "Author": info.get("author", "")}
        except Exception as exc:
            logger.debug(f"PyMuPDF metadata failed for {filepath}: {exc}")

    metadata: Dict[str, object] = {}
    title = str(raw.get("Title") or "").strip()
    author = str(raw.get("Author") or "").strip()
    if title and title.lower() not in {"untitled", "unknown"}:
        metadata["title"] = title
    if author:
        metadata["writer"] = author
    return metadata


def render_first_page(
    filepath: str,
    max_width: int = 900,
    scale: float = 2.0,
) -> Optional["object"]:
    """Render page 1 of a PDF as a PIL image (RGB), or None on failure."""
    if HAS_PDFIUM:
        try:
            document = _pdfium.PdfDocument(filepath)
            try:
                if len(document) == 0:
                    return None
                page = document[0]
                try:
                    width = page.get_width() or 600
                    factor = min(scale, max(1.0, max_width / float(width)))
                    bitmap = page.render(scale=factor)
                    try:
                        return bitmap.to_pil().convert("RGB")
                    finally:
                        if hasattr(bitmap, "close"):
                            bitmap.close()
                finally:
                    page.close()
            finally:
                document.close()
        except Exception as exc:
            logger.debug(f"pypdfium2 render failed for {filepath}: {exc}")

    if HAS_PYMUPDF:
        try:
            from PIL import Image

            with _fitz.open(filepath) as document:
                if document.page_count == 0:
                    return None
                pix = document[0].get_pixmap(matrix=_fitz.Matrix(scale, scale))
                return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        except Exception as exc:
            logger.debug(f"PyMuPDF render failed for {filepath}: {exc}")

    return None
