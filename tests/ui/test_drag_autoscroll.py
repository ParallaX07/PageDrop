"""Tests for drag auto-scroll while reordering pages."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from tests.conftest import wait_for_grid_loaded


def _load_tall_grid(qtbot, pdf_path, *, height: int = 120) -> ThumbnailGrid:
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(900, height)
    grid.show()
    loader = PdfLoader(str(pdf_path))
    grid.load_pdf(loader)
    wait_for_grid_loaded(qtbot, grid)
    grid._reflow_grid(force=True)
    return grid


def _assert_scrollable(grid: ThumbnailGrid) -> None:
    assert grid.verticalScrollBar().maximum() > 0


def test_edge_autoscroll_advances_scrollbar(qtbot, five_page_pdf):
    grid = _load_tall_grid(qtbot, five_page_pdf)
    _assert_scrollable(grid)
    bar = grid.verticalScrollBar()
    bar.setValue(0)

    scroller = grid._drag_autoscroller
    bottom_y = grid.height() - 4
    scroller.update(QPoint(grid.width() // 2, bottom_y))
    assert scroller._timer.isActive()

    start = bar.value()
    qtbot.wait(80)
    assert bar.value() > start

    scroller.stop()
    assert not scroller._timer.isActive()


def test_wheel_during_drag_scrolls_grid(qtbot, five_page_pdf):
    from PyQt6.QtGui import QWheelEvent

    grid = _load_tall_grid(qtbot, five_page_pdf)
    _assert_scrollable(grid)
    bar = grid.verticalScrollBar()
    bar.setValue(0)

    grid._start_drag_autoscroll_tracking()
    local = QPoint(grid.width() // 2, grid.height() // 2)
    grid._drag_autoscroller.update(local)

    global_pos = grid.mapToGlobal(local)
    wheel = QWheelEvent(
        QPointF(local),
        QPointF(global_pos),
        QPoint(0, -120),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    assert grid.eventFilter(grid, wheel)
    assert bar.value() > 0

    grid._stop_drag_autoscroll()


def test_drag_move_near_bottom_updates_indicator(qtbot, five_page_pdf):
    grid = _load_tall_grid(qtbot, five_page_pdf)
    _assert_scrollable(grid)
    bar = grid.verticalScrollBar()
    bar.setValue(bar.maximum())

    last_card = grid._cards[-1]
    pos_in_grid = grid.mapFromGlobal(
        last_card.mapToGlobal(QPoint(last_card.width() * 3 // 4, last_card.height() // 2))
    )

    grid._start_drag_autoscroll_tracking()
    grid._drag_autoscroller.update(pos_in_grid)
    grid._update_drop_at_drag_pos(pos_in_grid)

    assert grid._drop_insertion_index == len(grid._cards)
    assert grid._drop_indicator.isVisible()

    grid._stop_drag_autoscroll()
