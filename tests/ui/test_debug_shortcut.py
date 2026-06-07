"""Temporary debug - delete after fix."""

from PyQt6.QtCore import Qt
from pagedrop.ui.main_window import MainWindow


def test_debug_shortcut(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    window.setFocus()
    window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(window._thumbnail_grid.rendering_finished, timeout=30000)
    cards = window._thumbnail_grid._cards
    qtbot.mouseClick(cards[0], Qt.MouseButton.LeftButton)
    assert {c.page_index for c in cards if c.is_selected} == {0}
    window._clear_selection()
    assert {c.page_index for c in cards if c.is_selected} == set()
