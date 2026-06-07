"""Phase 13 UI tests — delete and arrow-button page reorder."""

from __future__ import annotations

from PyQt6.QtCore import Qt

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import wait_for_grid_loaded, wait_for_pdf_loaded


def _source_indices(tab: PdfTab) -> list[int]:
    model = tab.edit_model
    assert model is not None
    return [model.page_at(i).source_index for i in range(model.logical_count())]


def _card_labels(tab: PdfTab) -> list[str]:
    return [card._page_label.text() for card in tab.thumbnail_grid._cards]


def _load_tab(qtbot, pdf_path) -> PdfTab:
    tab = PdfTab(TempManager())
    qtbot.addWidget(tab)
    tab.resize(900, 650)
    tab.show()
    tab.load_pdf(str(pdf_path))
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)
    return tab


def test_delete_selected_pages(qtbot, five_page_pdf):
    tab = _load_tab(qtbot, five_page_pdf)
    grid = tab.thumbnail_grid

    grid.selection_manager.select_single(1)
    grid.selection_manager.toggle(3)
    assert tab.delete_selected_pages()

    assert tab.edit_model is not None
    assert tab.edit_model.logical_count() == 3
    assert _source_indices(tab) == [0, 2, 4]
    assert tab.is_dirty
    assert len(grid._cards) == 3
    assert grid.selection_manager.selection == set()


def test_delete_all_pages_shows_empty_state(qtbot, five_page_pdf):
    tab = _load_tab(qtbot, five_page_pdf)
    grid = tab.thumbnail_grid

    grid.selection_manager.select_all()
    assert tab.delete_selected_pages()

    assert tab.edit_model is not None
    assert tab.edit_model.logical_count() == 0
    assert len(grid._cards) == 0
    assert grid._empty_title.text() == "No pages in this document"
    assert tab.is_dirty


def test_move_up_down_buttons(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    tab = window._tab_manager.active_tab
    assert tab is not None
    grid = tab.thumbnail_grid
    cards = grid._cards

    qtbot.mouseClick(cards[2], Qt.MouseButton.LeftButton)
    assert window._move_up_action.isEnabled()

    window._move_up_action.trigger()
    qtbot.waitUntil(
        lambda: _source_indices(tab) == [0, 2, 1, 3, 4],
        timeout=5000,
    )
    assert grid.selection_manager.selection == {1}

    assert window._move_down_action.isEnabled()
    window._move_down_action.trigger()
    qtbot.waitUntil(
        lambda: _source_indices(tab) == [0, 1, 2, 3, 4],
        timeout=5000,
    )
    assert grid.selection_manager.selection == {2}
    assert tab.is_dirty
    window.close()


def test_labels_renumber_after_delete(qtbot, five_page_pdf):
    tab = _load_tab(qtbot, five_page_pdf)
    grid = tab.thumbnail_grid

    grid.selection_manager.select_single(1)
    assert tab.delete_selected_pages()

    assert _card_labels(tab) == [
        "Page 1",
        "Page 2",
        "Page 3",
        "Page 4",
    ]
    for index, card in enumerate(grid._cards):
        assert card.page_index == index
