"""Tests for Ctrl+scroll zoom and page preview."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QToolBar

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.page_preview import PagePreviewDialog
from pagedrop.ui.theme import DEFAULT_THUMBNAIL_WIDTH, ZOOM_WHEEL_STEP
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.ui.zoom_controls import ZoomControls


def _ctrl_wheel(grid: ThumbnailGrid, delta_y: int) -> None:
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
    grid.wheelEvent(event)


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


def test_preview_arrow_keys_change_page(qtbot, five_page_pdf):
    loader = PdfLoader(str(five_page_pdf))
    dialog = PagePreviewDialog(loader, start_page=0)
    qtbot.addWidget(dialog)
    dialog.showMinimized()
    qtbot.waitExposed(dialog, timeout=5000)

    assert dialog._current_page == 0
    qtbot.keyClick(dialog, Qt.Key.Key_Right)
    assert dialog._current_page == 1
    qtbot.keyClick(dialog, Qt.Key.Key_Down)
    assert dialog._current_page == 2
    qtbot.keyClick(dialog, Qt.Key.Key_Left)
    assert dialog._current_page == 1
    qtbot.keyClick(dialog, Qt.Key.Key_Up)
    assert dialog._current_page == 0

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
    assert zoom._value_label.text() == str(grid.thumbnail_width_px)


def test_zoom_slider_changes_thumbnail_width(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    grid = main_window._thumbnail_grid
    zoom = main_window.findChild(ZoomControls)

    zoom._slider.setValue(zoom._slider.value() + 2)
    expected = DEFAULT_THUMBNAIL_WIDTH + 2 * ZOOM_WHEEL_STEP
    assert grid.thumbnail_width_px == expected


def test_open_preview_uses_selected_page(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    main_window._thumbnail_grid.selection_manager.select_single(3)
    main_window._open_preview()

    qtbot.waitUntil(
        lambda: main_window._preview_dialog is not None
        and main_window._preview_dialog.isVisible(),
        timeout=5000,
    )
    assert main_window._preview_dialog._current_page == 3
