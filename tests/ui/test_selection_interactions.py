"""Phase 5 UI tests — page selection interactions."""

from __future__ import annotations

from PyQt6.QtCore import Qt

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from tests.conftest import wait_for_grid_loaded, wait_for_pdf_loaded


def _load_grid(qtbot, pdf_path) -> ThumbnailGrid:
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(900, 650)
    loader = PdfLoader(str(pdf_path))
    grid.load_pdf(loader)
    wait_for_grid_loaded(qtbot, grid)
    loader.close()
    return grid


def _selected_indices(cards) -> set[int]:
    return {card.page_index for card in cards if card.is_selected}


def test_click_selects_single(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards

    qtbot.mouseClick(cards[0], Qt.MouseButton.LeftButton)
    assert _selected_indices(cards) == {0}

    qtbot.mouseClick(cards[2], Qt.MouseButton.LeftButton)
    assert _selected_indices(cards) == {2}
    assert not cards[0].is_selected


def test_ctrl_click_toggles(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards

    qtbot.mouseClick(
        cards[0],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    qtbot.mouseClick(
        cards[2],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    qtbot.mouseClick(
        cards[4],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    assert _selected_indices(cards) == {0, 2, 4}


def test_shift_click_selects_range(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards

    qtbot.mouseClick(cards[1], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(
        cards[3],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ShiftModifier,
    )
    assert _selected_indices(cards) == {1, 2, 3}


def test_ctrl_a_selects_all(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    qtbot.keyClick(
        window,
        Qt.Key.Key_A,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    assert _selected_indices(window._thumbnail_grid._cards) == {0, 1, 2, 3, 4}
    window.close()


def test_escape_clears_selection(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    qtbot.mouseClick(
        window._thumbnail_grid._cards[0],
        Qt.MouseButton.LeftButton,
    )
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert _selected_indices(window._thumbnail_grid._cards) == set()
    window.close()


def test_status_bar_matches_selection(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    cards = window._thumbnail_grid._cards
    qtbot.mouseClick(cards[0], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._selection_status.text() == "1 page selected",
        timeout=1000,
    )
    assert window._selection_status.isVisible()

    qtbot.mouseClick(
        cards[2],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    qtbot.waitUntil(
        lambda: window._selection_status.text() == "2 pages selected",
        timeout=1000,
    )

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    qtbot.waitUntil(
        lambda: window._selection_status.text() == "No selection",
        timeout=1000,
    )
    window.close()


def test_selection_toolbar_coalesces_storm(qtbot, five_page_pdf) -> None:
    """Rapid selection emits in one turn → one toolbar flush for the final set."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    updates: list[set[int]] = []
    real_status = window._update_selection_status

    def tracking_status(selection: set[int]) -> None:
        updates.append(set(selection))
        real_status(selection)

    window._update_selection_status = tracking_status  # type: ignore[method-assign]
    updates.clear()

    grid = window._thumbnail_grid
    # Simulate a selection storm in one turn (timer already armed after first).
    grid.selection_manager.select_single(0)
    assert updates == [{0}]
    assert window._selection_coalesce_timer.isActive()
    grid.selection_manager.select_range(0, 2)
    grid.selection_manager.select_range(0, 4)
    # Coalesced — no extra status update until the 0ms timer fires.
    assert updates == [{0}]
    qtbot.waitUntil(lambda: not window._selection_coalesce_timer.isActive(), timeout=1000)
    assert updates == [{0}, {0, 1, 2, 3, 4}]
    assert window._selection_status.text() == "5 pages selected"
    assert window._deselect_all_action.isEnabled()
    window.close()
