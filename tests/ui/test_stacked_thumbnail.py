"""Tests for stacked PDF thumbnail rendering."""

from __future__ import annotations

from pagedrop.ui.stacked_thumbnail import (
    MAX_STACK_PAGES,
    build_stacked_pixmap,
    render_stacked_pdf_thumbnail,
)
from tests.fixtures.generate_fixtures import generate_n_page


def test_build_stacked_pixmap_single_page(one_page_pdf):
    pixmap = render_stacked_pdf_thumbnail(str(one_page_pdf), 1)
    assert not pixmap.isNull()
    assert pixmap.width() > 0
    assert pixmap.height() > 0


def test_render_stacked_pdf_thumbnail_uses_page_count(one_page_pdf, five_page_pdf):
    one = render_stacked_pdf_thumbnail(str(one_page_pdf), 1)
    five = render_stacked_pdf_thumbnail(str(five_page_pdf), 5)

    assert not one.isNull()
    assert not five.isNull()
    assert one.width() < five.width()
    assert one.height() < five.height()


def test_render_stacked_pdf_thumbnail_caps_at_three_pages(tmp_path):
    pdf = tmp_path / "many.pdf"
    generate_n_page(pdf, 10)
    pixmap = render_stacked_pdf_thumbnail(str(pdf), 10)
    assert not pixmap.isNull()

    three = render_stacked_pdf_thumbnail(str(pdf), MAX_STACK_PAGES)
    assert pixmap.width() == three.width()
    assert pixmap.height() == three.height()


def test_build_stacked_pixmap_empty():
    assert build_stacked_pixmap([]).isNull()
