"""Phase 8 core tests — render safety limits."""

from __future__ import annotations

import fitz

from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX, render_page_png


def test_render_caps_large_page_width():
    doc = fitz.open()
    # A0 landscape width in points (~3370 pt)
    page = doc.new_page(width=3370, height=2384)
    try:
        png = render_page_png(doc, 0, width_px=4096)
        assert png[:4] == b"\x89PNG"
        pix = fitz.Pixmap(png)
        try:
            assert pix.width <= MAX_RENDER_WIDTH_PX
            # Requested width is honored up to the hard pixel cap (no 150 DPI clamp).
            assert pix.width == MAX_RENDER_WIDTH_PX
        finally:
            pix = None
    finally:
        doc.close()


def test_render_honors_requested_width_for_letter():
    doc = fitz.open()
    doc.new_page(width=612, height=792)
    try:
        png = render_page_png(doc, 0, width_px=1600)
        pix = fitz.Pixmap(png)
        try:
            assert abs(pix.width - 1600) <= 1
        finally:
            pix = None
    finally:
        doc.close()
