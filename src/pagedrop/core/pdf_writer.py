from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import fitz

from pagedrop.core.jobs.credentials import RuntimeCredentials
from pagedrop.core.markup import MarkupEntry, apply_markup_entries
from pagedrop.core.pdf_editor import PageRef, PdfEditModel
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


def append_page_refs(
    out: fitz.Document,
    refs: Sequence[PageRef],
    docs: dict[str, fitz.Document],
    passwords: Mapping[str, str] | None = None,
) -> None:
    """Append *refs* to *out*, batching contiguous same-source page ranges.

    Contiguous means same ``source_path`` and consecutive ``source_index``.
    Rotation is applied per page after each batched insert so multi-source and
    mixed-rotation lists stay correct.
    """
    i = 0
    n = len(refs)
    while i < n:
        ref = refs[i]
        j = i + 1
        while (
            j < n
            and refs[j].source_path == ref.source_path
            and refs[j].source_index == refs[j - 1].source_index + 1
        ):
            j += 1
        src = _cached_doc(ref.source_path, docs, passwords)
        dest_start = out.page_count
        out.insert_pdf(
            src,
            from_page=ref.source_index,
            to_page=refs[j - 1].source_index,
        )
        for offset, run_ref in enumerate(refs[i:j]):
            if run_ref.rotation:
                page = out[dest_start + offset]
                page.set_rotation((page.rotation + run_ref.rotation) % 360)
        i = j


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
    Contiguous same-source ranges use one ``insert_pdf`` call.
    """
    docs: dict[str, fitz.Document] = {}
    out = fitz.open()
    try:
        append_page_refs(out, model.iter_pages(), docs, passwords)
        if markup:
            apply_markup_entries(out, markup)
        out.save(output_path)
    finally:
        out.close()
        for doc in docs.values():
            doc.close()
