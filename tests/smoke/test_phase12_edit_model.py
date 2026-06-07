"""Phase 12 smoke tests — PdfEditModel integration with grid and preview."""

from __future__ import annotations

from pagedrop.ui.main_window import MainWindow
from tests.conftest import RENDER_TIMEOUT_MS, wait_for_pdf_loaded


def test_smoke_edit_model_grid_preview_sync(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()

    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    tab = window._tab_manager.active_tab
    assert tab is not None
    model = tab.edit_model
    assert model is not None
    assert model.logical_count() == 5
    assert model.original_path == str(five_page_pdf)
    assert not model.is_dirty()

    grid = tab.thumbnail_grid
    assert len(grid._cards) == 5
    for index, card in enumerate(grid._cards):
        assert card.page_index == index
        assert card._page_label.text() == f"Page {index + 1}"

    tab.show_preview_at(2)
    qtbot.waitUntil(
        lambda: tab.preview_widget.current_page == 2,
        timeout=RENDER_TIMEOUT_MS,
    )
    ref = model.page_at(2)
    assert ref.source_index == 2
    assert ref.source_path == str(five_page_pdf)

    preview = tab.preview_widget
    qtbot.waitUntil(
        lambda: preview._image_label.pixmap() is not None
        and not preview._image_label.pixmap().isNull(),
        timeout=RENDER_TIMEOUT_MS,
    )

    grid.selection_manager.select_single(0)
    card = grid._cards[0]
    card._start_drag()
