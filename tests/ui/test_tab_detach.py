"""WC4 / Phase 18 — tab tear-off and Move to New Window (minimal smoke)."""

from __future__ import annotations

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from tests.conftest import RENDER_TIMEOUT_MS


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


def _ensure_window_manager(qapp):
    from pagedrop.ui.window_manager import WindowManager

    return WindowManager(qapp)


def _windows_added(manager, before: frozenset) -> list:
    return [window for window in manager.windows if window not in before]


def test_detach_tab_creates_new_window_with_same_pdf(
    one_page_pdf,
    five_page_pdf,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    source.showMinimized()

    tab_a = source._tab_manager.add_blank_tab()
    source._load_pdf(str(one_page_pdf), tab=tab_a)
    tab_b = source._tab_manager.add_blank_tab()
    source._load_pdf(str(five_page_pdf), tab=tab_b)
    source._tab_manager.removeTab(0)
    _wait_for_tab_loaded(qtbot, tab_a)
    _wait_for_tab_loaded(qtbot, tab_b)

    tab_a.thumbnail_grid.selection_manager.select_single(0)
    tab_a.set_zoom_level(140)
    tab_b_index = source._tab_manager.indexOf(tab_b)

    initial_count = len(manager.windows)
    windows_before = frozenset(manager.windows)
    source._detach_tab_to_new_window(tab_b_index)
    qtbot.waitUntil(
        lambda: len(manager.windows) == initial_count + 1,
        timeout=5000,
    )

    assert source._tab_manager.count() == 1
    assert _tab_at(source, 0).pdf_path == str(one_page_pdf)

    detached = _windows_added(manager, windows_before)[0]
    qtbot.addWidget(detached)
    assert detached._tab_manager.count() == 1
    detached_tab = _tab_at(detached, 0)
    assert detached_tab.pdf_path == str(five_page_pdf)
    assert detached_tab.loader is tab_b.loader
    assert detached_tab.zoom_level == tab_b.zoom_level
    assert detached_tab.thumbnail_grid.selection_manager.selection == set()


def test_move_to_new_window_context_menu(
    one_page_pdf,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    source.showMinimized()

    tab = _tab_at(source, 0)
    source._load_pdf(str(one_page_pdf), tab=tab)
    _wait_for_tab_loaded(qtbot, tab)

    initial_count = len(manager.windows)
    windows_before = frozenset(manager.windows)
    source._tab_manager.move_to_new_window_requested.emit(0)
    qtbot.waitUntil(
        lambda: len(manager.windows) == initial_count + 1,
        timeout=5000,
    )

    assert source._tab_manager.count() == 1
    assert _tab_at(source, 0).is_blank

    detached = _windows_added(manager, windows_before)[0]
    assert _tab_at(detached, 0).pdf_path == str(one_page_pdf)
