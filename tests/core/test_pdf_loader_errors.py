"""Phase 8 core tests — PDF loader error paths."""

from __future__ import annotations

import pytest

from pagedrop.core.pdf_loader import (
    PdfCorruptError,
    PdfEmptyError,
    PdfLoadError,
    PdfLoader,
    PdfPasswordError,
    PdfPasswordRequiredError,
)
from tests.core.test_jobs import _encrypted_pdf


def test_corrupt_file_raises_clear_error(corrupt_pdf):
    with pytest.raises(PdfCorruptError, match="corrupt|invalid"):
        PdfLoader(str(corrupt_pdf))


def test_garbage_file_raises_clear_error(garbage_pdf):
    with pytest.raises(PdfCorruptError, match="corrupt|invalid"):
        PdfLoader(str(garbage_pdf))


def test_empty_pdf_zero_pages(empty_pdf):
    with pytest.raises(PdfEmptyError, match="no pages"):
        PdfLoader(str(empty_pdf))


def test_oserror_on_open_becomes_pdf_load_error(tmp_path, monkeypatch):
    path = tmp_path / "gone.pdf"
    path.write_bytes(b"%PDF-1.4")

    import fitz

    monkeypatch.setattr(fitz, "open", lambda *_a, **_k: (_ for _ in ()).throw(OSError(5, "I/O error")))

    with pytest.raises(PdfLoadError, match="drive disconnected|I/O error"):
        PdfLoader(str(path))


def test_oserror_on_is_file_becomes_pdf_load_error(tmp_path, monkeypatch):
    path = tmp_path / "remote.pdf"

    monkeypatch.setattr(
        "pagedrop.core.pdf_loader.Path.is_file",
        lambda self: (_ for _ in ()).throw(OSError(5, "Input/output error")),
    )

    with pytest.raises(PdfLoadError, match="drive disconnected|I/O error"):
        PdfLoader(str(path))


def test_password_required_and_incorrect(tmp_path):
    path = tmp_path / "locked.pdf"
    _encrypted_pdf(path, password="secret")

    with pytest.raises(PdfPasswordRequiredError, match="password-protected"):
        PdfLoader(str(path))

    with pytest.raises(PdfPasswordError, match="Incorrect password"):
        PdfLoader(str(path), password="wrong")

    loader = PdfLoader(str(path), password="secret")
    try:
        assert loader.page_count == 1
    finally:
        loader.close()
