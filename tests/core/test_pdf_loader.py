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


def test_empty_file_raises_corrupt_error(tmp_path):
    empty_bytes = tmp_path / "empty_bytes.pdf"
    empty_bytes.write_bytes(b"")
    with pytest.raises(PdfCorruptError, match="empty"):
        PdfLoader(str(empty_bytes))


@pytest.mark.parametrize("rotation", [90, 270])
def test_page_size_pt_is_unrotated_with_own_rotation(tmp_path, rotation):
    import fitz

    path = tmp_path / "rot.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=400)
        page.set_rotation(rotation)
        doc.save(str(path))
    finally:
        doc.close()

    loader = PdfLoader(str(path))
    try:
        assert loader.page_size_pt(0) == (200, 400)
        assert loader.page_rotation(0) == rotation
    finally:
        loader.close()
