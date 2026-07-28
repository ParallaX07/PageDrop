"""Phase 18 UI tests — WindowManager registry and multi-window lifecycle."""

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


def _reset_window_manager(qapp):
    from PyQt6.QtWidgets import QApplication

    from pagedrop.ui.convert_window import ConvertWindow
    from pagedrop.ui.main_window import MainWindow
    from pagedrop.ui.compare_window import CompareWindow
    from pagedrop.ui.merge_window import MergeWindow
    from pagedrop.ui.tools_window import ToolsWindow
    from pagedrop.ui.window_manager import WindowManager

    # Close utility hubs first — they are top-level and keep the app alive.
    for widget in list(QApplication.topLevelWidgets()):
        if isinstance(
            widget, (MergeWindow, ConvertWindow, ToolsWindow, CompareWindow)
        ):
            widget.close()
            qapp.processEvents()
    for widget in list(QApplication.topLevelWidgets()):
        if isinstance(widget, MainWindow):
            widget.close()
            qapp.processEvents()
    return WindowManager(qapp)


def test_open_new_window_spawns_second_main_window(qtbot, qapp):
    manager = _reset_window_manager(qapp)
    first = manager.open_new_window()
    qtbot.addWidget(first)

    assert len(manager.windows) == 1
    first._new_window()
    qtbot.waitUntil(lambda: len(manager.windows) == 2, timeout=5000)

    windows = list(manager.windows)
    assert first in windows
    assert all(isinstance(window, MainWindow) for window in windows)
    assert windows[0] is not windows[1]


def test_last_window_close_quits_app_when_only_one(qtbot, qapp, monkeypatch):
    manager = _reset_window_manager(qapp)
    window = manager.open_new_window()
    qtbot.addWidget(window)

    quit_called: list[bool] = []

    def spy_quit() -> None:
        quit_called.append(True)

    monkeypatch.setattr(qapp, "quit", spy_quit)

    assert len(manager.windows) == 1
    window.close()
    qapp.processEvents()

    assert quit_called
    assert window not in manager.windows


def test_two_windows_independent_tab_state(
    one_page_pdf,
    five_page_pdf,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    window_a = manager.open_new_window()
    window_b = manager.open_new_window()
    qtbot.addWidget(window_a)
    qtbot.addWidget(window_b)

    tab_a = _tab_at(window_a, 0)
    tab_b = _tab_at(window_b, 0)
    window_a._load_pdf(str(one_page_pdf), tab=tab_a)
    window_b._load_pdf(str(five_page_pdf), tab=tab_b)
    _wait_for_tab_loaded(qtbot, tab_a)
    _wait_for_tab_loaded(qtbot, tab_b)

    tab_a.thumbnail_grid.selection_manager.select_single(0)
    tab_a.set_zoom_level(120)
    tab_b.thumbnail_grid.selection_manager.select_single(3)
    tab_b.set_zoom_level(180)

    assert tab_a.pdf_path == str(one_page_pdf)
    assert tab_b.pdf_path == str(five_page_pdf)
    assert tab_a.loader is not None
    assert tab_b.loader is not None
    assert tab_a.loader.page_count == 1
    assert tab_b.loader.page_count == 5
    assert tab_a.thumbnail_grid.selection_manager.selection == {0}
    assert tab_b.thumbnail_grid.selection_manager.selection == {3}
    assert tab_a.zoom_level == 120
    assert tab_b.zoom_level == 180

    window_a._tab_manager.setCurrentIndex(0)
    assert window_a._active_tab() is tab_a
    assert window_a._active_tab().thumbnail_grid.selection_manager.selection == {0}

    window_b._tab_manager.setCurrentIndex(0)
    assert window_b._active_tab() is tab_b
    assert window_b._active_tab().thumbnail_grid.selection_manager.selection == {3}


def test_secondary_close_does_not_poison_geometry(qtbot, qapp, isolated_settings, monkeypatch):
    from pagedrop.ui.settings import load_window_geometry, save_window_geometry

    manager = _reset_window_manager(qapp)
    primary = manager.open_new_window()
    secondary = manager.open_new_window()
    qtbot.addWidget(primary)
    qtbot.addWidget(secondary)

    assert manager.is_primary(primary)
    assert not manager.is_primary(secondary)

    primary.resize(900, 700)
    secondary.resize(500, 400)
    primary_geom = primary.saveGeometry()
    save_window_geometry(primary_geom)

    quit_called: list[bool] = []
    monkeypatch.setattr(qapp, "quit", lambda: quit_called.append(True))

    secondary.close()
    qapp.processEvents()

    assert not quit_called
    loaded = load_window_geometry()
    assert loaded is not None
    assert bytes(loaded) == bytes(primary_geom)
    assert primary in manager.windows
    assert secondary not in manager.windows


def test_primary_close_persists_geometry_while_secondary_remains(
    qtbot, qapp, isolated_settings, monkeypatch
):
    from pagedrop.ui.settings import load_window_geometry

    manager = _reset_window_manager(qapp)
    primary = manager.open_new_window()
    secondary = manager.open_new_window()
    qtbot.addWidget(primary)
    qtbot.addWidget(secondary)

    primary.resize(880, 640)
    expected = primary.saveGeometry()

    quit_called: list[bool] = []
    monkeypatch.setattr(qapp, "quit", lambda: quit_called.append(True))

    primary.close()
    qapp.processEvents()

    assert not quit_called
    assert manager.primary is None
    loaded = load_window_geometry()
    assert loaded is not None
    assert bytes(loaded) == bytes(expected)


def test_unmanaged_open_in_new_window_does_not_spawn(qtbot, one_page_pdf):
    """Unmanaged MainWindow must not create a second top-level editor."""
    from PyQt6.QtWidgets import QApplication

    window = MainWindow()
    qtbot.addWidget(window)
    before = {
        id(w) for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)
    }
    window._open_in_new_window(str(one_page_pdf))
    after = {
        id(w) for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)
    }
    assert after == before
    assert "Cannot open a new window" in window.statusBar().currentMessage()


def test_closing_last_of_two_windows_quits(qtbot, qapp, monkeypatch):
    manager = _reset_window_manager(qapp)
    first = manager.open_new_window()
    second = manager.open_new_window()
    qtbot.addWidget(first)
    qtbot.addWidget(second)

    quit_called: list[bool] = []
    monkeypatch.setattr(qapp, "quit", lambda: quit_called.append(True))

    first.close()
    qapp.processEvents()
    assert not quit_called
    assert len(manager.windows) == 1

    second.close()
    qapp.processEvents()
    assert quit_called
    assert not manager.windows
