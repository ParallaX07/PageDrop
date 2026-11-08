"""Phase 11 UI tests — tab manager and MainWindow tab routing."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QAction, QColor, QIcon, QKeySequence, QMouseEvent
from PyQt6.QtWidgets import QApplication, QFileDialog, QTabBar, QWidget

from pagedrop.ui import settings as app_settings
from pagedrop.ui.accessibility import refresh_themed_widgets
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.theme import (
    INDEX_COLOUR_NAMES,
    SPACE_1,
    TAB_EDGE_HEIGHT,
    TAB_UNSAVED_DOT,
    current_theme,
    index_qcolor,
    token_qcolor,
)
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
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
    # Guard against setTabBar wiping tabsClosable — emit alone hides that bug.
    btn = window._tab_manager.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)
    assert btn is not None, f"tab {index} missing close button"
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
    assert "…" in shown
    shown_prefix, shown_suffix = shown.split("…", 1)
    assert long_title.startswith(shown_prefix)
    assert long_title.endswith(shown_suffix)
    assert tab_manager.tabToolTip(0) == tab.tab_title

    metrics = tab_manager.tabBar().fontMetrics()
    assert metrics.horizontalAdvance(shown) <= 185

    # Short titles pass through untouched.
    assert tab.set_custom_tab_title("Short")
    assert tab_manager.tabText(0) == "Short"
    assert tab_manager.tabToolTip(0) == "Short"


def test_crowded_tabs_have_an_open_tabs_menu(main_window, qtbot):
    manager = main_window._tab_manager
    for title in ("One", "Two", "Three", "Four"):
        tab = manager.add_blank_tab()
        assert tab.set_custom_tab_title(title)
    # Exercise tab overflow independently of the application's minimum width.
    main_window.setMinimumWidth(360)
    main_window.resize(360, 500)
    main_window.show()
    qtbot.waitUntil(lambda: manager._open_tabs_button.isVisible(), timeout=3000)

    manager._populate_open_tabs_menu()
    actions = manager._open_tabs_menu.actions()
    assert [action.text() for action in actions] == ["New tab", "One", "Two", "Three", "Four"]
    actions[2].trigger()
    assert manager.currentIndex() == 2
    main_window.resize(1200, 500)
    qtbot.waitUntil(lambda: manager._open_tabs_button.isHidden(), timeout=3000)


def test_open_tabs_menu_disambiguates_duplicate_filenames(main_window, tmp_path):
    paths = []
    for folder in ("first", "second"):
        path = tmp_path / folder / "report.pdf"
        path.parent.mkdir()
        generate_n_page(path, 1)
        paths.append(path)
    first = _tab_at(main_window, 0)
    main_window._load_pdf(str(paths[0]), tab=first)
    second = main_window._tab_manager.add_blank_tab()
    main_window._load_pdf(str(paths[1]), tab=second)

    manager = main_window._tab_manager
    manager._populate_open_tabs_menu()
    assert [action.text() for action in manager._open_tabs_menu.actions()] == [
        "report.pdf — first",
        "report.pdf — second",
    ]


def test_dirty_tab_has_accessible_unsaved_state(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    tab = _tab_at(main_window, 0)
    _wait_for_tab_loaded(qtbot, tab)
    tab.thumbnail_grid.reorder_pages_by_drop([4], 0)
    qtbot.waitUntil(lambda: tab.is_dirty, timeout=3000)
    assert "unsaved changes" in main_window._tab_manager.tabBar().accessibleTabName(0)


def test_document_and_tool_tabs_have_distinct_icons(main_window):
    manager = main_window._tab_manager
    document_icon = manager.tabIcon(0)
    tool = QWidget()
    manager.add_page(tool, "Tool")
    tool_icon = manager.tabIcon(manager.indexOf(tool))
    assert not document_icon.isNull()
    assert not tool_icon.isNull()
    assert document_icon.cacheKey() != tool_icon.cacheKey()


def test_tab_tooltip_includes_logical_page_count(
    main_window, five_page_pdf, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    tab = _tab_at(main_window, 0)
    assert main_window._tab_manager.tabToolTip(0) == f"{five_page_pdf.name}\n{five_page_pdf}\n5 pages"

    tab.thumbnail_grid.selection_manager.select_single(0)
    assert tab.delete_selected_pages()
    main_window._tab_manager.update_tab_title(tab)
    assert main_window._tab_manager.tabToolTip(0) == f"{five_page_pdf.name}\n{five_page_pdf}\n4 pages"


def test_each_pdf_tab_restores_its_own_toolbar_context(
    main_window, one_page_pdf, five_page_pdf, qtbot
):
    first = _tab_at(main_window, 0)
    main_window._load_pdf(str(one_page_pdf), tab=first)
    second = main_window._tab_manager.add_blank_tab()
    main_window._load_pdf(str(five_page_pdf), tab=second)
    _wait_for_tab_loaded(qtbot, first)
    _wait_for_tab_loaded(qtbot, second)

    main_window._tab_manager.setCurrentWidget(second)
    second.thumbnail_grid.selection_manager.select_single(0)
    qtbot.waitUntil(
        lambda: main_window._selection_toolbar_label.text() == "Page 1 selected"
    )
    main_window._tab_manager.setCurrentWidget(first)

    assert main_window.windowTitle() == f"PageDrop: {one_page_pdf.name} (1 page)"
    assert main_window._selection_toolbar_label.text() == "No selection"
    assert not main_window._selection_toolbar_label.isHidden()
    assert main_window._toolbar.parentWidget() is first


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


def test_detach_last_tab_spawns_blank_tab(
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
    source._detach_tab_to_new_window(0)
    qtbot.waitUntil(
        lambda: len(manager.windows) == initial_count + 1,
        timeout=5000,
    )
    qtbot.waitUntil(
        lambda: source._tab_manager.count() == 1 and _tab_at(source, 0).is_blank,
        timeout=5000,
    )


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


def test_rebinding_open_action_drops_the_previous_one(qtbot) -> None:
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    first, second = QAction("Open", grid), QAction("Open file", grid)
    hits: list[str] = []
    first.triggered.connect(lambda: hits.append("first"))
    second.triggered.connect(lambda: hits.append("second"))

    grid.bind_open_action(first)
    grid.bind_open_action(second)
    grid.bind_open_action(second)  # same action twice must not double-connect
    grid._empty_open_button.click()
    assert hits == ["second"]

    first.setText("Changed")  # no longer projected onto the button
    assert grid._empty_open_button.text() == "Open file"


def test_detached_blank_tab_opens_files_in_its_new_window(qtbot, qapp, monkeypatch):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    windows_before = frozenset(manager.windows)
    source._detach_tab_to_new_window(0)
    qtbot.waitUntil(lambda: len(manager.windows) > len(windows_before), timeout=5000)
    detached = _windows_added(manager, windows_before)[0]

    opened: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([], ""),
    )
    source._actions["open"].triggered.connect(lambda: opened.append("source"))
    detached._actions["open"].triggered.connect(lambda: opened.append("detached"))
    _tab_at(detached, 0).thumbnail_grid._empty_open_button.click()
    assert opened == ["detached"]


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


def test_open_tabs_button_shares_one_corner_with_new_tab(main_window, qtbot):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QToolButton, QWidget

    manager = main_window._tab_manager
    corner = manager.cornerWidget(Qt.Corner.TopRightCorner)
    assert corner.objectName() == "TabCorner"
    assert manager.cornerWidget(Qt.Corner.TopLeftCorner) is None
    new_tab = corner.findChild(QToolButton, "NewTabButton")
    assert corner.findChild(QToolButton, "ChromeToggleButton") is None
    assert new_tab is main_window._tab_manager.findChild(QToolButton, "NewTabButton")
    assert manager._open_tabs_button.parent() is corner

    for title in ("One", "Two", "Three", "Four"):
        assert manager.add_blank_tab().set_custom_tab_title(title)
    main_window.setMinimumWidth(360)
    main_window.resize(360, 500)
    main_window.show()
    qtbot.waitUntil(lambda: manager._open_tabs_button.isVisible(), timeout=3000)

    def buttons_laid_out():
        rects = [
            b.geometry()
            for b in (manager._open_tabs_button, new_tab)
            if b.isVisible()
        ]
        return (
            len(rects) == 2
            and all(corner.rect().contains(r) for r in rects)
            and not any(
                a.intersects(b) for i, a in enumerate(rects) for b in rects[i + 1 :]
            )
        )

    qtbot.waitUntil(buttons_laid_out, timeout=3000)
    # The corner is where the tab strip ends: the tab bar does not run under it.
    assert manager.tabBar().geometry().right() < corner.geometry().left()
    assert corner.geometry().right() <= manager.rect().right()

    manager._populate_open_tabs_menu()
    assert [a.text() for a in manager._open_tabs_menu.actions()][-4:] == [
        "One",
        "Two",
        "Three",
        "Four",
    ]

    # Hiding the button shrinks the corner without leaving a gap or overlap.
    main_window.resize(1200, 500)
    qtbot.waitUntil(lambda: manager._open_tabs_button.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: new_tab.geometry().left() == 0, timeout=3000)
    assert isinstance(corner, QWidget)


def test_chrome_toggle_lives_in_the_window_controls_and_collapses_the_chrome(
    isolated_settings, main_window, qtbot
):
    from PyQt6.QtWidgets import QToolButton

    toggle = main_window._chrome_toggle_btn
    controls = main_window._window_controls
    assert toggle.objectName() == "ChromeToggleButton"
    assert toggle.parent() is controls
    minimize = controls.findChild(QToolButton, "WindowMinimize")
    assert toggle not in main_window._window_control_buttons
    assert controls.layout().indexOf(toggle) + 1 == controls.layout().indexOf(minimize)
    assert toggle.text() == ""
    assert not toggle.icon().isNull()
    assert toggle.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert toggle.accessibleName() == toggle.toolTip() == "Hide menu and toolbar"

    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert toggle.isVisible()
    toggle.click()
    assert main_window.menuBar().isHidden()
    assert main_window._toolbar.isHidden()
    # The toggle is the way back and stays on screen with the chrome collapsed.
    qtbot.waitUntil(lambda: toggle.isVisible() and toggle.width() > 0)
    toggle.click()
    assert not main_window.menuBar().isHidden()
    assert not main_window._toolbar.isHidden()


def _close_button(window: MainWindow, index: int):
    bar = window._tab_manager.tabBar()
    button = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
    assert button is not None
    return button


def _close_button_shown(window: MainWindow, index: int) -> bool:
    bar = window._tab_manager.tabBar()
    return _close_button(window, index).isVisibleTo(bar)


def _hover(widget: QWidget, point: QPoint) -> None:
    """Deliver a pointer move with no buttons down (QTest.mouseMove is a no-op offscreen)."""
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(point),
        QPointF(widget.mapToGlobal(point)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def _show_window(qtbot, window: MainWindow) -> None:
    window.show()
    qtbot.waitExposed(window)


def _edge_pixel(window: MainWindow, index: int):
    bar = window._tab_manager.tabBar()
    rect = bar.tabRect(index)
    image = bar.grab().toImage()
    return image.pixelColor(rect.center().x(), TAB_EDGE_HEIGHT // 2)


def _three_blank_tabs(window: MainWindow) -> None:
    window._tab_manager.add_blank_tab()
    window._tab_manager.add_blank_tab()
    assert window._tab_manager.count() == 3


def _index_name(window: MainWindow, index: int) -> str | None:
    return _tab_at(window, index).index_colour


def test_index_colours_follow_open_order_and_cycle(main_window):
    manager = main_window._tab_manager
    for _ in range(6):
        manager.add_blank_tab()
    names = [_index_name(main_window, i) for i in range(manager.count())]
    assert names[:6] == list(INDEX_COLOUR_NAMES)
    assert names[6] == INDEX_COLOUR_NAMES[0]
    assert [manager._tab_index_colour(i) for i in range(manager.count())] == names


def test_tool_tab_uses_slate_and_does_not_take_a_document_colour(main_window):
    manager = main_window._tab_manager
    tool = QWidget()
    manager.add_page(tool, "Tool")
    assert manager._tab_index_colour(manager.indexOf(tool)) == "index_slate"
    fresh = manager.add_blank_tab()
    # The tool page did not advance the document counter.
    assert fresh.index_colour == "index_teal"


def test_reorder_keeps_colour_with_the_document(main_window):
    manager = main_window._tab_manager
    _three_blank_tabs(main_window)
    moved = _tab_at(main_window, 0)
    manager.tabBar().moveTab(0, 2)
    assert manager.indexOf(moved) == 2
    assert moved.index_colour == "index_clay"
    assert manager._tab_index_colour(2) == "index_clay"
    assert [_index_name(main_window, i) for i in range(3)] == [
        "index_teal",
        "index_ochre",
        "index_clay",
    ]


def test_top_edge_paints_the_index_colour_in_both_themes(main_window, qtbot):
    _show_window(qtbot, main_window)
    _three_blank_tabs(main_window)
    manager = main_window._tab_manager
    manager.setCurrentIndex(0)
    for light in (True, False):
        app_settings.set_light_theme(light)
        refresh_themed_widgets()
        for index in range(manager.count()):
            expected = index_qcolor(INDEX_COLOUR_NAMES[index])
            assert _edge_pixel(main_window, index).name() == expected.name(), (
                light,
                index,
            )
    # Active and inactive tabs both carry their colour; they differ from each other.
    assert _edge_pixel(main_window, 0).name() != _edge_pixel(main_window, 1).name()


def test_close_button_only_on_active_or_hovered_tab(main_window, qtbot):
    _show_window(qtbot, main_window)
    _three_blank_tabs(main_window)
    manager = main_window._tab_manager
    bar = manager.tabBar()
    manager.setCurrentIndex(1)
    assert [_close_button_shown(main_window, i) for i in range(3)] == [False, True, False]

    _hover(bar, bar.tabRect(2).center())
    assert _close_button_shown(main_window, 2)
    assert _close_button_shown(main_window, 1)
    assert not _close_button_shown(main_window, 0)

    QApplication.sendEvent(bar, QEvent(QEvent.Type.Leave))
    assert [_close_button_shown(main_window, i) for i in range(3)] == [False, True, False]

    manager.setCurrentIndex(0)
    assert [_close_button_shown(main_window, i) for i in range(3)] == [True, False, False]


def test_hiding_the_close_button_does_not_change_tab_widths(main_window, qtbot):
    _show_window(qtbot, main_window)
    _three_blank_tabs(main_window)
    manager = main_window._tab_manager
    bar = manager.tabBar()
    before = [bar.tabRect(i).width() for i in range(3)]
    manager.setCurrentIndex(2)
    _hover(bar, bar.tabRect(0).center())
    assert _close_button_shown(main_window, 0)
    assert [bar.tabRect(i).width() for i in range(3)] == before


def _mouse(bar, kind, point, *, buttons=Qt.MouseButton.LeftButton, global_pos=None) -> None:
    """Deliver a real mouse event to the bar (QTest.mouseMove is a no-op offscreen)."""
    button = (
        Qt.MouseButton.LeftButton
        if kind != QEvent.Type.MouseMove
        else Qt.MouseButton.NoButton
    )
    if kind == QEvent.Type.MouseButtonRelease:
        buttons = Qt.MouseButton.NoButton
    event = QMouseEvent(
        kind,
        QPointF(point),
        QPointF(global_pos if global_pos is not None else bar.mapToGlobal(point)),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(bar, event)


def _drag_start(bar, index: int) -> QPoint:
    start = bar.tabRect(index).center()
    _mouse(bar, QEvent.Type.MouseButtonPress, start)
    return start


def _move_dragged(bar, start: QPoint, dx: int) -> None:
    _mouse(bar, QEvent.Type.MouseMove, start + QPoint(dx, 0))
    QApplication.processEvents()  # Qt positions the dragged tab on the next pass


def _drag_across_slot(bar, start: QPoint, first: int, width: int) -> int:
    """Step the pointer in small moves until it is a tab's width from the press."""
    dx = first
    while dx < width:
        _move_dragged(bar, start, dx)
        dx += 15
    return dx - 15


