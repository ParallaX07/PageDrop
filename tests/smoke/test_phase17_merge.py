"""Phase 17 smoke tests — merge PDFs workflow."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtWidgets import QFileDialog

from pagedrop.ui.merge_window import MergeWindow


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
    qtbot.waitUntil(lambda: not window._merging, timeout=10000)

    expected_widths = [444, 555, 666, 111, 222, 333]
    assert [_page_width(output, index) for index in range(len(expected_widths))] == expected_widths

    for path, data in original_bytes.items():
        assert Path(path).read_bytes() == data
