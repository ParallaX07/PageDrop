from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import fitz

from pagedrop.core.jobs.credentials import RuntimeCredentials
from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_loader import (
    PdfCorruptError,
    PdfEmptyError,
    PdfNotFoundError,
    PdfPasswordError,
    PdfPasswordRequiredError,
)


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


def extract_page_refs_to_files(
    refs: list[PageRef],
    output_dir: Path,
    base_name: str,
    *,
    passwords: Mapping[str, str] | None = None,
) -> list[Path]:
    """Extract pages in *refs* order; output filenames use sequential 1-based indices."""
    docs: dict[str, fitz.Document] = {}
    out_paths: list[Path] = []
    try:
        for seq, ref in enumerate(refs, start=1):
            if ref.source_path not in docs:
                docs[ref.source_path] = _open_pdf(
                    ref.source_path,
                    password=RuntimeCredentials.lookup(passwords, ref.source_path),
                )
            src = docs[ref.source_path]
            out = fitz.open()
            try:
                out.insert_pdf(src, from_page=ref.source_index, to_page=ref.source_index)
                if ref.rotation:
                    page = out[-1]
                    page.set_rotation((page.rotation + ref.rotation) % 360)
                out_path = output_dir / f"{base_name}_page_{seq:04d}.pdf"
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
