"""Phase 8 core tests — PDF loader error paths."""

from __future__ import annotations

import fitz
import pytest

from pagedrop.core.pdf_loader import (
    PdfCorruptError,
    PdfEmptyError,
    PdfLoader,
    PdfPasswordError,
    PdfPasswordRequiredError,
)


def test_corrupt_file_raises_clear_error(corrupt_pdf):
    with pytest.raises(PdfCorruptError, match="corrupt|invalid"):
        PdfLoader(str(corrupt_pdf))


def test_garbage_file_raises_clear_error(garbage_pdf):
    with pytest.raises(PdfCorruptError, match="corrupt|invalid"):
        PdfLoader(str(garbage_pdf))


def test_empty_pdf_zero_pages(empty_pdf):
    with pytest.raises(PdfEmptyError, match="no pages"):
        PdfLoader(str(empty_pdf))


def test_password_required_and_incorrect(tmp_path):
    path = tmp_path / "locked.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="secret",
            owner_pw="owner",
        )
    finally:
        doc.close()

    with pytest.raises(PdfPasswordRequiredError, match="password-protected"):
        PdfLoader(str(path))

    with pytest.raises(PdfPasswordError, match="Incorrect password"):
        PdfLoader(str(path), password="wrong")

    loader = PdfLoader(str(path), password="secret")
    try:
        assert loader.page_count == 1
    finally:
        loader.close()
