"""Phase 6 unit tests — page extractor."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from pagedrop.core.page_extractor import extract_pages_to_files


def _mediabox(reader: PdfReader, page_index: int) -> tuple[float, float, float, float]:
    box = reader.pages[page_index].mediabox
    return (float(box.left), float(box.bottom), float(box.right), float(box.top))


def test_extract_single_page(one_page_pdf, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    paths = extract_pages_to_files(
        str(one_page_pdf),
        [0],
        output_dir,
        "report",
    )

    assert len(paths) == 1
    assert paths[0].name == "report_page_0001.pdf"
    reader = PdfReader(paths[0])
    assert len(reader.pages) == 1


def test_extract_multiple_non_contiguous(pdf_fixtures_dir, tmp_path):
    source = pdf_fixtures_dir / "ten_page.pdf"
    if not source.exists():
        from tests.fixtures.generate_fixtures import generate_n_page

        generate_n_page(source, 10)

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    indices = [0, 3, 6]
    paths = extract_pages_to_files(str(source), indices, output_dir, "doc")

    assert len(paths) == 3
    assert [path.name for path in paths] == [
        "doc_page_0001.pdf",
        "doc_page_0004.pdf",
        "doc_page_0007.pdf",
    ]

    source_reader = PdfReader(str(source))
    for path, index in zip(paths, sorted(indices), strict=True):
        extracted = PdfReader(path)
        assert len(extracted.pages) == 1
        assert _mediabox(extracted, 0) == _mediabox(source_reader, index)


def test_filename_zero_padding(pdf_fixtures_dir, tmp_path):
    source = pdf_fixtures_dir / "ten_page.pdf"
    if not source.exists():
        from tests.fixtures.generate_fixtures import generate_n_page

        generate_n_page(source, 10)

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    paths = extract_pages_to_files(
        str(source),
        [2, 9],
        output_dir,
        "report",
    )

    names = [path.name for path in paths]
    assert names == ["report_page_0003.pdf", "report_page_0010.pdf"]
    assert names == sorted(names)


def test_extracted_content_matches_source(five_page_pdf, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    indices = [1, 4]
    paths = extract_pages_to_files(
        str(five_page_pdf),
        indices,
        output_dir,
        "report",
    )

    source_reader = PdfReader(str(five_page_pdf))
    for path, index in zip(paths, sorted(indices), strict=True):
        extracted = PdfReader(path)
        assert len(extracted.pages) == 1
        assert _mediabox(extracted, 0) == _mediabox(source_reader, index)
