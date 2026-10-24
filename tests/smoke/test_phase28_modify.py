"""Phase 28 / 28b smoke — watermark + page numbers; never-overwrite."""

from __future__ import annotations

from pathlib import Path

import fitz

from pagedrop.core import modify_ops as ops
from tests.conftest import file_sha256


def _make_pdf(path: Path, *, text: str = "phase28 body", pages: int = 2) -> Path:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=300, height=300)
            page.insert_text((40, 80), f"{text} {i + 1}", fontsize=16)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_smoke_watermark_and_page_numbers(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    source_hash = file_sha256(src)

    watermarked = tmp_path / "wm.pdf"
    ops.add_text_watermark(str(src), str(watermarked), text="DRAFT")
    assert file_sha256(src) == source_hash
    assert watermarked.resolve() != src.resolve()

    numbered = tmp_path / "num.pdf"
    ops.add_page_numbers(
        str(watermarked),
        str(numbered),
        template="{page}/{total}",
        position="bottom-center",
    )
    assert file_sha256(src) == source_hash
    wm_hash = file_sha256(watermarked)

    doc = fitz.open(str(numbered))
    try:
        assert doc.page_count == 2
        t0 = doc[0].get_text()
        t1 = doc[1].get_text()
        # DRAFT is rasterized for rotated watermark (avoids mirrored glyphs)
        assert doc[0].get_images()
        assert "1/2" in t0
        assert "2/2" in t1
        assert "phase28 body" in t0
    finally:
        doc.close()
    assert file_sha256(watermarked) == wm_hash
    assert file_sha256(src) == source_hash
