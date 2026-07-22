"""Phase D navigation: go-to-page, page-range jump, zoom reset, overlays."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QInputDialog

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.page_card import PageCard
from pagedrop.ui.page_preview import PagePreviewWidget
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    PAGE_NUMBER_OVERLAY_MIN_WIDTH,
    ZOOM_WHEEL_STEP,
)
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.ui.zoom_controls import ZoomControls


def test_jump_to_pages_selects_and_focuses(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)
    qtbot.waitSignal(grid.rendering_finished, timeout=15000)

    grid.jump_to_pages([2, 3])
    assert grid.selection_manager.selection == {2, 3}
    assert grid.focused_index == 2

    loader.close()


def test_go_to_page_dialog(main_window, five_page_pdf, qtbot, monkeypatch):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    monkeypatch.setattr(QInputDialog, "getInt", lambda *a, **k: (4, True))
    main_window._go_to_page_dialog()

    assert main_window._thumbnail_grid.selection_manager.selection == {3}
    assert main_window._thumbnail_grid.focused_index == 3


def test_go_to_page_in_preview(main_window, five_page_pdf, qtbot, monkeypatch):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)
    main_window._thumbnail_grid.selection_manager.select_single(0)
    main_window._open_preview()
    qtbot.waitUntil(lambda: main_window._is_preview_visible(), timeout=5000)

    monkeypatch.setattr(QInputDialog, "getInt", lambda *a, **k: (5, True))
    main_window._go_to_page_dialog()

    assert main_window._preview_widget.current_page == 4


def test_page_range_jump_dialog(main_window, five_page_pdf, qtbot, monkeypatch):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("2-4", True))
    main_window._page_range_jump_dialog()

    assert main_window._thumbnail_grid.selection_manager.selection == {1, 2, 3}


def test_page_overlay_appears_when_zoomed_in(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    loader = PdfLoader(str(five_page_pdf))
    with qtbot.waitSignal(grid.rendering_finished, timeout=15000):
        grid.load_pdf(loader)
    qtbot.waitUntil(
        lambda: all(not card._is_skeleton for card in grid._cards),
        timeout=5000,
    )

    card: PageCard = grid._cards[0]
    assert card._page_overlay.isHidden()

    grid.set_thumbnail_zoom(PAGE_NUMBER_OVERLAY_MIN_WIDTH)
    assert not card._page_overlay.isHidden()
    assert card._page_overlay.text() == "1"

    loader.close()


def test_ctrl_zero_resets_thumbnail_zoom(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    grid = main_window._thumbnail_grid
    grid.set_thumbnail_zoom(DEFAULT_THUMBNAIL_WIDTH + ZOOM_WHEEL_STEP * 3)
    assert grid.thumbnail_width_px != DEFAULT_THUMBNAIL_WIDTH

    main_window._reset_zoom()
    assert grid.thumbnail_width_px == DEFAULT_THUMBNAIL_WIDTH


def test_zoom_slider_double_click_resets(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    grid = main_window._thumbnail_grid
    zoom = main_window.findChild(ZoomControls)
    grid.set_thumbnail_zoom(DEFAULT_THUMBNAIL_WIDTH + ZOOM_WHEEL_STEP * 4)
    zoom.set_value(grid.thumbnail_width_px)

    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    zoom.eventFilter(zoom._slider, event)
    assert grid.thumbnail_width_px == DEFAULT_THUMBNAIL_WIDTH


def test_preview_ctrl_zero_fits_width(qtbot, five_page_pdf):
    loader = PdfLoader(str(five_page_pdf))
    preview = PagePreviewWidget()
    preview.set_loader(loader)
    qtbot.addWidget(preview)
    preview.resize(800, 600)
    preview.show()
    qtbot.waitExposed(preview, timeout=5000)
    preview.show_page(0)
    fit_width = preview.render_width_px

    preview.zoom_by(ZOOM_WHEEL_STEP * 5)
    assert preview.render_width_px != fit_width
    assert preview._manual_zoom

    preview.reset_zoom_to_fit()
    assert not preview._manual_zoom
    assert preview.render_width_px == preview._fit_render_width()

    loader.close()
