"""Phase 5 UI tests — page selection interactions."""

from __future__ import annotations

from PyQt6.QtCore import Qt

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.thumbnail_grid import ThumbnailGrid


def _show_window(qtbot, window) -> None:
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    window.setFocus()


def _load_grid(qtbot, pdf_path) -> ThumbnailGrid:
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(900, 650)
    loader = PdfLoader(str(pdf_path))
    grid.load_pdf(loader)
    qtbot.waitSignal(grid.rendering_finished, timeout=30000)
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
    _show_window(qtbot, window)
    window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(window._thumbnail_grid.rendering_finished, timeout=30000)

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
    _show_window(qtbot, window)
    window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(window._thumbnail_grid.rendering_finished, timeout=30000)

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
    _show_window(qtbot, window)
    window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(window._thumbnail_grid.rendering_finished, timeout=30000)

    cards = window._thumbnail_grid._cards
    qtbot.mouseClick(cards[0], Qt.MouseButton.LeftButton)
    assert window.statusBar().currentMessage() == "1 page selected"

    qtbot.mouseClick(
        cards[2],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    assert window.statusBar().currentMessage() == "2 pages selected"

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert window.statusBar().currentMessage() == "No selection"
    window.close()
