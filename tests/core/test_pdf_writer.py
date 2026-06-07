"""Phase 15 unit tests — PDF writer."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from pagedrop.core.pdf_editor import PageRef, PdfEditModel
import pytest

from pagedrop.core.pdf_writer import merge_pdf_files, write_pdf


def _write_distinct_pdf(path: Path, widths: list[int]) -> None:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


def _page_width(reader: PdfReader, page_index: int) -> float:
    return float(reader.pages[page_index].mediabox.width)


def test_write_preserves_page_order(five_page_pdf, tmp_path):
    model = PdfEditModel(str(five_page_pdf), 5)
    output = tmp_path / "out.pdf"

    write_pdf(model, str(output))

    reader = PdfReader(str(output))
    source = PdfReader(str(five_page_pdf))
    assert len(reader.pages) == 5
    for index in range(5):
        assert _page_width(reader, index) == _page_width(source, index)


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

    reader = PdfReader(str(output))
    assert len(reader.pages) == 6
    assert [_page_width(reader, i) for i in range(6)] == [200, 300, 600, 700, 400, 500]


def test_write_multi_source_refs(tmp_path):
    doc_a = tmp_path / "a.pdf"
    doc_b = tmp_path / "b.pdf"
    _write_distinct_pdf(doc_a, [111, 222, 333])
    _write_distinct_pdf(doc_b, [444, 555])

    model = PdfEditModel(str(doc_a), 3)
    model.insert_pages(1, [PageRef(str(doc_b), 0), PageRef(str(doc_b), 1)])

    output = tmp_path / "merged.pdf"
    write_pdf(model, str(output))

    reader = PdfReader(str(output))
    assert len(reader.pages) == 5
    assert [_page_width(reader, i) for i in range(5)] == [111, 444, 555, 222, 333]


def test_merge_pdf_files_preserves_file_order(tmp_path):
    doc_a = tmp_path / "a.pdf"
    doc_b = tmp_path / "b.pdf"
    _write_distinct_pdf(doc_a, [100, 200])
    _write_distinct_pdf(doc_b, [300, 400, 500])

    output = tmp_path / "merged.pdf"
    merge_pdf_files([str(doc_a), str(doc_b)], str(output))

    reader = PdfReader(str(output))
    assert [_page_width(reader, i) for i in range(5)] == [100, 200, 300, 400, 500]


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

    reader = PdfReader(str(output))
    assert len(reader.pages) == 3
