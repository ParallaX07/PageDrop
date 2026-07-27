"""Phase 25 smoke — PNG + TXT export happy path; sources unchanged."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from pagedrop.core import native_conversions as nc


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_text_pdf(path: Path, texts: list[str]) -> Path:
    doc = fitz.open()
    try:
        for text in texts:
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), text, fontsize=16)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_smoke_png_and_txt_export(tmp_path: Path) -> None:
    source = _make_text_pdf(
        tmp_path / "born.pdf",
        ["Hello PageDrop", "page-two"],
    )
    source_hash = _file_hash(source)

    png_dir = tmp_path / "png"
    written = nc.export_pdf(source, png_dir, format_id="png", dpi=72)
    assert len(written) == 2
    assert all(p.suffix == ".png" and p.is_file() and p.stat().st_size > 0 for p in written)
    assert _file_hash(source) == source_hash

    txt = tmp_path / "born.txt"
    nc.export_pdf(source, txt, format_id="text")
    body = txt.read_text(encoding="utf-8")
    assert "Hello PageDrop" in body
    assert "page-two" in body
    assert _file_hash(source) == source_hash
    assert txt.resolve() != source.resolve()
