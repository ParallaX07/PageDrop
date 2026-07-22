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


class PdfLoader:
    def __init__(self, path: str, password: str | None = None) -> None:
        self.path = path
        try:
            if not Path(path).is_file():
                raise PdfNotFoundError(f"PDF not found: {path}")
        except OSError as exc:
            # Removable / network volumes: is_file() itself can raise.
            raise PdfLoadError(
                f"Could not access PDF (drive disconnected or I/O error): {path}"
            ) from exc

        try:
            self.doc = fitz.open(path)
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

        if self.doc.needs_pass:
            if password is None:
                self.doc.close()
                raise PdfPasswordRequiredError(
                    f"PDF is password-protected: {path}"
                )
            if self.doc.authenticate(password) == 0:
                self.doc.close()
                raise PdfPasswordError(f"Incorrect password for PDF: {path}")

        if len(self.doc) == 0:
            self.doc.close()
            raise PdfEmptyError(f"PDF has no pages: {path}")

    @property
    def page_count(self) -> int:
        return len(self.doc)

    def render_page(self, page_index: int, width_px: int = 160) -> bytes:
        """Render page to PNG bytes at target width."""
        return render_page_png(self.doc, page_index, width_px=width_px)

    def page_size_mm(self, page_index: int) -> tuple[int, int]:
        """Return (width_mm, height_mm) for a page, rounded to nearest mm."""
        return page_size_mm(self.doc, page_index)

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self.doc.close()
        self._closed = True


MAX_RENDER_DPI = 150
MAX_RENDER_WIDTH_PX = 2048

_MM_PER_POINT = 25.4 / 72.0
_MAX_RENDER_SCALE = MAX_RENDER_DPI / 72.0


def page_size_mm(doc: fitz.Document, page_index: int) -> tuple[int, int]:
    """Return (width_mm, height_mm) for a page, rounded to nearest mm."""
    page = doc[page_index]
    width_mm = round(page.rect.width * _MM_PER_POINT)
    height_mm = round(page.rect.height * _MM_PER_POINT)
    return width_mm, height_mm


def render_page_png(
    doc: fitz.Document, page_index: int, width_px: int = 160
) -> bytes:
    """Render a page from an open PyMuPDF document to PNG bytes."""
    page = doc[page_index]
    page_width = page.rect.width
    if page_width <= 0:
        raise ValueError(f"Page {page_index} has invalid width")

    scale = min(width_px / page_width, _MAX_RENDER_SCALE)
    if page_width * scale > MAX_RENDER_WIDTH_PX:
        scale = MAX_RENDER_WIDTH_PX / page_width

    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")
