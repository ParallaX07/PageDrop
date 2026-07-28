"""pdf_tools overwrite guards share jobs.paths.reject_source_overwrite."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import fitz
import pytest

from pagedrop.core import pdf_tools
from pagedrop.core.jobs.errors import SourceOverwriteError


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), "src", fontsize=14)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_reverse_rejects_same_path(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "in.pdf")
    source_hash = _file_hash(src)
    with pytest.raises(SourceOverwriteError):
        pdf_tools.reverse_pdf_pages(str(src), str(src))
    assert _file_hash(src) == source_hash


def test_reverse_rejects_hardlink_alias(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "in.pdf")
    alias = tmp_path / "alias.pdf"
    try:
        os.link(src, alias)
    except OSError:
        pytest.skip("filesystem does not support hardlinks")
    source_hash = _file_hash(src)
    with pytest.raises(SourceOverwriteError):
        pdf_tools.reverse_pdf_pages(str(src), str(alias))
    assert _file_hash(src) == source_hash


def test_alternate_and_zip_reject_source_output(tmp_path: Path) -> None:
    a = _make_pdf(tmp_path / "a.pdf")
    b = _make_pdf(tmp_path / "b.pdf")
    with pytest.raises(SourceOverwriteError):
        pdf_tools.alternate_pdfs(str(a), str(b), str(a))
    with pytest.raises(SourceOverwriteError):
        pdf_tools.zip_pdfs([a, b], a)
