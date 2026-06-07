"""Phase 17 UI tests — Merge PDFs window."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog

from pagedrop.ui.merge_window import MergeWindow
from tests.fixtures.generate_fixtures import generate_n_page


def _merge_window(qtbot) -> MergeWindow:
    window = MergeWindow()
    qtbot.addWidget(window)
    return window


def test_add_files_populates_grid_with_filenames(qtbot, one_page_pdf, five_page_pdf):
    window = _merge_window(qtbot)
    window._add_paths([str(one_page_pdf), str(five_page_pdf)])

    assert window._model.file_count() == 2
    assert len(window._file_grid._cards) == 2
    names = [Path(path).name for path in window._file_grid.ordered_paths]
    assert one_page_pdf.name in names[0]
    assert five_page_pdf.name in names[1]


def test_remove_and_reorder_updates_model(qtbot, one_page_pdf, five_page_pdf, tmp_path):
    third = tmp_path / "third.pdf"
    generate_n_page(third, 2)

    window = _merge_window(qtbot)
    window._add_paths([str(one_page_pdf), str(five_page_pdf), str(third)])

    window._file_grid.selection_manager.select_single(1)
    window._remove_selected()
    assert window._model.file_count() == 2

    window._file_grid.selection_manager.select_single(1)
    window._move_up()

    names = [Path(path).name for path in window._model.all_paths()]
    assert names == [third.name, one_page_pdf.name]


def test_merge_disabled_when_empty(qtbot, one_page_pdf):
    window = _merge_window(qtbot)
    assert not window._merge_action.isEnabled()

    window._add_paths([str(one_page_pdf)])
    assert window._merge_action.isEnabled()


def test_merge_runs_in_background_without_blocking_ui(qtbot, one_page_pdf, five_page_pdf, tmp_path, monkeypatch):
    output = tmp_path / "merged.pdf"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF Files (*.pdf)"),
    )

    window = _merge_window(qtbot)
    window.show()
    qtbot.waitExposed(window, timeout=5000)
    window._add_paths([str(one_page_pdf), str(five_page_pdf)])

    window._merge_pdfs()
    assert window._merging
    assert window._busy_overlay.isVisible()

    qtbot.waitUntil(lambda: not window._merging, timeout=10000)
    assert output.is_file()
    assert not window._busy_overlay.isVisible()
    assert "Merged 2 files" in window.statusBar().currentMessage()


def test_double_click_enters_preview_stack(qtbot, one_page_pdf):
    window = _merge_window(qtbot)
    window.show()
    qtbot.waitExposed(window, timeout=5000)
    window._add_paths([str(one_page_pdf)])

    window._file_grid._on_card_double_clicked(0)

    qtbot.waitUntil(lambda: window._is_preview_visible(), timeout=5000)
    assert window._stack.currentWidget() is window._preview_widget
    assert window._preview_widget.current_page == 0


def test_escape_returns_to_grid_from_preview(qtbot, five_page_pdf):
    window = _merge_window(qtbot)
    window.show()
    qtbot.waitExposed(window, timeout=5000)
    window._add_paths([str(five_page_pdf)])

    window._open_preview(str(five_page_pdf.resolve()))
    qtbot.waitUntil(lambda: window._is_preview_visible(), timeout=5000)

    qtbot.keyClick(window._preview_widget, Qt.Key.Key_Escape)

    qtbot.waitUntil(lambda: not window._is_preview_visible(), timeout=5000)
    assert window._stack.currentWidget() is window._file_grid


def test_zoom_controls_resize_thumbnails(qtbot, one_page_pdf):
    window = _merge_window(qtbot)
    window._add_paths([str(one_page_pdf)])

    initial = window._file_grid.thumbnail_width_px
    window._file_grid.set_thumbnail_zoom(initial + 32)
    assert window._file_grid.thumbnail_width_px == initial + 32
    assert window._file_grid._cards[0].width() == initial + 32 + 16