def test_tabs_are_movable(main_window):
    manager = main_window._tab_manager
    assert manager.isMovable()
    assert manager.tabBar().isMovable()


def test_dragging_a_tab_with_the_mouse_reorders_it(main_window, qtbot):
    _show_window(qtbot, main_window)
    _three_blank_tabs(main_window)
    manager = main_window._tab_manager
    bar = manager.tabBar()
    first = _tab_at(main_window, 0)
    colours = [_index_name(main_window, i) for i in range(3)]

    start = _drag_start(bar, 0)
    last = _drag_across_slot(bar, start, 5, bar.tabRect(0).width())
    _mouse(bar, QEvent.Type.MouseButtonRelease, start + QPoint(last, 0))

    qtbot.waitUntil(lambda: manager.indexOf(first) == 1, timeout=3000)
    assert [_index_name(main_window, i) for i in range(3)] == [
        colours[1],
        colours[0],
        colours[2],
    ]


def test_dragged_tab_carries_its_stripe_and_dot_and_leaves_none_behind(
    main_window, five_page_pdf, qtbot
):
    _show_window(qtbot, main_window)
    main_window._load_pdf(str(five_page_pdf))
    dragged = _tab_at(main_window, 0)
    _wait_for_tab_loaded(qtbot, dragged)
    main_window._tab_manager.add_blank_tab()
    main_window._tab_manager.add_blank_tab()
    assert main_window._tab_manager.count() == 3
    dragged.thumbnail_grid.reorder_pages_by_drop([4], 0)
    qtbot.waitUntil(lambda: dragged.is_dirty, timeout=3000)
    manager = main_window._tab_manager
    bar = manager.tabBar()
    manager.setCurrentIndex(0)
    dragged_colour = index_qcolor(dragged.index_colour).name()
    ink = token_qcolor(current_theme().on_bar).name()
    slot = bar.tabRect(0)
    button = _close_button(main_window, 0)
    dot_y = (slot.top() + TAB_EDGE_HEIGHT + slot.bottom()) // 2
    dot_offset = button.geometry().left() - SPACE_1 - TAB_UNSAVED_DOT // 2

    start = _drag_start(bar, 0)
    for dx in (5, 20, 40):  # past the drag distance, not yet over the next tab
        _move_dragged(bar, start, dx)
    moving = bar._moving_tab
    assert moving is not None and moving.isVisible()
    shift = moving.x() + (moving.width() - slot.width()) // 2 - slot.x()
    assert shift > 20

    image = bar.grab().toImage()
    middle = slot.center().x() + shift
    assert image.pixelColor(middle, TAB_EDGE_HEIGHT // 2).name() == dragged_colour
    assert image.pixelColor(dot_offset + shift, dot_y).name() == ink
    # Neither mark stays behind at the empty slot the tab left.
    assert image.pixelColor(slot.left() + 4, TAB_EDGE_HEIGHT // 2).name() != dragged_colour
    assert image.pixelColor(dot_offset, dot_y).name() != ink

    # Over the next tab: the order changes mid-drag.
    last = _drag_across_slot(bar, start, 55, slot.width())
    qtbot.waitUntil(lambda: manager.indexOf(dragged) == 1, timeout=3000)
    image = bar.grab().toImage()
    assert image.pixelColor(bar.tabRect(1).center().x() + 30, 1).name() == dragged_colour
    assert image.pixelColor(slot.center().x(), 1).name() == index_qcolor(
        _tab_at(main_window, 0).index_colour
    ).name()

    _mouse(bar, QEvent.Type.MouseButtonRelease, start + QPoint(last, 0))
    qtbot.waitUntil(lambda: not moving.isVisible(), timeout=3000)
    image = bar.grab().toImage()
    for index in range(manager.count()):
        expected = index_qcolor(_tab_at(main_window, index).index_colour).name()
        assert image.pixelColor(bar.tabRect(index).center().x(), 1).name() == expected
    dot_x = _close_button(main_window, 1).geometry().left() - SPACE_1 - TAB_UNSAVED_DOT // 2
    assert image.pixelColor(dot_x, dot_y).name() == ink
    assert image.pixelColor(dot_offset, dot_y).name() != ink


def _strongest_pixel(image) -> QColor:
    pixels = [
        image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())
    ]
    return max(pixels, key=QColor.alpha)


def _close_to(actual: QColor, expected: QColor) -> bool:
    return all(
        abs(a - e) <= 3
        for a, e in (
            (actual.red(), expected.red()),
            (actual.green(), expected.green()),
            (actual.blue(), expected.blue()),
        )
    )


def test_close_icon_is_neutral_at_rest_and_danger_on_hover(main_window):
    icon = _close_button(main_window, 0).icon()
    theme = current_theme()
    rest = _strongest_pixel(icon.pixmap(14, 14, QIcon.Mode.Normal).toImage())
    hover = _strongest_pixel(icon.pixmap(14, 14, QIcon.Mode.Active).toImage())
    assert _close_to(rest, token_qcolor(theme.on_bar_muted))
    assert _close_to(hover, token_qcolor(theme.danger))
    assert not _close_to(rest, token_qcolor(theme.danger))


def test_close_icon_uses_the_text_colour_at_rest_in_high_contrast(main_window, monkeypatch):
    from pagedrop.ui import accessibility

    monkeypatch.setattr(accessibility, "prefers_high_contrast", lambda: True)
    main_window._tab_manager._refresh_close_icons()
    theme = current_theme()
    rest = _strongest_pixel(
        _close_button(main_window, 0).icon().pixmap(14, 14, QIcon.Mode.Normal).toImage()
    )
    assert _close_to(rest, token_qcolor(theme.text))
    assert not _close_to(rest, token_qcolor(theme.on_bar_muted))


def test_hovered_close_button_is_drawn_with_a_danger_icon(main_window, qtbot):
    _show_window(qtbot, main_window)
    button = _close_button(main_window, 0)

    def redness() -> int:
        image = button.grab().toImage()
        return max(
            image.pixelColor(x, y).red() - image.pixelColor(x, y).green()
            for x in range(image.width())
            for y in range(image.height())
        )

    # Neutral grey at rest; the hover fill alone is a faint tint, the icon is not.
    assert redness() < 15
    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    button.update()
    qtbot.waitUntil(lambda: redness() > 50, timeout=2000)


def test_close_tab_by_keyboard_after_close_button_is_hidden(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
):
    main_window.showMinimized()
    _open_single(main_window, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    _open_single(main_window, five_page_pdf, monkeypatch, target="new")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 1))
    main_window._tab_manager.setCurrentIndex(0)
    assert not _close_button_shown(main_window, 1)

    _trigger_shortcut(main_window, "Ctrl+W")
    qtbot.waitUntil(lambda: main_window._tab_manager.count() == 1, timeout=5000)
    assert _tab_at(main_window, 0).pdf_path == str(five_page_pdf)


