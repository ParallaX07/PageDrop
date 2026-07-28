"""Phase 15 unit tests — PDF writer."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_loader import PdfPasswordError, PdfPasswordRequiredError
from pagedrop.core.pdf_writer import merge_pdf_files, write_pdf
from tests.core.test_jobs import _encrypted_pdf


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_distinct_pdf(path: Path, widths: list[int]) -> None:
    doc = fitz.open()
    try:
        for width in widths:
            doc.new_page(width=width, height=200)
        doc.save(str(path))
    finally:
        doc.close()


def _page_width(path: Path | str, page_index: int) -> float:
    doc = fitz.open(str(path))
    try:
        return float(doc[page_index].rect.width)
    finally:
        doc.close()


def test_write_preserves_page_order(five_page_pdf, tmp_path):
    model = PdfEditModel(str(five_page_pdf), 5)
    output = tmp_path / "out.pdf"

    write_pdf(model, str(output))

    out = fitz.open(str(output))
    try:
        assert out.page_count == 5
        for index in range(5):
            assert _page_width(output, index) == _page_width(five_page_pdf, index)
    finally:
        out.close()


def test_write_after_reorder_delete_insert(tmp_path):
    primary = tmp_path / "primary.pdf"
    insert = tmp_path / "insert.pdf"
    _write_distinct_pdf(primary, [100, 200, 300, 400, 500])
    _write_distinct_pdf(insert, [600, 700])

    model = PdfEditModel(str(primary), 5)
    model.insert_pages(2, [PageRef(str(insert), 0), PageRef(str(insert), 1)])
    model.remove_pages([0])
    model.move_pages([3], 1)

    output = tmp_path / "edited.pdf"
    write_pdf(model, str(output))

    assert [_page_width(output, i) for i in range(6)] == [200, 300, 600, 700, 400, 500]


def test_write_multi_source_refs(tmp_path):
    doc_a = tmp_path / "a.pdf"
    doc_b = tmp_path / "b.pdf"
    _write_distinct_pdf(doc_a, [111, 222, 333])
    _write_distinct_pdf(doc_b, [444, 555])

    model = PdfEditModel(str(doc_a), 3)
    model.insert_pages(1, [PageRef(str(doc_b), 0), PageRef(str(doc_b), 1)])

    output = tmp_path / "merged.pdf"
    write_pdf(model, str(output))

    assert [_page_width(output, i) for i in range(5)] == [111, 444, 555, 222, 333]


def test_merge_pdf_files_preserves_file_order(tmp_path):
    doc_a = tmp_path / "a.pdf"
    doc_b = tmp_path / "b.pdf"
    _write_distinct_pdf(doc_a, [100, 200])
    _write_distinct_pdf(doc_b, [300, 400, 500])

    output = tmp_path / "merged.pdf"
    merge_pdf_files([str(doc_a), str(doc_b)], str(output))

    assert [_page_width(output, i) for i in range(5)] == [100, 200, 300, 400, 500]


def test_merge_pdf_files_rejects_empty_list(tmp_path):
    with pytest.raises(ValueError, match="No PDF files to merge"):
        merge_pdf_files([], str(tmp_path / "out.pdf"))


def test_merge_pdf_files_total_page_count(tmp_path):
    doc_a = tmp_path / "a.pdf"
    doc_b = tmp_path / "b.pdf"
    _write_distinct_pdf(doc_a, [100])
    _write_distinct_pdf(doc_b, [200, 300])

    output = tmp_path / "merged.pdf"
    merge_pdf_files([str(doc_a), str(doc_b)], str(output))

    doc = fitz.open(str(output))
    try:
        assert doc.page_count == 3
    finally:
        doc.close()


def test_write_applies_page_rotation(five_page_pdf, tmp_path):
    model = PdfEditModel(str(five_page_pdf), 5)
    model.rotate_pages([1], 90)
    model.rotate_pages([2], 180)

    output = tmp_path / "rotated.pdf"
    write_pdf(model, str(output))

    out = fitz.open(str(output))
    try:
        assert out[0].rotation == 0
        assert out[1].rotation == 90
        assert out[2].rotation == 180
        assert out[3].rotation == 0
    finally:
        out.close()


def test_write_encrypted_with_password_leaves_source_unchanged(tmp_path):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = _file_hash(enc)

    model = PdfEditModel(str(enc), 1)
    output = tmp_path / "unlocked_copy.pdf"
    write_pdf(model, str(output), passwords={str(enc): "secret"})

    assert _file_hash(enc) == source_hash
    assert output.resolve() != enc.resolve()
    out = fitz.open(str(output))
    try:
        assert out.page_count == 1
        assert not out.needs_pass
    finally:
        out.close()


def test_write_encrypted_without_password_fails_clearly(tmp_path):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = _file_hash(enc)

    model = PdfEditModel(str(enc), 1)
    output = tmp_path / "out.pdf"
    with pytest.raises(PdfPasswordRequiredError, match="password-protected"):
        write_pdf(model, str(output))

    assert _file_hash(enc) == source_hash
    assert not output.exists()


def test_write_encrypted_wrong_password_fails_clearly(tmp_path):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = _file_hash(enc)

    model = PdfEditModel(str(enc), 1)
    output = tmp_path / "out.pdf"
    with pytest.raises(PdfPasswordError, match="Incorrect password"):
        write_pdf(model, str(output), passwords={str(enc): "wrong"})

    assert _file_hash(enc) == source_hash
    assert not output.exists()
