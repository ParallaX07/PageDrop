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
from pagedrop.core.pdf_loader import open_pdf
from pagedrop.core.thread_policy import FITZ_LOCK, yield_fitz_lock

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


def _ocr_page_into(
    doc: fitz.Document,
    out: fitz.Document,
    index: int,
    *,
    dpi: int,
    language: str,
    tessdata: str,
) -> None:
    """OCR page *index* of *doc* and append it to *out*. Caller holds FITZ_LOCK.

    Page, pixmap and the temporary document are released here, under the lock,
    including when OCR fails.
    """
    page = pix = ocr_page = None
    failure: str | None = None
    try:
        page = doc[index]
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        try:
            pdf_bytes = pix.pdfocr_tobytes(
                compress=True,
                language=language,
                tessdata=tessdata,
            )
        except Exception as exc:  # noqa: BLE001 — surfaced as OcrError below
            failure = str(exc)
        if failure is None:
            ocr_page = fitz.open("pdf", pdf_bytes)
            out.insert_pdf(ocr_page)
    finally:
        if ocr_page is not None:
            ocr_page.close()
        page = pix = ocr_page = None
    if failure is not None:
        # Raised outside the except block so the failed call's traceback, which
        # would pin the pixmap, is already released under the lock.
        raise OcrError(f"OCR failed on page {index + 1}: {failure}")


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

    doc: fitz.Document | None = None
    out: fitz.Document | None = None
    try:
        # Every fitz touch takes FITZ_LOCK per step so the GUI is never stalled
        # for the whole run; cancel checks and progress run outside it.
        with FITZ_LOCK:
            doc = open_pdf(str(source_path), password)
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
            with FITZ_LOCK:
                _ocr_page_into(
                    doc,
                    out,
                    index,
                    dpi=dpi,
                    language=language,
                    tessdata=tessdata_dir,
                )
            yield_fitz_lock()
        if cancel is not None:
            cancel.check()
        report(0.95, "Writing searchable PDF…")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with FITZ_LOCK:
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
        with FITZ_LOCK:
            if out is not None:
                out.close()
            if doc is not None:
                doc.close()
            doc = out = None
