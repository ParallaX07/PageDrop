from __future__ import annotations

from pathlib import Path

import fitz

from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import (
    PdfCorruptError,
    PdfEmptyError,
    PdfNotFoundError,
)


def _cached_doc(path: str, docs: dict[str, fitz.Document]) -> fitz.Document:
    if path not in docs:
        docs[path] = _open_pdf(path)
    return docs[path]


def _open_pdf(path: str) -> fitz.Document:
    if not Path(path).is_file():
        raise PdfNotFoundError(f"PDF not found: {path}")
    try:
        doc = fitz.open(path)
    except fitz.EmptyFileError as exc:
        raise PdfCorruptError(f"PDF file is empty: {path}") from exc
    except fitz.FileDataError as exc:
        raise PdfCorruptError(f"PDF file is corrupt or invalid: {path}") from exc
    except fitz.FileNotFoundError as exc:
        raise PdfNotFoundError(f"PDF not found: {path}") from exc
    if doc.page_count == 0:
        doc.close()
        raise PdfEmptyError(f"PDF has no pages: {path}")
    return doc


def merge_pdf_files(file_paths: list[str], output_path: str) -> None:
    """Merge whole PDFs in *file_paths* order, writing to *output_path*."""
    if not file_paths:
        raise ValueError("No PDF files to merge")

    docs: dict[str, fitz.Document] = {}
    out = fitz.open()
    try:
        for path in file_paths:
            src = _cached_doc(path, docs)
            out.insert_pdf(src)
        out.save(output_path)
    finally:
        out.close()
        for doc in docs.values():
            doc.close()


def write_pdf(model: PdfEditModel, output_path: str) -> None:
    """Write the logical page list to *output_path*, preserving order."""
    docs: dict[str, fitz.Document] = {}
    out = fitz.open()
    try:
        for logical_index in range(model.logical_count()):
            ref = model.page_at(logical_index)
            src = _cached_doc(ref.source_path, docs)
            out.insert_pdf(src, from_page=ref.source_index, to_page=ref.source_index)
            if ref.rotation:
                page = out[-1]
                page.set_rotation((page.rotation + ref.rotation) % 360)
        out.save(output_path)
    finally:
        out.close()
        for doc in docs.values():
            doc.close()
