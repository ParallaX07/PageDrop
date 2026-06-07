"""Phase 8 core tests — render safety limits."""

from __future__ import annotations

import fitz

from pagedrop.core.pdf_loader import MAX_RENDER_DPI, MAX_RENDER_WIDTH_PX, render_page_png


def test_render_caps_large_page_width():
    doc = fitz.open()
    # A0 landscape width in points (~3370 pt)
    page = doc.new_page(width=3370, height=2384)
    try:
        png = render_page_png(doc, 0, width_px=4096)
        assert png[:4] == b"\x89PNG"
        pix = fitz.Pixmap(png)
        try:
            effective_dpi = pix.width / (page.rect.width / 72.0)
            assert effective_dpi <= MAX_RENDER_DPI + 0.1
            assert pix.width <= MAX_RENDER_WIDTH_PX
        finally:
            pix = None
    finally:
        doc.close()
