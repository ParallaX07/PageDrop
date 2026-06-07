from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter


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
