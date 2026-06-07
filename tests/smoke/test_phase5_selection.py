"""Phase 5 smoke tests — selection matrix on a 10-page fixture."""

from __future__ import annotations

from PyQt6.QtCore import Qt

from pagedrop.ui.main_window import MainWindow
from tests.conftest import wait_for_pdf_loaded
from tests.fixtures.generate_fixtures import generate_n_page


def _selected_indices(cards) -> set[int]:
    return {card.page_index for card in cards if card.is_selected}


def test_smoke_selection_matrix(qtbot, pdf_fixtures_dir):
    ten_page_pdf = pdf_fixtures_dir / "ten_page.pdf"
    if not ten_page_pdf.exists():
        generate_n_page(ten_page_pdf, 10)

    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(ten_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    cards = window._thumbnail_grid._cards
    assert len(cards) == 10
    status = window.statusBar()

    qtbot.mouseClick(cards[0], Qt.MouseButton.LeftButton)
    assert _selected_indices(cards) == {0}
    assert status.currentMessage() == "1 page selected"

    qtbot.mouseClick(cards[2], Qt.MouseButton.LeftButton)
    assert _selected_indices(cards) == {2}
    assert status.currentMessage() == "1 page selected"

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    for index in (0, 2, 4):
        qtbot.mouseClick(
            cards[index],
            Qt.MouseButton.LeftButton,
            modifier=Qt.KeyboardModifier.ControlModifier,
        )
    assert _selected_indices(cards) == {0, 2, 4}
    assert status.currentMessage() == "3 pages selected"

    qtbot.mouseClick(cards[1], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(
        cards[5],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ShiftModifier,
    )
    assert _selected_indices(cards) == set(range(1, 6))
    assert status.currentMessage() == "5 pages selected"

    qtbot.keyClick(
        window,
        Qt.Key.Key_A,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    assert _selected_indices(cards) == set(range(10))
    assert status.currentMessage() == "10 pages selected"

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert _selected_indices(cards) == set()
    assert status.currentMessage() == "No selection"

    window.close()
