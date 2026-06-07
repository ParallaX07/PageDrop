"""Tests for Ctrl+scroll zoom and page preview."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QToolBar

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.page_preview import PagePreviewWidget
from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    MIN_PREVIEW_RENDER_WIDTH,
    ZOOM_WHEEL_STEP,
)
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.ui.zoom_controls import ZoomControls


def _ctrl_wheel(widget, delta_y: int) -> None:
    event = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    widget.wheelEvent(event)


def test_ctrl_scroll_zoom_increases_thumbnail_width(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)
    qtbot.waitSignal(grid.rendering_finished, timeout=15000)

    initial = grid.thumbnail_width_px
    _ctrl_wheel(grid, 120)
    assert grid.thumbnail_width_px == initial + ZOOM_WHEEL_STEP
    assert grid._cards[0].width() == grid.card_width

    loader.close()


def test_zoom_does_not_immediately_trigger_full_rerender(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)
    qtbot.waitSignal(grid.rendering_finished, timeout=15000)

    with qtbot.waitSignal(
        grid.rendering_started, timeout=200, raising=False
    ) as blocker:
        _ctrl_wheel(grid, 120)

    assert not blocker.signal_triggered
    assert grid.thumbnail_width_px == DEFAULT_THUMBNAIL_WIDTH + ZOOM_WHEEL_STEP
    loader.close()


def test_ctrl_scroll_zoom_out_decreases_thumbnail_width(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)
    qtbot.waitSignal(grid.rendering_finished, timeout=15000)

    _ctrl_wheel(grid, -120)
    assert grid.thumbnail_width_px == DEFAULT_THUMBNAIL_WIDTH - ZOOM_WHEEL_STEP

    loader.close()


def test_preview_button_disabled_without_pdf(main_window):
    preview_action = None
    for toolbar in main_window.findChildren(QToolBar):
        for action in toolbar.actions():
            if action.text() == "Preview":
                preview_action = action
                break
    assert preview_action is not None
    assert not preview_action.isEnabled()


def test_preview_button_enabled_with_pdf(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    preview_action = None
    for toolbar in main_window.findChildren(QToolBar):
        for action in toolbar.actions():
            if action.text() == "Preview":
                preview_action = action
                break
    assert preview_action is not None
    assert preview_action.isEnabled()


def _preview_zoom_step(preview: PagePreviewWidget) -> int:
    return ZOOM_WHEEL_STEP * max(1, preview.render_width_px // DEFAULT_THUMBNAIL_WIDTH)


def test_ctrl_scroll_zoom_increases_preview_width(qtbot, five_page_pdf):
    loader = PdfLoader(str(five_page_pdf))
    preview = PagePreviewWidget()
    preview.set_loader(loader)
    qtbot.addWidget(preview)
    preview.resize(900, 700)
    preview.show()
    qtbot.waitExposed(preview, timeout=5000)
    preview.show_page(0)

    initial = preview.render_width_px
    step = _preview_zoom_step(preview)
    _ctrl_wheel(preview._scroll, 120)
    assert preview.render_width_px == initial + step

    loader.close()


def test_ctrl_scroll_zoom_out_decreases_preview_width(qtbot, five_page_pdf):
    loader = PdfLoader(str(five_page_pdf))
    preview = PagePreviewWidget()
    preview.set_loader(loader)
    qtbot.addWidget(preview)
    preview.resize(900, 700)
    preview.show()
    qtbot.waitExposed(preview, timeout=5000)
    preview.show_page(0)

    initial = preview.render_width_px
    step = _preview_zoom_step(preview)
    _ctrl_wheel(preview._scroll, -120)
    assert preview.render_width_px == initial - step

    loader.close()


def test_preview_zoom_clamps_at_minimum(qtbot, five_page_pdf):
    loader = PdfLoader(str(five_page_pdf))
    preview = PagePreviewWidget()
    preview.set_loader(loader)
    qtbot.addWidget(preview)
    preview.resize(200, 200)
    preview.show()
    qtbot.waitExposed(preview, timeout=5000)
    preview.show_page(0)

    for _ in range(20):
        _ctrl_wheel(preview._scroll, -120)

    assert preview.render_width_px == MIN_PREVIEW_RENDER_WIDTH

    loader.close()


def test_preview_zoom_clamps_at_maximum(qtbot, five_page_pdf):
    loader = PdfLoader(str(five_page_pdf))
    preview = PagePreviewWidget()
    preview.set_loader(loader)
    qtbot.addWidget(preview)
    preview.resize(900, 700)
    preview.show()
    qtbot.waitExposed(preview, timeout=5000)
    preview.show_page(0)

    for _ in range(50):
        _ctrl_wheel(preview._scroll, 120)

    assert preview.render_width_px == MAX_RENDER_WIDTH_PX

    loader.close()


def test_open_preview_resets_zoom_to_fit(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    main_window._open_preview()
    qtbot.waitUntil(lambda: main_window._is_preview_visible(), timeout=5000)
    preview = main_window._preview_widget
    fit_width = preview.render_width_px

    _ctrl_wheel(preview._scroll, 120)
    assert preview.render_width_px > fit_width

    main_window._close_preview()
    main_window._open_preview()
    qtbot.waitUntil(lambda: main_window._is_preview_visible(), timeout=5000)
    assert preview.render_width_px == fit_width


def test_preview_arrow_keys_change_page(qtbot, five_page_pdf):
    loader = PdfLoader(str(five_page_pdf))
    preview = PagePreviewWidget()
    preview.set_loader(loader)
    qtbot.addWidget(preview)
    preview.show()
    qtbot.waitExposed(preview, timeout=5000)
    preview.show_page(0)

    assert preview.current_page == 0
    qtbot.keyClick(preview, Qt.Key.Key_Right)
    assert preview.current_page == 1
    qtbot.keyClick(preview, Qt.Key.Key_Down)
    assert preview.current_page == 2
    qtbot.keyClick(preview, Qt.Key.Key_Left)
    assert preview.current_page == 1
    qtbot.keyClick(preview, Qt.Key.Key_Up)
    assert preview.current_page == 0

    loader.close()


def test_zoom_controls_disabled_without_pdf(main_window):
    zoom = main_window.findChild(ZoomControls)
    assert zoom is not None
    assert not zoom.isEnabled()


def test_zoom_controls_enabled_with_pdf(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    zoom = main_window.findChild(ZoomControls)
    assert zoom is not None
    assert zoom.isEnabled()


def test_zoom_in_button_increases_thumbnail_width(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    grid = main_window._thumbnail_grid
    zoom = main_window.findChild(ZoomControls)
    initial = grid.thumbnail_width_px

    zoom._zoom_in.click()
    assert grid.thumbnail_width_px == initial + ZOOM_WHEEL_STEP
    assert zoom._value_label.text() == f"{grid.thumbnail_width_px}px"


def test_zoom_slider_changes_thumbnail_width(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    grid = main_window._thumbnail_grid
    zoom = main_window.findChild(ZoomControls)

    zoom._slider.setValue(zoom._slider.value() + 2)
    expected = DEFAULT_THUMBNAIL_WIDTH + 2 * ZOOM_WHEEL_STEP
    assert grid.thumbnail_width_px == expected


def test_zoom_rerender_prioritizes_visible_pages(qtbot, five_page_pdf, monkeypatch):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(400, 300)
    grid.show()
    qtbot.waitExposed(grid, timeout=5000)
    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)
    qtbot.waitSignal(grid.rendering_finished, timeout=15000)

    monkeypatch.setattr(grid, "_get_visible_page_indices", lambda **_: [0, 1])

    silent_requests: list[list[int] | None] = []
    original_start = ThumbnailGrid._start_rendering

    def tracking_start(self, *, silent, page_indices=None):
        if silent:
            silent_requests.append(
                list(page_indices) if page_indices is not None else None
            )
        return original_start(self, silent=silent, page_indices=page_indices)

    monkeypatch.setattr(grid, "_start_rendering", lambda **kw: tracking_start(grid, **kw))

    grid.set_thumbnail_zoom(grid.thumbnail_width_px + ZOOM_WHEEL_STEP)
    grid._render_zoom_quality()

    assert silent_requests == [[0, 1]]

    loader.close()


def test_escape_closes_preview(main_window, five_page_pdf, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    main_window._open_preview()
    qtbot.waitUntil(lambda: main_window._is_preview_visible(), timeout=5000)

    qtbot.keyClick(main_window._preview_widget, Qt.Key.Key_Escape)

    qtbot.waitUntil(lambda: not main_window._is_preview_visible(), timeout=5000)
    assert main_window._central_stack.currentWidget() is main_window._thumbnail_grid


def test_open_preview_uses_selected_page(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    main_window._thumbnail_grid.selection_manager.select_single(3)
    main_window._open_preview()

    qtbot.waitUntil(
        lambda: main_window._is_preview_visible(),
        timeout=5000,
    )
    assert main_window._preview_widget.current_page == 3
    assert main_window._central_stack.currentWidget() is main_window._preview_widget
