from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF


class PdfLoadError(Exception):
    """Base class for PDF loading failures."""


class PdfNotFoundError(PdfLoadError):
    """Raised when the PDF path does not exist."""


class PdfCorruptError(PdfLoadError):
    """Raised when the file is empty or not a valid PDF."""


class PdfPasswordRequiredError(PdfLoadError):
    """Raised when the PDF is encrypted and no password was supplied."""


class PdfPasswordError(PdfLoadError):
    """Raised when the supplied password is incorrect."""


class PdfLoader:
    def __init__(self, path: str, password: str | None = None) -> None:
        self.path = path
        if not Path(path).is_file():
            raise PdfNotFoundError(f"PDF not found: {path}")

        try:
            self.doc = fitz.open(path)
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

    @property
    def page_count(self) -> int:
        return len(self.doc)

    def render_page(self, page_index: int, width_px: int = 160) -> bytes:
        """Render page to PNG bytes at target width."""
        page = self.doc[page_index]
        scale = width_px / page.rect.width
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")

    def close(self) -> None:
        self.doc.close()
