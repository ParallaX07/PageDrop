"""Phase 8 core tests — PDF loader error paths."""

from __future__ import annotations

import pytest

from pagedrop.core.pdf_loader import PdfCorruptError, PdfEmptyError, PdfLoader


def test_corrupt_file_raises_clear_error(corrupt_pdf):
    with pytest.raises(PdfCorruptError, match="corrupt|invalid"):
        PdfLoader(str(corrupt_pdf))


def test_garbage_file_raises_clear_error(garbage_pdf):
    with pytest.raises(PdfCorruptError, match="corrupt|invalid"):
        PdfLoader(str(garbage_pdf))


def test_empty_pdf_zero_pages(empty_pdf):
    with pytest.raises(PdfEmptyError, match="no pages"):
        PdfLoader(str(empty_pdf))
