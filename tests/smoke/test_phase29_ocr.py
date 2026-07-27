"""Phase 29 smoke — gated searchable PDF when PAGEDROP_TESSDATA is set."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import fitz
import pytest

from pagedrop.core import ocr as ocr_mod


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.tessdata
def test_phase29_ocr_searchable_pdf(tmp_path):
    tess = os.environ.get("PAGEDROP_TESSDATA", "").strip()
    if not tess or not Path(tess).is_dir():
        pytest.skip("Set PAGEDROP_TESSDATA to run Phase 29 OCR smoke")

    # Image-only page with known glyph content.
    src = tmp_path / "scan.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=200)
        page.insert_text((60, 120), "PHASE29OCR", fontsize=36)
        pix = page.get_pixmap(dpi=200, alpha=False)
        out_doc = fitz.open()
        img_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
        img_page.insert_image(img_page.rect, pixmap=pix)
        out_doc.save(str(src))
        out_doc.close()
    finally:
        doc.close()

    before = _file_hash(src)
    out = tmp_path / "searchable.pdf"
    ocr_mod.ocr_pdf(src, out, tessdata=tess, language="eng", dpi=200)
    assert out.is_file()
    assert _file_hash(src) == before

    result = fitz.open(out)
    try:
        text = "".join(ch for ch in result[0].get_text() if ch.isalnum()).upper()
    finally:
        result.close()
    assert "PHASE29OCR" in text
