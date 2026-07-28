"""Phase 28 core — crop, watermark, page numbers, bookmarks, blank detect."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core import modify_ops as ops
from pagedrop.core.jobs.errors import SourceOverwriteError


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_pdf(
    path: Path,
    *,
    text: str = "hello",
    pages: int = 1,
    width: float = 400,
    height: float = 400,
) -> Path:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=width, height=height)
            page.insert_text((40, 80), f"{text} {i + 1}" if pages > 1 else text, fontsize=18)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_watermark_text_present_source_unchanged(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", text="body")
    source_hash = _file_hash(src)
    out = tmp_path / "wm.pdf"
    ops.add_text_watermark(str(src), str(out), text="CONFIDENTIAL")
    assert _file_hash(src) == source_hash
    doc = fitz.open(str(out))
    try:
        assert "CONFIDENTIAL" in doc[0].get_text()
        assert "body" in doc[0].get_text()
    finally:
        doc.close()
    with pytest.raises(SourceOverwriteError):
        ops.add_text_watermark(str(src), str(src), text="X")


def test_watermark_diagonal_percent_page_range_flatten(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", text="body", pages=3, width=400, height=400)
    source_hash = _file_hash(src)
    out = tmp_path / "diag.pdf"
    ops.add_text_watermark(
        str(src),
        str(out),
        text="MARK",
        diagonal_percent=50.0,
        rotate=-45,
        position="center",
        pages=[1],
        opacity=0.3,
    )
    assert _file_hash(src) == source_hash
    doc = fitz.open(str(out))
    try:
        assert "MARK" not in doc[0].get_text()
        assert "MARK" in doc[1].get_text()
        assert "MARK" not in doc[2].get_text()
    finally:
        doc.close()

    flat = tmp_path / "flat.pdf"
    ops.add_text_watermark(
        str(src),
        str(flat),
        text="SECRET",
        diagonal_percent=40.0,
        flatten=True,
    )
    assert _file_hash(src) == source_hash
    doc = fitz.open(str(flat))
    try:
        text = doc[0].get_text()
        assert "SECRET" not in text
        assert "body" not in text
        assert doc[0].get_images()
    finally:
        doc.close()


def test_watermark_free_placement_center_fractions(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", text="body", width=400, height=400)
    source_hash = _file_hash(src)
    out = tmp_path / "free.pdf"
    cx_f, cy_f = 0.2, 0.8
    ops.add_text_watermark(
        str(src),
        str(out),
        text="HERE",
        fontsize=24,
        rotate=0,
        diagonal_percent=None,
        center_x=cx_f,
        center_y=cy_f,
        opacity=1.0,
    )
    assert _file_hash(src) == source_hash
    doc = fitz.open(str(out))
    try:
        assert "HERE" in doc[0].get_text()
        # Visual glyph center must match preview page-relative placement.
        blocks = doc[0].get_text("dict")["blocks"]
        spans = [
            span
            for block in blocks
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if "HERE" in span["text"]
        ]
        assert spans
        bb = fitz.Rect(spans[0]["bbox"])
        expect_x, expect_y = cx_f * 400, cy_f * 400
        assert abs((bb.x0 + bb.x1) / 2 - expect_x) < 2.0
        assert abs((bb.y0 + bb.y1) / 2 - expect_y) < 2.0
    finally:
        doc.close()

    cx, cy = ops.position_center_fractions(400, 400, "center")
    assert abs(cx - 0.5) < 1e-6
    assert abs(cy - 0.5) < 1e-6

    # Snap preset fractions → apply at those coords lands on the same anchor.
    snap_out = tmp_path / "snap.pdf"
    sx, sy = ops.position_center_fractions(400, 400, "top-left")
    ops.add_text_watermark(
        str(src),
        str(snap_out),
        text="SNAP",
        fontsize=18,
        rotate=0,
        diagonal_percent=None,
        center_x=sx,
        center_y=sy,
        opacity=1.0,
    )
    doc = fitz.open(str(snap_out))
    try:
        spans = [
            span
            for block in doc[0].get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if "SNAP" in span["text"]
        ]
        assert spans
        bb = fitz.Rect(spans[0]["bbox"])
        assert abs((bb.x0 + bb.x1) / 2 - sx * 400) < 2.0
        assert abs((bb.y0 + bb.y1) / 2 - sy * 400) < 2.0
    finally:
        doc.close()


def test_watermark_image_free_placement_matches_preview_center(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", text="body", width=400, height=400)
    source_hash = _file_hash(src)
    img = tmp_path / "wm.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 40), 1)
    pix.set_rect(pix.irect, (200, 40, 40, 255))
    pix.save(str(img))

    cx_f, cy_f = 0.25, 0.75
    out = tmp_path / "img_wm.pdf"
    ops.add_image_watermark(
        str(src),
        str(out),
        image_path=str(img),
        rotate=0,
        opacity=1.0,
        center_x=cx_f,
        center_y=cy_f,
        diagonal_percent=40.0,
    )
    assert _file_hash(src) == source_hash
    expect_x, expect_y = cx_f * 400, cy_f * 400
    diag = (400**2 + 400**2) ** 0.5
    expect_w = diag * 0.4
    expect_h = expect_w * (40 / 80)
    doc = fitz.open(str(out))
    try:
        rects = []
        for item in doc[0].get_images():
            rects.extend(doc[0].get_image_rects(item[0]))
        assert rects
        r = rects[0]
        assert abs((r.x0 + r.x1) / 2 - expect_x) < 1.0
        assert abs((r.y0 + r.y1) / 2 - expect_y) < 1.0
        assert abs(r.width - expect_w) < 2.0
        assert abs(r.height - expect_h) < 2.0
    finally:
        doc.close()


def test_watermark_text_box_shared_with_preview() -> None:
    """Preview and apply share watermark_text_box for size."""
    w, h, fs = ops.watermark_text_box(
        "CONFIDENTIAL",
        page_width=400,
        page_height=400,
        diagonal_percent=50.0,
    )
    assert fs > 0
    assert abs(w - (400**2 + 400**2) ** 0.5 * 0.5) < 0.5
    assert h > fs  # visual height includes ascender+descender span


def test_page_numbers_present(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", pages=2)
    source_hash = _file_hash(src)
    out = tmp_path / "num.pdf"
    ops.add_page_numbers(str(src), str(out), template="Page {page}", start=1)
    assert _file_hash(src) == source_hash
    doc = fitz.open(str(out))
    try:
        assert "Page 1" in doc[0].get_text()
        assert "Page 2" in doc[1].get_text()
    finally:
        doc.close()


def test_crop_dims_cropbox_and_rebuild(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", width=400, height=400)
    source_hash = _file_hash(src)
    soft = tmp_path / "soft.pdf"
    ops.crop_pdf(str(src), str(soft), left=20, right=20, top=10, bottom=10, mode="cropbox")
    assert _file_hash(src) == source_hash
    doc = fitz.open(str(soft))
    try:
        assert abs(doc[0].cropbox.width - 360) < 0.5
        assert abs(doc[0].cropbox.height - 380) < 0.5
    finally:
        doc.close()

    hard = tmp_path / "hard.pdf"
    ops.crop_pdf(str(src), str(hard), left=50, right=50, top=50, bottom=50, mode="rebuild")
    doc = fitz.open(str(hard))
    try:
        assert abs(doc[0].rect.width - 300) < 0.5
        assert abs(doc[0].rect.height - 300) < 0.5
    finally:
        doc.close()


def test_bookmark_round_trip_and_toc(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", pages=2)
    source_hash = _file_hash(src)
    marked = tmp_path / "marked.pdf"
    ops.set_bookmarks(
        str(src),
        str(marked),
        [ops.BookmarkEntry(1, "First", 1), ops.BookmarkEntry(1, "Second", 2)],
    )
    assert _file_hash(src) == source_hash
    bookmarks = ops.get_bookmarks(str(marked))
    assert [(b.title, b.page) for b in bookmarks] == [("First", 1), ("Second", 2)]

    toc = tmp_path / "toc.pdf"
    ops.generate_toc_page(str(marked), str(toc))
    doc = fitz.open(str(toc))
    try:
        assert doc.page_count == 3
        titles = [row[1] for row in doc.get_toc()]
        assert "First" in titles
        assert "Table of contents" in doc[0].get_text()
    finally:
        doc.close()


def test_blank_heuristic_on_empty_page(tmp_path: Path) -> None:
    path = tmp_path / "mixed.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), "content", fontsize=14)
        doc.save(str(path))
    finally:
        doc.close()

    report = ops.detect_blank_pages(str(path))
    assert report.blank_indices == (0,)
    assert report.page_count == 2

    source_hash = _file_hash(path)
    out = tmp_path / "clean.pdf"
    ops.remove_blank_pages(str(path), str(out))
    assert _file_hash(path) == source_hash
    cleaned = fitz.open(str(out))
    try:
        assert cleaned.page_count == 1
        assert "content" in cleaned[0].get_text()
    finally:
        cleaned.close()


def test_header_footer_and_bates_across_files(tmp_path: Path) -> None:
    a = _make_pdf(tmp_path / "a.pdf", text="A")
    b = _make_pdf(tmp_path / "b.pdf", pages=2, text="B")
    out_dir = tmp_path / "bates"
    written = ops.add_bates_across_files(
        [str(a), str(b)], out_dir, prefix="EX-", start=1, digits=4
    )
    assert len(written) == 2
    da = fitz.open(str(written[0]))
    try:
        assert "EX-0001" in da[0].get_text()
    finally:
        da.close()
    db = fitz.open(str(written[1]))
    try:
        assert "EX-0002" in db[0].get_text()
        assert "EX-0003" in db[1].get_text()
    finally:
        db.close()

    hf = tmp_path / "hf.pdf"
    ops.add_header_footer(str(a), str(hf), header="H {page}", footer="F {total}")
    doc = fitz.open(str(hf))
    try:
        text = doc[0].get_text()
        assert "H 1" in text
        assert "F 1" in text
    finally:
        doc.close()


def test_remove_annotations_and_color_effects(tmp_path: Path) -> None:
    src = tmp_path / "annot.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), "note", fontsize=14)
        page.add_highlight_annot(fitz.Rect(10, 20, 80, 50))
        doc.save(str(src))
    finally:
        doc.close()
    source_hash = _file_hash(src)
    out = tmp_path / "clean.pdf"
    ops.remove_or_flatten_annotations(str(src), str(out), action="remove")
    assert _file_hash(src) == source_hash
    cleaned = fitz.open(str(out))
    try:
        assert list(cleaned[0].annots() or []) == []
        assert "note" in cleaned[0].get_text()
    finally:
        cleaned.close()

    grey = tmp_path / "grey.pdf"
    ops.apply_color_effect(str(src), str(grey), effect="greyscale")
    assert Path(grey).is_file()
    assert ops.RASTER_EFFECT_WARNING
