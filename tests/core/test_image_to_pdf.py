"""Phase 19 unit tests — image to PDF conversion."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from pypdf import PdfReader

from pagedrop.core.image_to_pdf import (
    ImageConvertError,
    images_to_individual_pdfs,
    images_to_single_pdf,
)


def _write_test_image(path: Path, width: int, height: int) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=width, height=height)
        page.draw_rect(
            fitz.Rect(0, 0, width, height),
            color=(0.4, 0.4, 0.4),
            fill=(0.4, 0.4, 0.4),
        )
        pix = page.get_pixmap()
        pix.save(str(path))
    finally:
        doc.close()


def _page_width(reader: PdfReader, page_index: int) -> float:
    return float(reader.pages[page_index].mediabox.width)


def test_images_to_single_pdf_page_order(tmp_path):
    images = []
    widths = [111, 222, 333]
    for index, width in enumerate(widths):
        path = tmp_path / f"page_{index}.png"
        _write_test_image(path, width, 200)
        images.append(str(path))

    forward_out = tmp_path / "forward.pdf"
    reverse_out = tmp_path / "reverse.pdf"
    images_to_single_pdf(images, str(forward_out))
    images_to_single_pdf(list(reversed(images)), str(reverse_out))

    forward_widths = [_page_width(PdfReader(str(forward_out)), i) for i in range(3)]
    reverse_widths = [_page_width(PdfReader(str(reverse_out)), i) for i in range(3)]

    assert len(forward_widths) == len(widths)
    assert forward_widths == list(reversed(reverse_widths))
    assert forward_widths[0] < forward_widths[1] < forward_widths[2]


def test_individual_pdfs_writes_one_file_per_image(tmp_path):
    png = tmp_path / "alpha.png"
    jpeg = tmp_path / "bravo.jpg"
    _write_test_image(png, 100, 100)
    _write_test_image(jpeg, 150, 150)

    out_dir = tmp_path / "out"
    written = images_to_individual_pdfs([str(png), str(jpeg)], str(out_dir))

    assert len(written) == 2
    assert {Path(path).name for path in written} == {"alpha.pdf", "bravo.pdf"}
    for path in written:
        reader = PdfReader(path)
        assert len(reader.pages) == 1


def test_rejects_empty_list(tmp_path):
    output = tmp_path / "empty.pdf"
    with pytest.raises(ImageConvertError, match="No images to convert"):
        images_to_single_pdf([], str(output))

    with pytest.raises(ImageConvertError, match="No images to convert"):
        images_to_individual_pdfs([], str(tmp_path / "out"))


def test_collision_suffix_on_duplicate_stem(tmp_path):
    first = tmp_path / "photo.png"
    second = tmp_path / "photo.jpg"
    _write_test_image(first, 100, 100)
    _write_test_image(second, 120, 120)

    out_dir = tmp_path / "out"
    written = images_to_individual_pdfs([str(first), str(second)], str(out_dir))

    assert [Path(path).name for path in written] == ["photo.pdf", "photo_2.pdf"]


def test_corrupt_image_raises(tmp_path):
    corrupt = tmp_path / "broken.png"
    corrupt.write_text("not an image", encoding="utf-8")

    output = tmp_path / "out.pdf"
    with pytest.raises(ImageConvertError, match="Could not read image"):
        images_to_single_pdf([str(corrupt)], str(output))
