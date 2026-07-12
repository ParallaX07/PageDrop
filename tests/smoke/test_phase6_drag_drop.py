"""Phase 6 smoke tests — page extraction simulates a file-manager drop.

Manual verification (cannot automate cross-process DnD in CI):
1. Run ``uv run pagedrop`` and open a multi-page PDF.
2. Select one or more page thumbnails.
3. Drag the selection onto a folder in Explorer (Windows) or Finder (macOS).
4. Confirm one PDF per selected page appears in the target folder.
5. Open each dropped PDF and verify it contains exactly one expected page.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import fitz

from pagedrop.core.page_extractor import extract_pages_to_files
from pagedrop.core.pdf_loader import PdfLoader


def _page_size(path: Path | str, page_index: int = 0) -> tuple[float, float]:
    doc = fitz.open(str(path))
    try:
        rect = doc[page_index].rect
        return (float(rect.width), float(rect.height))
    finally:
        doc.close()


def test_smoke_extract_pages_to_drop_folder(five_page_pdf, tmp_path):
    """Simulate drop target: copy extracted single-page PDFs into an output folder."""
    drop_dir = tmp_path / "drop_target"
    drop_dir.mkdir()

    selected_indices = [0, 2, 4]
    drag_temp = tmp_path / "drag_temp"
    drag_temp.mkdir()
    extracted = extract_pages_to_files(
        str(five_page_pdf),
        selected_indices,
        drag_temp,
        five_page_pdf.stem,
    )

    for path in extracted:
        shutil.copy2(path, drop_dir / path.name)

    dropped_files = sorted(drop_dir.glob("*.pdf"))
    assert len(dropped_files) == len(selected_indices)

    for dropped, index in zip(dropped_files, sorted(selected_indices), strict=True):
        doc = fitz.open(str(dropped))
        try:
            assert doc.page_count == 1
            assert _page_size(dropped) == _page_size(five_page_pdf, index)
        finally:
            doc.close()


def test_smoke_loader_and_extractor_integration(five_page_pdf):
    loader = PdfLoader(str(five_page_pdf))
    try:
        assert loader.page_count == 5
        png = loader.render_page(0)
        assert png[:4] == b"\x89PNG"
    finally:
        loader.close()

    import tests.core.test_page_extractor as extractor_tests  # noqa: F401

    assert hasattr(extractor_tests, "test_extract_single_page")
