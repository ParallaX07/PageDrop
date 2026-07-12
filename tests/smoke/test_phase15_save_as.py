"""Phase 15 smoke tests — edit workflow, Save As, original file unchanged."""

from __future__ import annotations

from PyQt6.QtWidgets import QFileDialog
import fitz

from pagedrop.ui.main_window import MainWindow
from tests.conftest import wait_for_pdf_loaded
from tests.fixtures.generate_fixtures import generate_n_page


def _page_count(path) -> int:
    doc = fitz.open(str(path))
    try:
        return doc.page_count
    finally:
        doc.close()


def test_smoke_edit_save_as_preserves_original(
    qtbot, five_page_pdf, tmp_path, monkeypatch
):
    original_bytes = five_page_pdf.read_bytes()
    insert_pdf = tmp_path / "insert.pdf"
    generate_n_page(insert_pdf, 3)
    output = tmp_path / "edited_output.pdf"

    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    tab = window._tab_manager.active_tab
    assert tab is not None
    grid = tab.thumbnail_grid

    assert grid.insert_pdf_pages([str(insert_pdf)], drop_index=2)
    grid.selection_manager.select_single(0)
    assert tab.delete_selected_pages()
    grid.selection_manager.select_single(1)
    window._move_up_action.trigger()

    model = tab.edit_model
    assert model is not None
    assert model.logical_count() == 7
    assert tab.is_dirty

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF Files (*.pdf)"),
    )

    assert window._save_as(tab) is True
    assert not tab.is_dirty

    assert _page_count(output) == model.logical_count()
    assert five_page_pdf.read_bytes() == original_bytes
