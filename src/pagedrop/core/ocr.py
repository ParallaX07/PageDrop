"""OCR → searchable PDF via PyMuPDF built-in Tesseract (Phase 29).

Requires configured ``tessdata`` (+ languages). Writes a **new** PDF; never
overwrites the source. Pages are rasterized with an OCR text layer
(``Pixmap.pdfocr_tobytes``) — suitable for scans; vector text on those pages
is replaced by the OCR image + invisible text.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import fitz

from pagedrop.core.capabilities import (
    TESSDATA,
    AbsenceReason,
    probe,
    resolve_tessdata_dir,
)
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import BackendUnavailableError
from pagedrop.core.jobs.paths import reject_source_overwrite
from pagedrop.core.pdf_tools import _open

ProgressCallback = Callable[[float, str], None]


class OcrError(Exception):
    """Raised when OCR fails for a reason other than missing tessdata."""


def _require_tessdata(tessdata: str | None) -> str:
    if tessdata:
        path = Path(tessdata)
        if path.is_dir() and any(path.glob("*.traineddata")):
            return str(path.resolve())
        raise BackendUnavailableError(
            TESSDATA,
            AbsenceReason.DATA_MISSING,
            f"No traineddata files in {path}",
        )
    status = probe(TESSDATA)
    if not status.available:
        raise BackendUnavailableError(
            TESSDATA,
            status.reason or AbsenceReason.DATA_MISSING,
            status.detail,
        )
    directory = resolve_tessdata_dir()
    if directory is None:
        raise BackendUnavailableError(
            TESSDATA,
            AbsenceReason.DATA_MISSING,
            "tessdata path unresolved after successful probe",
        )
    return str(directory)


def _page_indices(doc: fitz.Document, pages: Sequence[int] | None) -> list[int]:
    count = doc.page_count
    if pages is None:
        return list(range(count))
    indices: list[int] = []
    for index in pages:
        if index < 0 or index >= count:
            raise OcrError(f"Page index {index} out of range (0–{count - 1})")
        indices.append(int(index))
    if not indices:
        raise OcrError("No pages selected")
    return indices


def ocr_pdf(
    source: str | Path,
    output: str | Path,
    *,
    language: str = "eng",
    pages: Sequence[int] | None = None,
    dpi: int = 300,
    password: str | None = None,
    tessdata: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """Create a searchable PDF copy with an OCR text layer.

    *pages* are 0-based source indices; ``None`` means all pages. Output is a
    new file (source overwrite rejected). Cooperative *cancel* is checked
    between pages; partial staged files are the caller's responsibility.
    """
    source_path = Path(source)
    output_path = Path(output)
    reject_source_overwrite(output_path, source_path)
    tessdata_dir = _require_tessdata(tessdata)
    dpi = max(72, int(dpi))

    def report(frac: float, message: str) -> None:
        if progress is not None:
            progress(frac, message)

    doc = _open(str(source_path), password)
    out: fitz.Document | None = None
    try:
        indices = _page_indices(doc, pages)
        out = fitz.open()
        total = len(indices)
        for n, index in enumerate(indices):
            if cancel is not None:
                cancel.check()
            report(
                n / max(total, 1),
                f"OCR page {n + 1} of {total}…",
            )
            page = doc[index]
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            try:
                pdf_bytes = pix.pdfocr_tobytes(
                    compress=True,
                    language=language,
                    tessdata=tessdata_dir,
                )
            except Exception as exc:  # noqa: BLE001 — surface as OcrError
                raise OcrError(f"OCR failed on page {index + 1}: {exc}") from exc
            finally:
                pix = None  # type: ignore[assignment]
            ocr_page = fitz.open("pdf", pdf_bytes)
            try:
                out.insert_pdf(ocr_page)
            finally:
                ocr_page.close()
        if cancel is not None:
            cancel.check()
        report(0.95, "Writing searchable PDF…")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out.save(
            str(output_path),
            garbage=3,
            deflate=True,
            clean=True,
            incremental=False,
        )
        report(1.0, "OCR complete")
        return output_path
    finally:
        if out is not None:
            out.close()
        doc.close()
