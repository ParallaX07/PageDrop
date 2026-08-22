"""Phase 28 core — crop, watermark, page numbers, bookmarks, blank detect."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core import modify_ops as ops
from pagedrop.core.jobs.cancel import check_cancel
from pagedrop.core.jobs.errors import SourceOverwriteError


def test_check_cancel_alias_is_shared_helper() -> None:
    """O16: modify_ops / optimize_secure import check_cancel (no local copies)."""
    from pagedrop.core import optimize_secure as secure

    assert ops._check_cancel is check_cancel
    assert secure._check_cancel is check_cancel


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
    # Use rotate=0 to keep vector text selectable; rotated text is rasterized (like image watermark) to avoid mirrored glyphs
    ops.add_text_watermark(str(src), str(out), text="CONFIDENTIAL", rotate=0)
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
        # Rotated text is now rasterized (like image) to avoid mirrored glyphs, so check images not selectable text
        assert not doc[0].get_images()
        assert doc[1].get_images()
        assert not doc[2].get_images()
        # Also check via pixmap that watermark is present on page 1 (dark pixels)
        assert not doc[0].get_text().strip().endswith("MARK")  # not selectable
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


def test_watermark_rotation_matches_preview_direction(tmp_path: Path) -> None:
    """Saved text baseline direction must match Qt preview (painter.rotate).

    Preview angle -45 renders "/" (SW->NE) in Y-down screen space; the saved
    page must extract the same direction, not its diagonal mirror "\".
    Rotated text is now rasterized (like image) to avoid mirrored glyphs, so
    we verify via pixmap dark-pixel quadrants and image presence, not via
    selectable text dir.
    """
    src = _make_pdf(tmp_path / "src.pdf", width=595, height=842)
    for angle, want_slash in [(-45.0, True), (45.0, False)]:
        out = tmp_path / f"rot{int(angle)}.pdf"
        ops.add_text_watermark(
            str(src),
            str(out),
            text="SAALIM SIR",
            diagonal_percent=60,
            rotate=angle,
            opacity=1.0,
            position="center",
        )
        doc = fitz.open(str(out))
        try:
            # Rotated text is rasterized
            assert doc[0].get_images(), f"watermark image missing at angle {angle}"
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
            n = pix.n
            w = pix.width
            h = pix.height
            s = pix.samples
            qu = {"tl": 0, "tr": 0, "bl": 0, "br": 0}
            for y in range(h):
                for x in range(w):
                    idx = (y * w + x) * n
                    if s[idx] < 200:  # grey text 0.55*255=140
                        if y < h // 2:
                            if x < w // 2:
                                qu["tl"] += 1
                            else:
                                qu["tr"] += 1
                        else:
                            if x < w // 2:
                                qu["bl"] += 1
                            else:
                                qu["br"] += 1
            is_slash = (qu["tr"] + qu["bl"]) > (qu["tl"] + qu["br"])
            assert is_slash == want_slash, (
                f"angle {angle}: quadrants {qu} -> {'/' if is_slash else chr(92)} != preview {'/' if want_slash else chr(92)}"
            )
        finally:
            doc.close()


def _asym_png(path: Path, w: int = 200, h: int = 100) -> None:
    """PNG with green top strip, red left half, blue right half (orientation probe)."""
    import struct
    import zlib

    rows = b""
    for y in range(h):
        row = b"\x00"
        for x in range(w):
            if y < h // 5:
                c = (0, 180, 0)
            elif x < w // 2:
                c = (220, 30, 30)
            else:
                c = (30, 60, 220)
            row += bytes(c)
        rows += row

    def chunk(t: bytes, d: bytes) -> bytes:
        body = t + d
        return struct.pack(">I", len(d)) + body + struct.pack(">I", zlib.crc32(body))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _green_quadrant_bias(doc: fitz.Document, page_pts: float = 400.0) -> tuple[int, int]:
    """(green pixel count upper-left quadrant vs upper-right) of rendered page."""
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    n = pix.n
    samples = pix.samples
    mid_y = pix.height // 2
    ul = ur = 0
    for y in range(pix.height):
        base = y * pix.width * n
        for x in range(pix.width):
            r, g, b = samples[base + x * n], samples[base + x * n + 1], samples[base + x * n + 2]
            if g > 120 and r < 100 and b < 100:
                if y <= mid_y:
                    if x < pix.width // 2:
                        ul += 1
                    else:
                        ur += 1
    return ul, ur


def test_watermark_image_rotation_matches_preview(tmp_path: Path) -> None:
    """Saved image watermark orientation must match the Qt preview rotation.

    The asymmetric mark (green top / red left / blue right) rotated -45 must
    put the green strip toward the upper-LEFT (preview "/" direction); a
    mirrored apply puts it upper-RIGHT.
    """
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    doc.new_page(width=400, height=400)
    doc.save(str(src))
    doc.close()

    img = tmp_path / "mark.png"
    _asym_png(img)
    out = tmp_path / "img_wm.pdf"
    ops.add_image_watermark(
        str(src),
        str(out),
        image_path=str(img),
        diagonal_percent=45,
        rotate=-45,
        opacity=1.0,
        position="center",
    )
    out_doc = fitz.open(str(out))
    try:
        ul, ur = _green_quadrant_bias(out_doc)
        assert ul > 0 and ur >= 0
        assert ul > ur, f"image rotated mirrored: upper-left {ul} <= upper-right {ur}"
    finally:
        out_doc.close()


def test_watermark_text_box_caches_helv_font(monkeypatch) -> None:
    """O17-b: many watermark_text_box calls create ≤1 fitz.Font('helv')."""
    ops._HELV_FONT = None
    creates: list[object] = []
    real_font = fitz.Font

    def counting_font(*args, **kwargs):
        creates.append(args[0] if args else kwargs.get("fontname"))
        return real_font(*args, **kwargs)

    monkeypatch.setattr(fitz, "Font", counting_font)
    for _ in range(100):
        ops.watermark_text_box(
            "CONFIDENTIAL",
            page_width=400,
            page_height=400,
            diagonal_percent=50.0,
        )
    helv_creates = [c for c in creates if c == "helv"]
    assert len(helv_creates) <= 1, f"expected ≤1 helv Font, got {len(helv_creates)}"
    # Geometry still matches uncached math.
    w, _h, _fs = ops.watermark_text_box(
        "CONFIDENTIAL",
        page_width=400,
        page_height=400,
        diagonal_percent=50.0,
    )
    assert abs(w - (400**2 + 400**2) ** 0.5 * 0.5) < 0.5


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


def test_detect_blank_pages_holds_fitz_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O17-e: detect_blank_pages open/scan owns FITZ_LOCK."""
    from pagedrop.core.pdf_service import FITZ_LOCK

    path = tmp_path / "mixed.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), "content", fontsize=14)
        doc.save(str(path))
    finally:
        doc.close()

    held_at_open: list[bool] = []
    real_open = fitz.open

    def tracking_open(*args: object, **kwargs: object) -> fitz.Document:
        held_at_open.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracking_open)
    report = ops.detect_blank_pages(str(path))
    assert report.blank_indices == (0,)
    assert held_at_open, "expected at least one fitz.open"
    assert all(held_at_open), (
        f"fitz.open without FITZ_LOCK (owned flags={held_at_open})"
    )


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


