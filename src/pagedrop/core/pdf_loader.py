from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF


class PdfLoadError(Exception):
    """Base class for PDF loading failures."""


class PdfNotFoundError(PdfLoadError):
    """Raised when the PDF path does not exist."""


class PdfCorruptError(PdfLoadError):
    """Raised when the file is empty or not a valid PDF."""


class PdfEmptyError(PdfLoadError):
    """Raised when the PDF is valid but contains no pages."""


class PdfPasswordRequiredError(PdfLoadError):
    """Raised when the PDF is encrypted and no password was supplied."""


class PdfPasswordError(PdfLoadError):
    """Raised when the supplied password is incorrect."""


def open_pdf(path: str, password: str | None = None) -> fitz.Document:
    """Open a PDF with typed load errors. Caller owns ``close()``.

    Shared by tools, writer, extractor, forms, annotations, and pdf_service —
    password / empty / corrupt / missing paths all close the handle on failure.
    """
    try:
        if not Path(path).is_file():
            raise PdfNotFoundError(f"PDF not found: {path}")
    except OSError as exc:
        # Removable / network volumes: is_file() itself can raise.
        raise PdfLoadError(
            f"Could not access PDF (drive disconnected or I/O error): {path}"
        ) from exc

    try:
        doc = fitz.open(path)
    except OSError as exc:
        raise PdfLoadError(
            f"Could not access PDF (drive disconnected or I/O error): {path}"
        ) from exc
    except fitz.EmptyFileError as exc:
        raise PdfCorruptError(f"PDF file is empty: {path}") from exc
    except fitz.FileDataError as exc:
        raise PdfCorruptError(f"PDF file is corrupt or invalid: {path}") from exc
    except fitz.FileNotFoundError as exc:
        raise PdfNotFoundError(f"PDF not found: {path}") from exc

    try:
        if doc.needs_pass:
            if password is None:
                raise PdfPasswordRequiredError(
                    f"PDF is password-protected: {path}"
                )
            if doc.authenticate(password) == 0:
                raise PdfPasswordError(f"Incorrect password for PDF: {path}")

        if len(doc) == 0:
            raise PdfEmptyError(f"PDF has no pages: {path}")
        return doc
    except Exception:
        doc.close()
        raise


class PdfLoader:
    # ponytail: tab-owned long-lived Document for editor geometry / sync UI.
    # Distinct from pdf_service's short TTL path→doc cache (interactive render).
    # Ceiling: two open docs per path while a tab is live. Upgrade: fold tab
    # geometry reads into pdf_service under FITZ_LOCK when measured pain warrants
    # (O10 process service / single-owner cache) — do not invent a third cache.
    def __init__(self, path: str, password: str | None = None) -> None:
        self.path = path
        self.doc = open_pdf(path, password)
        self._size_cache: dict[tuple[int, int], tuple[int, int]] = {}
        self._pt_size_cache: dict[int, tuple[float, float]] = {}

    @property
    def page_count(self) -> int:
        return len(self.doc)

    def render_page(
        self, page_index: int, width_px: int = 160, *, rotation: int = 0
    ) -> bytes:
        """Render page to PNG bytes at target width."""
        return render_page_png(
            self.doc, page_index, width_px=width_px, rotation=rotation
        )

    def page_size_pt(self, page_index: int) -> tuple[float, float]:
        """Unrotated page size in points (page.rect already honors /Rotate)."""
        cached = self._pt_size_cache.get(page_index)
        if cached is None:
            rect = self.doc[page_index].rect
            cached = (float(rect.width), float(rect.height))
            self._pt_size_cache[page_index] = cached
        return cached

    def page_size_mm(self, page_index: int, *, rotation: int = 0) -> tuple[int, int]:
        """Return (width_mm, height_mm) for a page, rounded to nearest mm."""
        key = (page_index, rotation % 360)
        cached = self._size_cache.get(key)
        if cached is None:
            cached = page_size_mm(self.doc, page_index, rotation=rotation)
            self._size_cache[key] = cached
        return cached


    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self.doc.close()
        self._closed = True


MAX_RENDER_DPI = 150  # documented legacy; width cap is the real safety limit
MAX_RENDER_WIDTH_PX = 2048

_MM_PER_POINT = 25.4 / 72.0


def page_size_mm(
    doc: fitz.Document, page_index: int, *, rotation: int = 0
) -> tuple[int, int]:
    """Return (width_mm, height_mm) for a page, rounded to nearest mm."""
    page = doc[page_index]
    width_mm = round(page.rect.width * _MM_PER_POINT)
    height_mm = round(page.rect.height * _MM_PER_POINT)
    if rotation % 180 == 90:
        return height_mm, width_mm
    return width_mm, height_mm


def render_page_png(
    doc: fitz.Document,
    page_index: int,
    width_px: int = 160,
    *,
    rotation: int = 0,
) -> bytes:
    """Render a page from an open PyMuPDF document to PNG bytes.

    Honors *width_px* up to ``MAX_RENDER_WIDTH_PX``. (An older 150 DPI clamp
    made full-page viewer tiles soft whenever fit-width exceeded ~1275 px.)
    """
    page = doc[page_index]
    rot = ((rotation // 90) % 4) * 90
    # page.rect already reflects the PDF /Rotate flag; *rotation* is extra.
    basis = page.rect.height if rot in (90, 270) else page.rect.width
    if basis <= 0:
        raise ValueError(f"Page {page_index} has invalid width")

    target = max(1, min(int(width_px), MAX_RENDER_WIDTH_PX))
    scale = target / basis
    mat = fitz.Matrix(scale, scale).prerotate(rot)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")
