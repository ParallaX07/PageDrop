"""Phase 28 / 28b smoke — watermark + page numbers; never-overwrite."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from pagedrop.core import modify_ops as ops


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    source_hash = _file_hash(src)

    watermarked = tmp_path / "wm.pdf"
    ops.add_text_watermark(str(src), str(watermarked), text="DRAFT")
    assert _file_hash(src) == source_hash
    assert watermarked.resolve() != src.resolve()

    numbered = tmp_path / "num.pdf"
    ops.add_page_numbers(
        str(watermarked),
        str(numbered),
        template="{page}/{total}",
        position="bottom-center",
    )
    assert _file_hash(src) == source_hash
    wm_hash = _file_hash(watermarked)

    doc = fitz.open(str(numbered))
    try:
        assert doc.page_count == 2
        t0 = doc[0].get_text()
        t1 = doc[1].get_text()
        assert "DRAFT" in t0
        assert "1/2" in t0
        assert "2/2" in t1
        assert "phase28 body" in t0
    finally:
        doc.close()
    assert _file_hash(watermarked) == wm_hash
    assert _file_hash(src) == source_hash
