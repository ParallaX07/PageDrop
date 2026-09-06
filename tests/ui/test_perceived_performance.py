"""Phase G — perceived performance (skeletons, render priority, zoom feedback)."""

from __future__ import annotations

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.theme import ZOOM_WHEEL_STEP
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.ui.zoom_controls import ZoomControls


def test_skeleton_cards_before_thumbnails(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    loader = PdfLoader(str(five_page_pdf))

    with qtbot.waitSignal(grid.rendering_started, timeout=5000):
        grid.load_pdf(loader)

    assert len(grid._cards) == 5
    assert not hasattr(grid, "_overlay")
    assert all(card._is_skeleton for card in grid._cards)
    assert all(not card._page_overlay.isHidden() for card in grid._cards)
    assert grid._skeleton_pulse_active

    qtbot.waitUntil(
        lambda: all(not card._is_skeleton for card in grid._cards),
        timeout=15000,
    )
    assert not grid._skeleton_pulse_active
    loader.close()


def test_initial_render_prioritizes_page_one_and_visible(
    qtbot, five_page_pdf, monkeypatch
):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(400, 300)
    grid.show()
    qtbot.waitExposed(grid, timeout=5000)

    captured: list[list[int]] = []
    original = ThumbnailGrid._priority_render_order

    def tracking(self, page_indices):
        ordered = original(self, page_indices)
        captured.append(ordered)
        return ordered

    monkeypatch.setattr(ThumbnailGrid, "_priority_render_order", tracking)
    monkeypatch.setattr(grid, "_get_visible_page_indices", lambda **_: [2, 3])

    loader = PdfLoader(str(five_page_pdf))
    with qtbot.waitSignal(grid.rendering_finished, timeout=15000):
        grid.load_pdf(loader)

    assert captured
    assert captured[0][0] == 0
    assert captured[0][:3] == [0, 2, 3]
    loader.close()


def test_zoom_debounce_shows_rendering_affordance(main_window, five_page_pdf, qtbot):
    with qtbot.waitSignal(
        main_window._thumbnail_grid.rendering_finished, timeout=15000
    ):
        main_window._load_pdf(str(five_page_pdf))

    grid = main_window._thumbnail_grid
    zoom = main_window.findChild(ZoomControls)
    assert zoom is not None

    grid.set_thumbnail_zoom(grid.thumbnail_width_px + ZOOM_WHEEL_STEP)
    assert main_window.statusBar().currentMessage() == "Rendering thumbnails…"
    assert zoom._value_label.text() == f"{grid.thumbnail_width_px}px"

    qtbot.waitUntil(
        lambda: main_window.statusBar().currentMessage().startswith("Thumbnail size:"),
        timeout=2000,
    )


def test_page_size_deferred_until_tooltip(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    loader = PdfLoader(str(five_page_pdf))
    assert loader._size_cache == {}

    grid.load_pdf(loader)
    assert loader._size_cache == {}

    card = grid._cards[0]
    assert "mm" not in card.toolTip()
    QApplication.sendEvent(card, QEvent(QEvent.Type.ToolTip))
    assert "mm" in card.toolTip()
    assert (0, 0) in loader._size_cache

    loader.close()


def test_progress_survives_silent_zoom_interrupt(qtbot, five_page_pdf):
    """Zoom mid-load must not freeze the status-bar percentage."""
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(400, 300)
    grid.show()
    qtbot.waitExposed(grid, timeout=5000)

    progress_values: list[int] = []
    finished: list[bool] = []

    grid.rendering_progress.connect(lambda cur, _total: progress_values.append(cur))
    grid.rendering_finished.connect(lambda: finished.append(True))

    loader = PdfLoader(str(five_page_pdf))
    with qtbot.waitSignal(grid.rendering_started, timeout=5000):
        grid.load_pdf(loader)

    assert grid._progress_active
    # Interrupt the initial job the same way zoom/scroll does.
    grid._start_rendering(silent=True, page_indices=[0, 1])
    assert grid._progress_active

    qtbot.waitUntil(lambda: bool(finished), timeout=15000)
    assert not grid._progress_active
    assert progress_values
    assert progress_values[-1] >= 1
    assert all(not card._is_skeleton for card in grid._cards)

    loader.close()
