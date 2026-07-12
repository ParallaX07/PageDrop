"""Phase 9 unit tests — UX polish."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QFileDialog, QToolBar

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.theme import ZOOM_WHEEL_STEP
from pagedrop.ui.thumbnail_grid import ThumbnailGrid


def test_card_tooltip(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)

    width_mm, height_mm = loader.page_size_mm(2)
    card = grid._cards[2]
    expected = f"Page 3 · {width_mm}×{height_mm} mm · Click to select"
    assert card.toolTip() == expected

    loader.close()


def test_context_menu_extract_action(
    main_window, five_page_pdf, tmp_path, monkeypatch, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    grid = main_window._thumbnail_grid
    grid.selection_manager.select_single(0)
    grid.selection_manager.toggle(2)

    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(tmp_path),
    )

    main_window._extract_selected_to_folder()

    pdfs = list(tmp_path.glob("*.pdf"))
    assert len(pdfs) == 2
    assert all(path.suffix == ".pdf" for path in pdfs)


def _press_key(widget, key: Qt.Key) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    widget.keyPressEvent(event)


def test_arrow_keys_and_space(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    grid = main_window._thumbnail_grid
    assert grid.focused_index == 0

    _press_key(grid, Qt.Key.Key_Right)
    assert grid.focused_index == 1

    _press_key(grid, Qt.Key.Key_Down)
    assert grid.focused_index == min(1 + grid._grid_cols, len(grid._cards) - 1)

    _press_key(grid, Qt.Key.Key_Space)
    assert grid.focused_index in grid.selection_manager.selection

    _press_key(grid, Qt.Key.Key_Space)
    assert grid.focused_index not in grid.selection_manager.selection


def test_zoom_changes_thumbnail_size(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    grid = main_window._thumbnail_grid
    initial = grid.thumbnail_width_px

    qtbot.keyClick(main_window, Qt.Key.Key_Plus)
    assert grid.thumbnail_width_px == initial + ZOOM_WHEEL_STEP

    qtbot.keyClick(main_window, Qt.Key.Key_Minus)
    assert grid.thumbnail_width_px == initial


def test_qsettings_remembers_directory(
    main_window, five_page_pdf, isolated_settings, monkeypatch
):
    remember_directory(str(five_page_pdf))
    assert last_directory() == str(five_page_pdf.parent)

    captured: dict[str, str] = {}

    def fake_open(parent, title, start_dir, file_filter):
        captured["start"] = start_dir
        return ([], "")

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", fake_open)
    main_window._open_pdf()
    assert captured["start"] == str(five_page_pdf.parent)


def test_minimum_window_size(main_window, qtbot):
    min_w = main_window.minimumWidth()
    min_h = main_window.minimumHeight()
    assert min_w >= 720
    assert min_h >= 480

    main_window.showMinimized()
    qtbot.waitExposed(main_window, timeout=5000)
    main_window.resize(200, 200)
    qtbot.waitUntil(
        lambda: main_window.width() >= min_w and main_window.height() >= min_h,
        timeout=2000,
    )
    assert main_window.width() >= min_w
    assert main_window.height() >= min_h


def _toolbar_action(window: MainWindow, label: str):
    for toolbar in window.findChildren(QToolBar):
        for action in toolbar.actions():
            if action.text() == label:
                return action
    raise AssertionError(f"Toolbar action {label!r} not found")


def test_select_all_deselect_all_toolbar(main_window, five_page_pdf, qtbot):
    select_all = _toolbar_action(main_window, "Select All")
    deselect_all = _toolbar_action(main_window, "Deselect All")
    assert not select_all.isEnabled()
    assert not deselect_all.isEnabled()

    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    assert select_all.isEnabled()
    assert not deselect_all.isEnabled()

    select_all.trigger()
    assert len(main_window._thumbnail_grid.selection_manager.selection) == 5
    assert deselect_all.isEnabled()

    deselect_all.trigger()
    assert main_window._thumbnail_grid.selection_manager.selection == set()
