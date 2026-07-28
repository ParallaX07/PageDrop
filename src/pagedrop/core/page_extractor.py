from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import fitz

from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_loader import (
    PdfCorruptError,
    PdfEmptyError,
    PdfNotFoundError,
    PdfPasswordError,
    PdfPasswordRequiredError,
)
from pagedrop.core.pdf_writer import append_page_refs


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


def extract_page_refs_to_pdf(
    refs: list[PageRef],
    output_path: str | Path,
    *,
    passwords: Mapping[str, str] | None = None,
) -> Path:
    """Write all *refs* into one multi-page PDF (batched contiguous inserts).

    Use this when a single multi-page file is intended. One-file-per-page drag /
    folder export stays on ``extract_page_refs_to_files``.
    """
    if not refs:
        raise ValueError("No pages to extract")
    out_path = Path(output_path)
    docs: dict[str, fitz.Document] = {}
    out = fitz.open()
    try:
        append_page_refs(out, refs, docs, passwords)
        out.save(str(out_path))
    finally:
        out.close()
        for doc in docs.values():
            doc.close()
    return out_path


def extract_page_refs_to_files(
    refs: list[PageRef],
    output_dir: Path,
    base_name: str,
    *,
    passwords: Mapping[str, str] | None = None,
) -> list[Path]:
    """Extract pages in *refs* order; output filenames use sequential 1-based indices.

    Each ref is its own single-page PDF (drag / export-to-folder contract). Source
    docs are opened once per path and shared across the loop.
    """
    docs: dict[str, fitz.Document] = {}
    out_paths: list[Path] = []
    try:
        for seq, ref in enumerate(refs, start=1):
            out_path = output_dir / f"{base_name}_page_{seq:04d}.pdf"
            out = fitz.open()
            try:
                # Single-page file — append_page_refs keeps rotation / password
                # handling identical to the multi-page extract path.
                append_page_refs(out, [ref], docs, passwords)
                out.save(str(out_path))
                out_paths.append(out_path)
            finally:
                out.close()
    finally:
        for doc in docs.values():
            doc.close()
    return out_paths


def extract_pages_to_files(
    source_pdf: str,
    page_indices: list[int],
    output_dir: Path,
    base_name: str,
    *,
    password: str | None = None,
) -> list[Path]:
    src = _open_pdf(source_pdf, password=password)
    out_paths: list[Path] = []
    try:
        for idx in sorted(page_indices):
            out = fitz.open()
            try:
                out.insert_pdf(src, from_page=idx, to_page=idx)
                out_path = output_dir / f"{base_name}_page_{idx + 1:04d}.pdf"
                out.save(str(out_path))
                out_paths.append(out_path)
            finally:
                out.close()
    finally:
        src.close()
    return out_paths
