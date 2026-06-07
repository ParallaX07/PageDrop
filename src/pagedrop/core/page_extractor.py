from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from pagedrop.core.pdf_editor import PageRef


def extract_page_refs_to_files(
    refs: list[PageRef],
    output_dir: Path,
    base_name: str,
) -> list[Path]:
    """Extract pages in *refs* order; output filenames use sequential 1-based indices."""
    readers: dict[str, PdfReader] = {}
    out_paths: list[Path] = []
    for seq, ref in enumerate(refs, start=1):
        if ref.source_path not in readers:
            readers[ref.source_path] = PdfReader(ref.source_path)
        reader = readers[ref.source_path]
        writer = PdfWriter()
        writer.add_page(reader.pages[ref.source_index])
        out_path = output_dir / f"{base_name}_page_{seq:04d}.pdf"
        with open(out_path, "wb") as f:
            writer.write(f)
        out_paths.append(out_path)
    return out_paths


def extract_pages_to_files(
    source_pdf: str,
    page_indices: list[int],
    output_dir: Path,
    base_name: str,
) -> list[Path]:
    reader = PdfReader(source_pdf)
    out_paths = []
    for idx in sorted(page_indices):
        writer = PdfWriter()
        writer.add_page(reader.pages[idx])
        out_path = output_dir / f"{base_name}_page_{idx + 1:04d}.pdf"
        with open(out_path, "wb") as f:
            writer.write(f)
        out_paths.append(out_path)
    return out_paths