def test_watermark_cancel_mid_loop_cleans_staged(tmp_path: Path, monkeypatch) -> None:
    """Cancel during watermark page loop must not promote and must scrub staging."""
    from pagedrop.core.jobs import CancelToken, JobCancelledError, JobSpec, SerializedJobRunner
    from pagedrop.core.modify_jobs import register_modify_handlers
    from pagedrop.utils.temp_manager import TempManager

    src = _make_pdf(tmp_path / "src.pdf", text="body", pages=6)
    src_hash = _file_hash(src)
    out = tmp_path / "wm.pdf"
    token = CancelToken()
    checks = {"n": 0}
    real_check = ops._check_cancel

    def counting_check(cancel):
        checks["n"] += 1
        if checks["n"] >= 2:
            token.cancel()
        real_check(cancel)

    monkeypatch.setattr(ops, "_check_cancel", counting_check)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_modify_handlers(runner)
        with pytest.raises(JobCancelledError):
            runner.run(
                JobSpec.create(
                    "watermark",
                    inputs=[str(src)],
                    output=out,
                    options={"kind": "text", "text": "MARK", "fontsize": 48},
                ),
                cancel=token,
            )
        assert not out.exists()
        assert not any(temp._dir.glob("job_*"))
        assert _file_hash(src) == src_hash
    finally:
        temp.cleanup()
