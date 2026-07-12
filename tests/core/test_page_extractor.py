"""Phase 6 unit tests — page extractor."""

from __future__ import annotations

from pathlib import Path

import fitz

from pagedrop.core.page_extractor import extract_pages_to_files


def _page_size(path: Path | str, page_index: int = 0) -> tuple[float, float]:
    doc = fitz.open(str(path))
    try:
        rect = doc[page_index].rect
        return (float(rect.width), float(rect.height))
    finally:
        doc.close()


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
    doc = fitz.open(str(paths[0]))
    try:
        assert doc.page_count == 1
    finally:
        doc.close()


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

    for path, index in zip(paths, sorted(indices), strict=True):
        extracted = fitz.open(str(path))
        try:
            assert extracted.page_count == 1
            assert _page_size(path) == _page_size(source, index)
        finally:
            extracted.close()


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

    for path, index in zip(paths, sorted(indices), strict=True):
        extracted = fitz.open(str(path))
        try:
            assert extracted.page_count == 1
            assert _page_size(path) == _page_size(five_page_pdf, index)
        finally:
            extracted.close()
