"""Tests for stacked PDF thumbnail rendering."""

from __future__ import annotations

from pagedrop.ui.stacked_thumbnail import (
    MAX_STACK_PAGES,
    MIN_STACK_OFFSET,
    build_stacked_pixmap,
    render_stacked_pdf_thumbnail,
    stack_thumbnail_layout,
)
from tests.fixtures.generate_fixtures import generate_n_page


def test_build_stacked_pixmap_single_page(one_page_pdf, qtbot):
    pixmap = render_stacked_pdf_thumbnail(str(one_page_pdf), 1)
    assert not pixmap.isNull()
    assert pixmap.width() > 0
    assert pixmap.height() > 0


def test_render_stacked_pdf_thumbnail_uses_page_count(
    one_page_pdf, five_page_pdf, qtbot
):
    target = 160
    one = render_stacked_pdf_thumbnail(str(one_page_pdf), 1, width_px=target)
    five = render_stacked_pdf_thumbnail(str(five_page_pdf), 5, width_px=target)

    assert not one.isNull()
    assert not five.isNull()
    assert one.width() == target
    assert five.width() == target
    assert five.height() >= one.height()


def test_stack_thumbnail_layout_fits_target_width():
    layers, stack_offset, page_width = stack_thumbnail_layout(160, 5)
    assert layers == MAX_STACK_PAGES
    assert stack_offset >= MIN_STACK_OFFSET
    assert page_width + stack_offset * (layers - 1) == 160


def test_render_stacked_pdf_thumbnail_caps_at_three_pages(tmp_path, qtbot):
    pdf = tmp_path / "many.pdf"
    generate_n_page(pdf, 10)
    pixmap = render_stacked_pdf_thumbnail(str(pdf), 10)
    assert not pixmap.isNull()

    three = render_stacked_pdf_thumbnail(str(pdf), MAX_STACK_PAGES)
    assert pixmap.width() == three.width()
    assert pixmap.height() == three.height()


def test_build_stacked_pixmap_empty(qtbot):
    assert build_stacked_pixmap([]).isNull()


def test_build_stacked_pixmap_puts_first_page_on_top(tmp_path, qtbot):
    import fitz

    pdf = tmp_path / "colored.pdf"
    doc = fitz.open()
    for color in [(1, 0, 0), (0, 1, 0), (0, 0, 1)]:
        page = doc.new_page(width=200, height=280)
        page.draw_rect(page.rect, color=color, fill=color)
    doc.save(str(pdf))
    doc.close()

    pixmap = render_stacked_pdf_thumbnail(str(pdf), 3, width_px=160)
    top_left = pixmap.toImage().pixelColor(20, 20)
    assert top_left.red() > 200
    assert top_left.green() < 50
    assert top_left.blue() < 50

    # Bottom-right corner belongs to the rearmost (blue) page peeking out.
    back_corner = pixmap.toImage().pixelColor(pixmap.width() - 8, pixmap.height() - 8)
    assert back_corner.blue() > 200


def test_render_stacked_page_pngs_hits_doc_cache(tmp_path, monkeypatch):
    """O16: stacked thumbs warm pdf_service LRU (no private open+close bypass)."""
    import fitz

    from pagedrop.core.pdf_service import invalidate_doc_cache
    from pagedrop.ui.stacked_thumbnail import render_stacked_page_pngs

    pdf = tmp_path / "stack-cache.pdf"
    generate_n_page(pdf, 5)
    path = str(pdf)

    open_calls = {"n": 0}
    real_open = fitz.open

    def counting_open(*args: object, **kwargs: object) -> fitz.Document:
        open_calls["n"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", counting_open)
    invalidate_doc_cache()

    first = render_stacked_page_pngs(path, 3, width_px=40)
    assert len(first) == 3
    assert open_calls["n"] == 1

    second = render_stacked_page_pngs(path, 3, width_px=40)
    assert len(second) == 3
    assert open_calls["n"] == 1


def test_stacked_border_follows_light_dark_theme(tmp_path, qtbot, isolated_settings):
    """O16: stack page borders use border_hover_qcolor (updates on theme toggle)."""
    from pagedrop.ui.settings import set_light_theme
    from pagedrop.ui.theme import BORDER_HOVER, border_hover_qcolor

    set_light_theme(True)
    light = border_hover_qcolor()
    assert light.name().upper() == "#9CA3AF"

    set_light_theme(False)
    dark = border_hover_qcolor()
    assert dark.name().upper() == BORDER_HOVER.upper()
    assert light != dark

    pdf = tmp_path / "border.pdf"
    generate_n_page(pdf, 1)

    set_light_theme(True)
    light_px = render_stacked_pdf_thumbnail(str(pdf), 1, width_px=80)
    set_light_theme(False)
    dark_px = render_stacked_pdf_thumbnail(str(pdf), 1, width_px=80)

    # Edge pixel samples the stroke (AA may blend; colors must still diverge).
    light_border = light_px.toImage().pixelColor(0, 0)
    dark_border = dark_px.toImage().pixelColor(0, 0)
    assert light_border != dark_border
    assert light_border.lightness() > dark_border.lightness()