def _dot_pixel(window: MainWindow, index: int):
    bar = window._tab_manager.tabBar()
    rect = bar.tabRect(index)
    button = _close_button(window, index)
    x = button.geometry().left() - SPACE_1 - TAB_UNSAVED_DOT // 2
    y = (rect.top() + TAB_EDGE_HEIGHT + rect.bottom()) // 2
    return bar.grab().toImage().pixelColor(x, y)


def test_unsaved_dot_is_painted_only_while_dirty(main_window, five_page_pdf, qtbot):
    _show_window(qtbot, main_window)
    main_window._load_pdf(str(five_page_pdf))
    tab = _tab_at(main_window, 0)
    _wait_for_tab_loaded(qtbot, tab)
    manager = main_window._tab_manager
    ink = token_qcolor(current_theme().on_bar).name()

    assert _dot_pixel(main_window, 0).name() != ink
    tab.thumbnail_grid.reorder_pages_by_drop([4], 0)
    qtbot.waitUntil(lambda: tab.is_dirty, timeout=3000)
    assert _dot_pixel(main_window, 0).name() == ink
    assert manager.tabBar().accessibleTabName(0).endswith(", unsaved changes")
    assert "*" not in manager.tabText(0)
    assert manager.tabText(0) == tab.display_name
    # The window title and unsaved prompt still read the starred title.
    assert tab.tab_title == f"{tab.display_name}*"

    assert tab.undo_edit()
    qtbot.waitUntil(lambda: not tab.is_dirty, timeout=3000)
    assert _dot_pixel(main_window, 0).name() != ink
    assert manager.tabBar().accessibleTabName(0) == tab.display_name


def test_tool_tab_never_shows_the_unsaved_dot(main_window, qtbot):
    _show_window(qtbot, main_window)
    tool = QWidget()
    main_window._tab_manager.add_page(tool, "Tool")
    index = main_window._tab_manager.indexOf(tool)
    assert _dot_pixel(main_window, index).name() != token_qcolor(current_theme().on_bar).name()
