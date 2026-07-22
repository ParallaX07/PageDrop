"""Phase 11 UI tests — tab manager and MainWindow tab routing."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QFileDialog

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from tests.conftest import RENDER_TIMEOUT_MS
from tests.fixtures.generate_fixtures import generate_n_page


def _tab_at(window: MainWindow, index: int) -> PdfTab:
    widget = window._tab_manager.widget(index)
    assert isinstance(widget, PdfTab)
    return widget


def _loaded_tab_paths(window: MainWindow) -> list[str]:
    paths: list[str] = []
    for index in range(window._tab_manager.count()):
        tab = _tab_at(window, index)
        if tab.pdf_path is not None:
            paths.append(tab.pdf_path)
    return paths


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


def _open_single(
    window: MainWindow,
    path: Path,
    monkeypatch,
    *,
    target: str = "current",
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(path)], "PDF Files (*.pdf)"),
    )
    monkeypatch.setattr(window, "_ask_open_target", lambda _: target)
    window._open_pdf()


def _open_multi(window: MainWindow, paths: list[Path], monkeypatch) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (
            [str(path) for path in paths],
            "PDF Files (*.pdf)",
        ),
    )
    monkeypatch.setattr(window, "_ask_multi_open_target", lambda _: "tabs")
    window._open_pdf()


def _close_tab_at(window: MainWindow, index: int) -> None:
    window._tab_manager.setCurrentIndex(index)
    window._tab_manager.tabCloseRequested.emit(index)


def _trigger_shortcut(window: MainWindow, sequence: str) -> None:
    """Fire a registered window shortcut (reliable under offscreen Qt)."""
    target = QKeySequence(sequence)
    candidates = list(window.actions())
    registry = getattr(window, "_actions", None)
    if registry is not None:
        candidates.extend(registry.values())
    seen: set[int] = set()
    for action in candidates:
        key = id(action)
        if key in seen:
            continue
        seen.add(key)
        if action.shortcut() == target:
            action.trigger()
            return
    raise AssertionError(f"No action registered for {sequence}")


def test_long_tab_title_elided_with_full_tooltip(main_window, qtbot):
    """QSS-sized tabs ignore setElideMode, so titles are elided manually."""
    tab = _tab_at(main_window, 0)
    long_title = "Saalim_Saadman_Araf__Resume_With_A_Very_Long_Name"
    assert tab.set_custom_tab_title(long_title)

    tab_manager = main_window._tab_manager
    shown = tab_manager.tabText(0)
    assert shown.endswith("…")
    assert long_title.startswith(shown[:-1])
    assert tab_manager.tabToolTip(0) == tab.tab_title

    metrics = tab_manager.tabBar().fontMetrics()
    assert metrics.horizontalAdvance(shown) <= 185

    # Short titles pass through untouched.
    assert tab.set_custom_tab_title("Short")
    assert tab_manager.tabText(0) == "Short"
    assert tab_manager.tabToolTip(0) == "Short"


def test_tab_tooltip_includes_logical_page_count(
    main_window, five_page_pdf, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    tab = _tab_at(main_window, 0)
    assert (
        main_window._tab_manager.tabToolTip(0)
        == f"{five_page_pdf.name} (5 pages)"
    )

    tab.thumbnail_grid.selection_manager.select_single(0)
    assert tab.delete_selected_pages()
    main_window._tab_manager.update_tab_title(tab)
    assert (
        main_window._tab_manager.tabToolTip(0)
        == f"{five_page_pdf.name}* (4 pages)"
    )


def test_detach_hint_restores_title_tooltip(main_window):
    tab = _tab_at(main_window, 0)
    assert tab.set_custom_tab_title("My Document")
    bar = main_window._tab_manager.detachable_tab_bar

    bar._set_detach_hint(0, True)
    assert bar.tabToolTip(0) == "Release to open in new window"
    bar._clear_detach_hint()
    assert bar.tabToolTip(0) == "My Document"


def test_open_in_new_tab(main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot):
    _open_single(main_window, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    assert main_window._tab_manager.count() == 1

    _open_single(main_window, five_page_pdf, monkeypatch, target="new")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 1))

    assert main_window._tab_manager.count() == 2
    assert _tab_at(main_window, 0).pdf_path == str(one_page_pdf)
    assert _tab_at(main_window, 1).pdf_path == str(five_page_pdf)
    assert _tab_at(main_window, 0).loader is not None
    assert _tab_at(main_window, 1).loader is not None
    assert _tab_at(main_window, 0).loader.page_count == 1
    assert _tab_at(main_window, 1).loader.page_count == 5


def test_open_in_current_tab(main_window, five_page_pdf, monkeypatch, qtbot):
    assert _tab_at(main_window, 0).is_blank

    _open_single(main_window, five_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))

    assert main_window._tab_manager.count() == 1
    assert _tab_at(main_window, 0).pdf_path == str(five_page_pdf)
    assert not _tab_at(main_window, 0).is_blank


def test_multi_select_opens_each_in_new_tab(
    main_window,
    one_page_pdf,
    five_page_pdf,
    pdf_fixtures_dir,
    monkeypatch,
    qtbot,
):
    two_page_pdf = pdf_fixtures_dir / "two_page.pdf"
    if not two_page_pdf.exists():
        generate_n_page(two_page_pdf, 2)

    initial_count = main_window._tab_manager.count()
    paths = [one_page_pdf, two_page_pdf, five_page_pdf]
    asked: list[int] = []
    monkeypatch.setattr(
        main_window,
        "_ask_multi_open_target",
        lambda count: asked.append(count) or "tabs",
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (
            [str(path) for path in paths],
            "PDF Files (*.pdf)",
        ),
    )
    main_window._open_pdf()

    # Blank active tab: open each in its own tab with no prompt (reuse blank).
    assert asked == []
    assert main_window._tab_manager.count() == len(paths)
    loaded = _loaded_tab_paths(main_window)
    assert loaded == [str(path) for path in paths]

    for index in range(main_window._tab_manager.count()):
        _wait_for_tab_loaded(qtbot, _tab_at(main_window, index))


def test_multi_select_prompts_when_active_has_content(
    main_window,
    one_page_pdf,
    five_page_pdf,
    pdf_fixtures_dir,
    monkeypatch,
    qtbot,
):
    two_page_pdf = pdf_fixtures_dir / "two_page.pdf"
    if not two_page_pdf.exists():
        generate_n_page(two_page_pdf, 2)

    _open_single(main_window, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))

    paths = [two_page_pdf, five_page_pdf]
    asked: list[int] = []
    monkeypatch.setattr(
        main_window,
        "_ask_multi_open_target",
        lambda count: asked.append(count) or "tabs",
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (
            [str(path) for path in paths],
            "PDF Files (*.pdf)",
        ),
    )
    before = main_window._tab_manager.count()
    main_window._open_pdf()

    assert asked == [2]
    assert main_window._tab_manager.count() == before + len(paths)


def test_close_tab_via_x_button(
    main_window,
    one_page_pdf,
    five_page_pdf,
    pdf_fixtures_dir,
    monkeypatch,
    qtbot,
):
    two_page_pdf = pdf_fixtures_dir / "two_page.pdf"
    if not two_page_pdf.exists():
        generate_n_page(two_page_pdf, 2)

    for path in (one_page_pdf, two_page_pdf, five_page_pdf):
        tab = main_window._tab_manager.add_blank_tab()
        main_window._load_pdf(str(path), tab=tab)
    main_window._tab_manager.removeTab(0)

    for index in range(main_window._tab_manager.count()):
        _wait_for_tab_loaded(qtbot, _tab_at(main_window, index))

    assert main_window._tab_manager.count() == 3
    before = [tab.pdf_path for tab in (_tab_at(main_window, i) for i in range(3))]

    _close_tab_at(main_window, 1)
    qtbot.waitUntil(lambda: main_window._tab_manager.count() == 2, timeout=5000)

    after = [tab.pdf_path for tab in (_tab_at(main_window, i) for i in range(2))]
    assert after == [before[0], before[2]]


def test_close_tab_via_ctrl_w(main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot):
    main_window.showMinimized()
    _open_single(main_window, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    _open_single(main_window, five_page_pdf, monkeypatch, target="new")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 1))

    main_window._tab_manager.setCurrentIndex(1)
    _trigger_shortcut(main_window, "Ctrl+W")
    qtbot.waitUntil(lambda: main_window._tab_manager.count() == 1, timeout=5000)

    assert _tab_at(main_window, 0).pdf_path == str(one_page_pdf)


def test_ctrl_w_on_last_blank_tab_shows_status(main_window, qtbot):
    assert main_window._tab_manager.count() == 1
    assert _tab_at(main_window, 0).is_blank

    _trigger_shortcut(main_window, "Ctrl+W")

    assert main_window._tab_manager.count() == 1
    assert _tab_at(main_window, 0).is_blank
    assert "Cannot close the last blank tab" in main_window.statusBar().currentMessage()


def test_close_last_tab_spawns_blank_tab(main_window, one_page_pdf, monkeypatch, qtbot):
    _open_single(main_window, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))

    main_window.show()
    _close_tab_at(main_window, 0)
    qtbot.waitUntil(
        lambda: main_window._tab_manager.count() == 1
        and _tab_at(main_window, 0).is_blank,
        timeout=5000,
    )

    assert main_window.isVisible()


def test_close_middle_tab(
    main_window,
    one_page_pdf,
    five_page_pdf,
    pdf_fixtures_dir,
    monkeypatch,
    qtbot,
):
    two_page_pdf = pdf_fixtures_dir / "two_page.pdf"
    if not two_page_pdf.exists():
        generate_n_page(two_page_pdf, 2)

    paths = [one_page_pdf, two_page_pdf, five_page_pdf]
    for path in paths:
        tab = main_window._tab_manager.add_blank_tab()
        main_window._load_pdf(str(path), tab=tab)
    main_window._tab_manager.removeTab(0)

    for index in range(3):
        _wait_for_tab_loaded(qtbot, _tab_at(main_window, index))

    first_loader = _tab_at(main_window, 0).loader
    third_loader = _tab_at(main_window, 2).loader
    first_selection = {0}
    _tab_at(main_window, 0).thumbnail_grid.selection_manager.select_single(0)

    _close_tab_at(main_window, 1)
    qtbot.waitUntil(lambda: main_window._tab_manager.count() == 2, timeout=5000)

    assert _tab_at(main_window, 0).loader is first_loader
    assert _tab_at(main_window, 1).loader is third_loader
    assert _tab_at(main_window, 0).thumbnail_grid.selection_manager.selection == first_selection


def test_ctrl_tab_switches_active(main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot):
    main_window.showMinimized()
    _open_single(main_window, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    _open_single(main_window, five_page_pdf, monkeypatch, target="new")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 1))

    main_window._tab_manager.setCurrentIndex(0)
    _trigger_shortcut(main_window, "Ctrl+Tab")
    qtbot.waitUntil(
        lambda: main_window._tab_manager.currentIndex() == 1,
        timeout=5000,
    )
    assert _tab_at(main_window, 1).pdf_path == str(five_page_pdf)

    _trigger_shortcut(main_window, "Ctrl+Shift+Tab")
    qtbot.waitUntil(
        lambda: main_window._tab_manager.currentIndex() == 0,
        timeout=5000,
    )
    assert _tab_at(main_window, 0).pdf_path == str(one_page_pdf)


def test_toolbar_routes_to_active_tab(
    main_window,
    one_page_pdf,
    five_page_pdf,
    monkeypatch,
    qtbot,
):
    _open_single(main_window, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    _open_single(main_window, five_page_pdf, monkeypatch, target="new")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 1))

    tab_a = _tab_at(main_window, 0)
    tab_b = _tab_at(main_window, 1)
    tab_a.thumbnail_grid.selection_manager.select_single(0)
    assert tab_a.thumbnail_grid.selection_manager.selection == {0}
    assert tab_b.thumbnail_grid.selection_manager.selection == set()

    main_window._tab_manager.setCurrentIndex(1)
    qtbot.waitUntil(
        lambda: main_window._active_tab() is tab_b,
        timeout=5000,
    )
    main_window._select_all_pages()

    assert tab_b.thumbnail_grid.selection_manager.selection == set(range(5))
    assert tab_a.thumbnail_grid.selection_manager.selection == {0}


def _ensure_window_manager(qapp):
    from pagedrop.ui.window_manager import WindowManager

    return WindowManager(qapp)


def _windows_added(manager, before: frozenset) -> list:
    return [window for window in manager.windows if window not in before]


def test_detach_tab_to_new_window(
    one_page_pdf,
    five_page_pdf,
    monkeypatch,
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


def test_detach_last_tab_spawns_blank_tab(
    one_page_pdf,
    monkeypatch,
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
    source._detach_tab_to_new_window(0)
    qtbot.waitUntil(
        lambda: len(manager.windows) == initial_count + 1,
        timeout=5000,
    )
    qtbot.waitUntil(
        lambda: source._tab_manager.count() == 1 and _tab_at(source, 0).is_blank,
        timeout=5000,
    )


def test_move_to_new_window_context_menu(
    one_page_pdf,
    monkeypatch,
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

    detached = _windows_added(manager, windows_before)[0]
    assert _tab_at(detached, 0).pdf_path == str(one_page_pdf)


def test_detach_blank_tab_to_new_window(qtbot, qapp):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)

    assert _tab_at(source, 0).is_blank
    initial_count = len(manager.windows)
    windows_before = frozenset(manager.windows)
    source._detach_tab_to_new_window(0)
    qtbot.waitUntil(
        lambda: len(manager.windows) == initial_count + 1,
        timeout=5000,
    )

    detached = _windows_added(manager, windows_before)[0]
    assert _tab_at(detached, 0).is_blank
    qtbot.waitUntil(
        lambda: source._tab_manager.count() == 1 and _tab_at(source, 0).is_blank,
        timeout=5000,
    )


def test_detach_dirty_tab_keeps_dirty_flag(
    five_page_pdf,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)

    tab = _tab_at(source, 0)
    source._load_pdf(str(five_page_pdf), tab=tab)
    _wait_for_tab_loaded(qtbot, tab)
    tab.thumbnail_grid.reorder_pages_by_drop([4], 0)
    assert tab.is_dirty

    windows_before = frozenset(manager.windows)
    source._detach_tab_to_new_window(0)
    qtbot.waitUntil(
        lambda: len(manager.windows) == len(windows_before) + 1,
        timeout=5000,
    )

    detached = _windows_added(manager, windows_before)[0]
    detached_tab = _tab_at(detached, 0)
    assert detached_tab.is_dirty
    assert detached_tab.tab_title.endswith("*")


def test_detach_tab_in_preview_mode(
    five_page_pdf,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)

    tab = _tab_at(source, 0)
    source._load_pdf(str(five_page_pdf), tab=tab)
    _wait_for_tab_loaded(qtbot, tab)
    tab.show_preview_at(2)
    assert tab.is_preview_visible()

    windows_before = frozenset(manager.windows)
    source._detach_tab_to_new_window(0)
    qtbot.waitUntil(
        lambda: len(manager.windows) == len(windows_before) + 1,
        timeout=5000,
    )

    detached = _windows_added(manager, windows_before)[0]
    detached_tab = _tab_at(detached, 0)
    assert detached_tab.is_preview_visible()
    assert detached_tab.preview_widget.current_page == 2

