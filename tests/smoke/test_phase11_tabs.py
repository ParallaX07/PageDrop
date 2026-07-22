"""Phase 11 smoke tests — multi-tab open, switch, close, isolation."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from tests.conftest import RENDER_TIMEOUT_MS
from tests.fixtures.generate_fixtures import generate_n_page


def _tab_at(window: MainWindow, index: int) -> PdfTab:
    widget = window._tab_manager.widget(index)
    assert isinstance(widget, PdfTab)
    return widget


def _wait_for_tab_loaded(qtbot, tab: PdfTab, *, timeout: int = RENDER_TIMEOUT_MS) -> None:
    qtbot.waitUntil(
        lambda: (
            tab.loader is not None
            and tab.thumbnail_grid._last_rendered_width_px
            == tab.thumbnail_grid._thumbnail_width_px
            and tab.thumbnail_grid._render_pool.activeThreadCount() == 0
            and len(tab.thumbnail_grid._cards) == tab.loader.page_count
        ),
        timeout=timeout,
    )


def test_smoke_multi_tab_isolation(qtbot, pdf_fixtures_dir, monkeypatch):
    one_page = pdf_fixtures_dir / "one_page.pdf"
    two_page = pdf_fixtures_dir / "two_page.pdf"
    five_page = pdf_fixtures_dir / "five_page.pdf"
    if not two_page.exists():
        generate_n_page(two_page, 2)

    paths = [one_page, two_page, five_page]
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (
            [str(path) for path in paths],
            "PDF Files (*.pdf)",
        ),
    )

    window = MainWindow()
    monkeypatch.setattr(window, "_ask_multi_open_target", lambda _: "tabs")
    qtbot.addWidget(window)
    window.showMinimized()

    window._open_pdf()
    loaded_indices = [
        index
        for index in range(window._tab_manager.count())
        if not _tab_at(window, index).is_blank
    ]
    assert len(loaded_indices) == 3

    tabs = [_tab_at(window, index) for index in loaded_indices]
    for tab, path in zip(tabs, paths, strict=True):
        _wait_for_tab_loaded(qtbot, tab)
        assert tab.pdf_path == str(path)
        assert len(tab.thumbnail_grid._cards) == tab.loader.page_count

    tabs[0].thumbnail_grid.selection_manager.select_single(0)
    tabs[0].set_zoom_level(120)
    tabs[1].thumbnail_grid.selection_manager.select_single(1)
    tabs[1].set_zoom_level(160)
    tabs[2].thumbnail_grid.selection_manager.select_single(4)
    tabs[2].set_zoom_level(200)

    for index, tab in enumerate(tabs):
        window._tab_manager.setCurrentIndex(loaded_indices[index])
        qtbot.waitUntil(
            lambda expected=tab: window._active_tab() is expected,
            timeout=5000,
        )
        assert window._active_tab().thumbnail_grid.selection_manager.selection == (
            tab.thumbnail_grid.selection_manager.selection
        )
        assert window._active_tab().zoom_level == tab.zoom_level
        assert len(window._active_tab().thumbnail_grid._cards) == tab.loader.page_count

    middle_index = loaded_indices[1]
    window._tab_manager.setCurrentIndex(middle_index)
    window._tab_manager.tabCloseRequested.emit(middle_index)
    qtbot.waitUntil(
        lambda: window._tab_manager.count() == len(loaded_indices) - 1,
        timeout=5000,
    )

    remaining = [
        _tab_at(window, index)
        for index in range(window._tab_manager.count())
        if not _tab_at(window, index).is_blank
    ]
    assert len(remaining) == 2
    assert {tab.pdf_path for tab in remaining} == {str(one_page), str(five_page)}

    one_tab = next(tab for tab in remaining if tab.pdf_path == str(one_page))
    five_tab = next(tab for tab in remaining if tab.pdf_path == str(five_page))
    assert one_tab.thumbnail_grid.selection_manager.selection == {0}
    assert five_tab.thumbnail_grid.selection_manager.selection == {4}
    assert one_tab.zoom_level == 120
    assert five_tab.zoom_level == 200

    window._tab_manager.setCurrentIndex(window._tab_manager.indexOf(one_tab))
    qtbot.keyClick(
        window,
        Qt.Key.Key_Tab,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    qtbot.waitUntil(
        lambda: window._active_tab() is five_tab,
        timeout=5000,
    )

    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
