"""Phase 2 unit tests — PdfLoader."""

from __future__ import annotations

import pytest

from pagedrop.core.pdf_loader import PdfCorruptError, PdfLoader, PdfNotFoundError


def test_page_count(five_page_pdf):
    loader = PdfLoader(str(five_page_pdf))
    try:
        assert loader.page_count == 5
    finally:
        loader.close()


def test_render_page_returns_png(one_page_pdf):
    loader = PdfLoader(str(one_page_pdf))
    try:
        png = loader.render_page(0)
        assert png[:4] == b"\x89PNG"
    finally:
        loader.close()


def test_render_last_page(five_page_pdf):
    loader = PdfLoader(str(five_page_pdf))
    try:
        png = loader.render_page(-1)
        assert png[:4] == b"\x89PNG"
    finally:
        loader.close()


def test_invalid_path_raises(tmp_path):
    missing = tmp_path / "does_not_exist.pdf"
    with pytest.raises(PdfNotFoundError, match="PDF not found"):
        PdfLoader(str(missing))


def test_close_idempotent(one_page_pdf):
    loader = PdfLoader(str(one_page_pdf))
    loader.close()
    loader.close()


def test_empty_file_raises_corrupt_error(empty_pdf):
    with pytest.raises(PdfCorruptError):
        PdfLoader(str(empty_pdf))
