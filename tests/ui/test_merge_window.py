"""Phase 17 UI tests — Merge PDFs window."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt

from pagedrop.ui.merge_window import MergeWindow
from tests.fixtures.generate_fixtures import generate_n_page


def _merge_window(qtbot) -> MergeWindow:
    window = MergeWindow()
    qtbot.addWidget(window)
    return window


def test_add_files_populates_list_with_filenames(qtbot, one_page_pdf, five_page_pdf):
    window = _merge_window(qtbot)
    window._add_paths([str(one_page_pdf), str(five_page_pdf)])

    assert window._model.file_count() == 2
    assert window._list_widget.count() == 2
    assert one_page_pdf.name in window._list_widget.item(0).text()
    assert five_page_pdf.name in window._list_widget.item(1).text()


def test_remove_and_reorder_updates_model(qtbot, one_page_pdf, five_page_pdf, tmp_path):
    third = tmp_path / "third.pdf"
    generate_n_page(third, 2)

    window = _merge_window(qtbot)
    window._add_paths([str(one_page_pdf), str(five_page_pdf), str(third)])

    window._list_widget.item(1).setSelected(True)
    window._remove_selected()
    assert window._model.file_count() == 2

    window._list_widget.clearSelection()
    window._list_widget.item(1).setSelected(True)
    window._move_up()

    names = [Path(path).name for path in window._model.all_paths()]
    assert names == [third.name, one_page_pdf.name]


def test_merge_disabled_when_empty(qtbot, one_page_pdf):
    window = _merge_window(qtbot)
    assert not window._merge_action.isEnabled()

    window._add_paths([str(one_page_pdf)])
    assert window._merge_action.isEnabled()


def test_double_click_enters_preview_stack(qtbot, one_page_pdf):
    window = _merge_window(qtbot)
    window.show()
    qtbot.waitExposed(window, timeout=5000)
    window._add_paths([str(one_page_pdf)])

    item = window._list_widget.item(0)
    # Offscreen Qt does not reliably synthesize QListWidget double-clicks.
    window._list_widget.itemDoubleClicked.emit(item)

    qtbot.waitUntil(lambda: window._is_preview_visible(), timeout=5000)
    assert window._stack.currentWidget() is window._preview_widget
    assert window._preview_widget.current_page == 0


def test_escape_returns_to_list_from_preview(qtbot, five_page_pdf):
    window = _merge_window(qtbot)
    window.show()
    qtbot.waitExposed(window, timeout=5000)
    window._add_paths([str(five_page_pdf)])

    window._open_preview(str(five_page_pdf.resolve()))
    qtbot.waitUntil(lambda: window._is_preview_visible(), timeout=5000)

    qtbot.keyClick(window._preview_widget, Qt.Key.Key_Escape)

    qtbot.waitUntil(lambda: not window._is_preview_visible(), timeout=5000)
    assert window._stack.currentWidget() is window._list_widget
