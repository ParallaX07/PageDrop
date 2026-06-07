"""Phase 17 smoke tests — merge PDFs workflow."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog
from pypdf import PdfReader, PdfWriter

from pagedrop.ui.merge_window import MergeWindow


def _write_distinct_pdf(path: Path, widths: list[int]) -> None:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


def _page_width(reader: PdfReader, page_index: int) -> float:
    return float(reader.pages[page_index].mediabox.width)


def test_smoke_merge_reorder_save_as(qtbot, tmp_path, monkeypatch):
    pdf_a = tmp_path / "alpha.pdf"
    pdf_b = tmp_path / "bravo.pdf"
    pdf_c = tmp_path / "charlie.pdf"
    _write_distinct_pdf(pdf_a, [111])
    _write_distinct_pdf(pdf_b, [222, 333])
    _write_distinct_pdf(pdf_c, [444, 555, 666])

    original_bytes = {
        str(pdf_a.resolve()): pdf_a.read_bytes(),
        str(pdf_b.resolve()): pdf_b.read_bytes(),
        str(pdf_c.resolve()): pdf_c.read_bytes(),
    }

    output = tmp_path / "merged_output.pdf"

    window = MergeWindow()
    qtbot.addWidget(window)
    window.showMinimized()

    window._add_paths([str(pdf_a), str(pdf_b), str(pdf_c)])
    assert window._model.file_count() == 3

    window._file_grid.selection_manager.select_single(2)
    window._move_up()

    window._file_grid.selection_manager.clear()
    window._file_grid.selection_manager.select_single(1)
    window._move_up()

    expected_order = [pdf_c, pdf_a, pdf_b]
    assert [Path(path).name for path in window._model.all_paths()] == [
        pdf.name for pdf in expected_order
    ]

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF Files (*.pdf)"),
    )

    window._merge_pdfs()

    merged = PdfReader(str(output))
    expected_widths = [444, 555, 666, 111, 222, 333]
    assert len(merged.pages) == len(expected_widths)
    assert [_page_width(merged, index) for index in range(len(expected_widths))] == expected_widths

    for path, data in original_bytes.items():
        assert Path(path).read_bytes() == data
