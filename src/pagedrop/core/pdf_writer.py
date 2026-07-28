from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import fitz

from pagedrop.core.jobs.credentials import RuntimeCredentials
from pagedrop.core.markup import MarkupEntry, apply_markup_entries
from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import (
    PdfCorruptError,
    PdfEmptyError,
    PdfNotFoundError,
    PdfPasswordError,
    PdfPasswordRequiredError,
)


def _cached_doc(
    path: str,
    docs: dict[str, fitz.Document],
    passwords: Mapping[str, str] | None,
) -> fitz.Document:
    if path not in docs:
        docs[path] = _open_pdf(
            path, password=RuntimeCredentials.lookup(passwords, path)
        )
    return docs[path]


def _open_pdf(path: str, password: str | None = None) -> fitz.Document:
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
    try:
        if doc.needs_pass:
            if password is None:
                raise PdfPasswordRequiredError(f"PDF is password-protected: {path}")
            if doc.authenticate(password) == 0:
                raise PdfPasswordError(f"Incorrect password for PDF: {path}")
        if doc.page_count == 0:
            raise PdfEmptyError(f"PDF has no pages: {path}")
        return doc
    except Exception:
        doc.close()
        raise


def merge_pdf_files(
    file_paths: list[str],
    output_path: str,
    *,
    passwords: Mapping[str, str] | None = None,
) -> None:
    """Merge whole PDFs in *file_paths* order, writing to *output_path*."""
    if not file_paths:
        raise ValueError("No PDF files to merge")

    docs: dict[str, fitz.Document] = {}
    out = fitz.open()
    try:
        for path in file_paths:
            src = _cached_doc(path, docs, passwords)
            out.insert_pdf(src)
        out.save(output_path)
    finally:
        out.close()
        for doc in docs.values():
            doc.close()


def write_pdf(
    model: PdfEditModel,
    output_path: str,
    *,
    markup: Sequence[MarkupEntry] | None = None,
    passwords: Mapping[str, str] | None = None,
) -> None:
    """Write the logical page list to *output_path*, preserving order.

    Optional *markup* (viewer annotation / form ops) is applied to the
    assembled document before save — originals are never modified.
    *passwords* maps source paths (raw or resolved) to unlock secrets.
    """
    docs: dict[str, fitz.Document] = {}
    out = fitz.open()
    try:
        for logical_index in range(model.logical_count()):
            ref = model.page_at(logical_index)
            src = _cached_doc(ref.source_path, docs, passwords)
            out.insert_pdf(src, from_page=ref.source_index, to_page=ref.source_index)
            if ref.rotation:
                page = out[-1]
                page.set_rotation((page.rotation + ref.rotation) % 360)
        if markup:
            apply_markup_entries(out, markup)
        out.save(output_path)
    finally:
        out.close()
        for doc in docs.values():
            doc.close()
