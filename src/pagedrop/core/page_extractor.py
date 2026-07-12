from __future__ import annotations

from pathlib import Path

import fitz

from pagedrop.core.pdf_editor import PageRef


def extract_page_refs_to_files(
    refs: list[PageRef],
    output_dir: Path,
    base_name: str,
) -> list[Path]:
    """Extract pages in *refs* order; output filenames use sequential 1-based indices."""
    docs: dict[str, fitz.Document] = {}
    out_paths: list[Path] = []
    try:
        for seq, ref in enumerate(refs, start=1):
            if ref.source_path not in docs:
                docs[ref.source_path] = fitz.open(ref.source_path)
            src = docs[ref.source_path]
            out = fitz.open()
            try:
                out.insert_pdf(src, from_page=ref.source_index, to_page=ref.source_index)
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
) -> list[Path]:
    src = fitz.open(source_pdf)
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
