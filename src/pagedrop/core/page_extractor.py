from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import fitz

from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_loader import open_pdf
from pagedrop.core.pdf_service import FITZ_LOCK
from pagedrop.core.pdf_writer import append_page_refs


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
    with FITZ_LOCK:
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
    with FITZ_LOCK:
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
    with FITZ_LOCK:
        src = open_pdf(source_pdf, password=password)
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
