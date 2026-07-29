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


def test_merge_encrypted_with_passwords_leaves_sources_unchanged(tmp_path):
    enc_a = tmp_path / "a.pdf"
    enc_b = tmp_path / "b.pdf"
    _encrypted_pdf(enc_a, password="alpha")
    _encrypted_pdf(enc_b, password="beta")
    hash_a = _file_hash(enc_a)
    hash_b = _file_hash(enc_b)

    output = tmp_path / "merged.pdf"
    merge_pdf_files(
        [str(enc_a), str(enc_b)],
        str(output),
        passwords={str(enc_a): "alpha", str(enc_b): "beta"},
    )

    assert output.is_file()
    assert _file_hash(enc_a) == hash_a
    assert _file_hash(enc_b) == hash_b
    doc = fitz.open(str(output))
    try:
        assert doc.page_count == 2
        assert not doc.needs_pass
    finally:
        doc.close()


def test_merge_encrypted_without_password_fails_clearly(tmp_path):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = _file_hash(enc)
    output = tmp_path / "out.pdf"
    with pytest.raises(PdfPasswordRequiredError, match="password-protected"):
        merge_pdf_files([str(enc)], str(output))
    assert _file_hash(enc) == source_hash
    assert not output.exists()


def test_write_batches_contiguous_same_source(tmp_path, monkeypatch):
    source = tmp_path / "hundred.pdf"
    widths = list(range(100, 200))
    _write_distinct_pdf(source, widths)
    model = PdfEditModel(str(source), 100)

    insert_calls: list[tuple[int | None, int | None]] = []
    real_insert = fitz.Document.insert_pdf

    def _spy(self, docsrc, *args, **kwargs):
        insert_calls.append((kwargs.get("from_page"), kwargs.get("to_page")))
        return real_insert(self, docsrc, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "insert_pdf", _spy)

    output = tmp_path / "out.pdf"
    write_pdf(model, str(output))

    assert insert_calls == [(0, 99)]
    assert [_page_width(output, i) for i in range(100)] == [float(w) for w in widths]


def test_write_batches_break_on_source_gap_and_rotation(tmp_path, monkeypatch):
    doc_a = tmp_path / "a.pdf"
    doc_b = tmp_path / "b.pdf"
    _write_distinct_pdf(doc_a, [110, 120, 130, 140])
    _write_distinct_pdf(doc_b, [210, 220])

    # A0,A1 | B0,B1 | A2,A3(rotated) — three contiguous runs, four insert calls
    # because A2/A3 are contiguous in source but split from A0/A1 by B.
    pages = [
        PageRef(str(doc_a), 0),
        PageRef(str(doc_a), 1),
        PageRef(str(doc_b), 0),
        PageRef(str(doc_b), 1),
        PageRef(str(doc_a), 2, rotation=90),
        PageRef(str(doc_a), 3, rotation=180),
    ]
    model = PdfEditModel.with_pages(str(doc_a), pages)

    insert_calls: list[tuple[int | None, int | None]] = []
    real_insert = fitz.Document.insert_pdf

    def _spy(self, docsrc, *args, **kwargs):
        insert_calls.append((kwargs.get("from_page"), kwargs.get("to_page")))
        return real_insert(self, docsrc, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "insert_pdf", _spy)

    output = tmp_path / "out.pdf"
    write_pdf(model, str(output))

    assert insert_calls == [(0, 1), (0, 1), (2, 3)]
    assert [_page_width(output, i) for i in range(4)] == [110.0, 120.0, 210.0, 220.0]
    out = fitz.open(str(output))
    try:
        assert out.page_count == 6
        assert out[4].rotation == 90
        assert out[5].rotation == 180
        # mediabox keeps source page size; visible rect swaps under 90° rotation
        assert float(out[4].mediabox.width) == 130.0
        assert float(out[5].mediabox.width) == 140.0
    finally:
        out.close()
