"""Phase 3 unit tests — MainWindow."""

from __future__ import annotations

import pytest

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QFont, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolBar,
    QToolButton,
    QWidget,
)

from pagedrop.ui.keyboard_nav import focusable_toolbar_widgets
from pagedrop.ui.main_window import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, MainWindow
from tests.conftest import wait_for_compare_render, wait_for_pdf_loaded


def _file_menu_actions(window: MainWindow):
    menubar = window.menuBar()
    for action in menubar.actions():
        if action.text().replace("&", "") == "File":
            return list(action.menu().actions())
    raise AssertionError("File menu not found")


def test_menu_layout_does_not_dispatch_unrelated_timers(main_window, qtbot):
    fired = []
    timer = QTimer(main_window)
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: fired.append(True))
    timer.start(0)

    main_window._update_responsive_shell()

    assert not fired
    qtbot.waitUntil(lambda: bool(fired))


def _find_action_by_text(actions, *candidates: str):
    normalized = {text.replace("&", "") for text in candidates}
    for action in actions:
        label = action.text().replace("&", "")
        if label in normalized:
            return action
    raise AssertionError(f"No action matching {candidates}")


def test_window_title_default(main_window):
    assert main_window.windowTitle() == "PageDrop"


def test_custom_title_controls_are_in_the_title_bar(main_window, qtbot):
    if QApplication.platformName() == "offscreen":
        assert not main_window.windowFlags() & Qt.WindowType.FramelessWindowHint
    else:
        assert main_window.windowFlags() & Qt.WindowType.FramelessWindowHint
    title = main_window.findChild(type(main_window._title_label), "WindowTitle")
    assert title.text() == "PageDrop"
    assert main_window._window_controls.parent() is main_window._title_bar
    assert main_window.menuBar().parent() is main_window._title_bar
    assert main_window.menuWidget() is main_window._title_bar
    maximize = main_window.findChild(type(main_window._maximize_button), "WindowMaximize")
    maximize.click()
    qtbot.waitUntil(main_window.isMaximized)
    assert maximize.toolTip() == "Restore window"
    maximize.click()
    qtbot.waitUntil(lambda: not main_window.isMaximized())


def test_custom_title_drag_falls_back_when_system_move_is_unavailable(main_window):
    main_window.move(100, 100)
    title = main_window._title_label
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(110, 110),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(110, 120),
        QPointF(210, 220),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(110, 120),
        QPointF(210, 220),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )

    assert main_window.eventFilter(title, press)
    assert main_window.eventFilter(title, move)
    assert main_window.pos().x() == 200
    assert main_window.pos().y() == 210
    assert main_window.eventFilter(title, release)


def test_menu_actions_exist(main_window):
    actions = _file_menu_actions(main_window)
    labels = {action.text().replace("&", "") for action in actions if not action.isSeparator()}
    assert "Open PDF" in labels
    assert "Close tab" in labels
    assert "Exit" in labels


def test_high_traffic_actions_use_sentence_case(main_window):
    """Menus/toolbar follow project sentence-case (not Title Case)."""
    a = main_window._actions
    assert a["close_tab"].text().replace("&", "") == "Close tab"
    assert a["save_as"].text().replace("&", "") == "Save as"
    assert a["export_all"].text().replace("&", "") == "Export all pages…"
    assert a["new_window"].text().replace("&", "") == "New window"
    assert a["light_theme"].text().replace("&", "") == "Toggle light theme"
    assert a["chrome_visible"].text().replace("&", "") == "Show menu and toolbar"
    assert a["keyboard_shortcuts"].text().replace("&", "") == "Keyboard shortcuts"
    assert a["tips"].text().replace("&", "") == "Show tips"
    assert a["move_up"].text() == "Move up"
    assert a["move_to"].text() == "Move to…"
    assert a["select_all"].text() == "Select all"
    assert main_window._open_recent_menu.title().replace("&", "") == "Open recent"


def test_toolbar_open_button(main_window):
    open_action = None
    for toolbar in main_window.findChildren(QToolBar):
        for action in toolbar.actions():
            if action.text().replace("&", "") == "Open PDF":
                open_action = action
                break
    assert open_action is not None
    assert open_action is main_window._actions["open"]
    assert open_action.isEnabled()


def test_contextual_toolbar_lives_in_active_pdf_tab_and_hides_for_tools(main_window):
    """The window owns actions; the active PDF tab only hosts their toolbar."""
    tab = main_window._active_tab()
    assert tab is not None
    assert main_window._toolbar.parentWidget() is tab
    assert main_window.toolBarArea(main_window._toolbar) == Qt.ToolBarArea.NoToolBarArea

    tool_page = QWidget()
    tool_page.tool_page_id = "test-tool"
    main_window._tab_manager.add_page(tool_page, "Test tool")

    assert main_window._active_tab() is None
    assert main_window._toolbar.isHidden()


def test_contextual_toolbar_promotes_save_as_after_edit(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: main_window._active_tab().loader is not None, timeout=15000)
    tab = main_window._active_tab()
    assert tab is not None
    tab.thumbnail_grid.selection_manager.select_single(0)
    main_window._duplicate_selected_pages()
    tab.thumbnail_grid.selection_manager.select_single(0)

    save_button = main_window._toolbar.widgetForAction(main_window._actions["save_as"])
    extract_button = main_window._toolbar.widgetForAction(
        main_window._actions["extract_selected"]
    )
    assert save_button is not None and save_button.objectName() == "ToolbarPrimary"
    assert save_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    qtbot.waitUntil(lambda: extract_button is not None and not extract_button.isHidden())
    assert extract_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert main_window._selection_toolbar_label.text() == "Page 2 selected"

    preview_button = main_window._toolbar.widgetForAction(main_window._actions["preview"])
    assert preview_button is not None and preview_button.text() == "Pages / Preview"


def test_toolbar_overflow_owns_only_actions_displaced_from_the_toolbar(
    main_window, five_page_pdf, qtbot
):
    overflow = main_window._toolbar_overflow.menu()
    assert overflow is not None
    actions = main_window._actions
    assert overflow.actions() == []
    assert main_window._toolbar_overflow.isHidden()

    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: main_window._active_tab().loader is not None)
    assert overflow.actions() == [actions["export_all"]]

    main_window._active_tab().thumbnail_grid.selection_manager.select_single(0)
    qtbot.waitUntil(lambda: overflow.actions() == [actions["export_all"], actions["move_to"]])
    assert main_window._toolbar.widgetForAction(actions["move_to"]) is None
    rotate = main_window._toolbar.widgetForAction(actions["rotate_cw"])
    assert rotate is not None
    assert rotate.accessibleName() == "Rotate clockwise"
    assert actions["move_to"].shortcut().toString()


def test_open_pdf_updates_title(main_window, five_page_pdf, monkeypatch, qtbot):
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(five_page_pdf)], "PDF Files (*.pdf)"),
    )
    monkeypatch.setattr(main_window, "_ask_open_target", lambda path: "current")
    main_window._open_pdf()
    qtbot.waitUntil(
        lambda: main_window.windowTitle()
        == f"PageDrop: {five_page_pdf.name} (5 pages)",
        timeout=5000,
    )


def test_status_bar_shows_page_count(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(
        lambda: "Loaded" in main_window.statusBar().currentMessage(),
        timeout=15000,
    )
    message = main_window.statusBar().currentMessage()
    assert "5" in message


def test_progress_bar_visible_during_preparing(
    main_window, five_page_pdf, monkeypatch, qtbot
):
    import pagedrop.ui.thumbnail_grid as tg

    monkeypatch.setattr(tg, "LARGE_PDF_PAGE_THRESHOLD", 2)
    monkeypatch.setattr(tg, "CARD_CREATE_BATCH", 2)

    grid = main_window._thumbnail_grid
    shown_during_prep: list[bool] = []

    def _on_progress(current: int, total: int) -> None:
        if "loading" in grid._busy_reasons:
            # isHidden() is the local flag; isVisible() needs a shown window.
            shown_during_prep.append(not main_window._progress_bar.isHidden())

    grid.rendering_progress.connect(_on_progress)
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: len(grid._cards) == 5, timeout=10000)
    assert shown_during_prep
    assert any(shown_during_prep)


def test_window_title_uses_logical_count_after_delete(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(
        lambda: "5 pages" in main_window.windowTitle(),
        timeout=15000,
    )
    grid = main_window._thumbnail_grid
    grid.selection_manager.select_single(0)
    grid.selection_manager.toggle(1)
    main_window._delete_selected_pages()
    assert "3 pages" in main_window.windowTitle()
    assert main_window._active_tab().edit_model.logical_count() == 3


def test_thumbnail_followup_ignores_deleted_page_indices(
    main_window, five_page_pdf, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: len(main_window._thumbnail_grid._cards) == 5, timeout=10000)
    grid = main_window._thumbnail_grid
    assert grid._model is not None
    grid._model.remove_pages([4])
    # A completion queued before delete can retain the old render-width entry.
    grid._page_render_width.append(0)
    grid._start_rendering(silent=True, page_indices=[4])
    assert grid._model.logical_count() == 4


def test_exit_action_closes(main_window, qtbot):
    main_window.show()
    exit_action = _find_action_by_text(_file_menu_actions(main_window), "E&xit", "Exit")
    exit_action.trigger()
    qtbot.waitUntil(lambda: not main_window.isVisible(), timeout=5000)


def test_document_identity_is_in_the_title_not_the_toolbar(
    main_window, tmp_path, qtbot
):
    """The title keeps discoverable identity without a redundant toolbar label."""
    import fitz

    long_name = "a" * 80 + ".pdf"
    pdf = tmp_path / long_name
    doc = fitz.open()
    try:
        doc.new_page()
        doc.save(str(pdf))
    finally:
        doc.close()

    main_window._load_pdf(str(pdf))
    qtbot.waitUntil(lambda: main_window.windowTitle().endswith("(1 page)"), timeout=15000)
    assert main_window.findChild(QLabel, "ToolbarFilename") is None
    assert main_window._title_label.toolTip() == main_window.windowTitle()
    assert "…" in main_window._title_label.text()


def test_narrow_shell_elides_title_and_keeps_application_actions_reachable(main_window):
    main_window.resize(720, 480)
    main_window.show()
    QApplication.processEvents()

    assert main_window._title_label.toolTip() == main_window.windowTitle()
    assert main_window._title_label.width() < 220
    overflow_actions = main_window._application_overflow_menu.actions()
    top_level_actions = main_window.menuBar().actions()
    for action in (
        main_window._actions["create_pdf"],
        main_window._actions["tools"],
        main_window._help_menu_action,
    ):
        assert action in top_level_actions or action in overflow_actions


def test_title_does_not_overlap_window_controls(main_window, qtbot):
    main_window.resize(960, 680)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    main_window._update_responsive_shell()

    buttons = main_window._window_controls.findChildren(QToolButton)
    assert buttons
    assert (
        main_window._window_controls.geometry().right()
        <= main_window._title_bar.rect().right()
    )
    assert (
        main_window.menuBar().geometry().right()
        < main_window._window_controls.geometry().left()
    )
    assert all(button.isVisible() and button.width() > 0 for button in buttons)
    assert main_window._title_label.geometry().right() < min(
        button.geometry().left() for button in buttons
    )


def test_shell_keeps_application_destinations_reachable_at_baseline_sizes(main_window):
    for width, height in ((960, 680), (800, 600), (720, 480)):
        main_window.resize(width, height)
        QApplication.processEvents()
        top_level_actions = main_window.menuBar().actions()
        overflow_actions = main_window._application_overflow_menu.actions()
        assert main_window._actions["open"] in _file_menu_actions(main_window)
        for action in (
            main_window._actions["merge"],
            main_window._actions["create_pdf"],
            main_window._actions["tools"],
            main_window._help_menu_action,
        ):
            assert (action in top_level_actions) + (action in overflow_actions) == 1
        assert main_window._application_overflow_menu.menuAction().isVisible() == bool(
            overflow_actions
        )
        assert main_window._title_label.toolTip() == main_window.windowTitle()


@pytest.mark.parametrize("menu_width", [None, 660])
@pytest.mark.parametrize("control_width", [None, 90])
def test_shell_uses_rendered_geometry_after_menu_font_growth(
    main_window, qtbot, menu_width, control_width
):
    main_window.resize(720, 480)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    menu_bar = main_window.menuBar()
    # Exercise a menu bar capped narrower than the window, too: all
    # measurements must stay in menu-bar coordinates, including after a
    # platform layout change.
    if menu_width is not None:
        menu_bar.setMaximumWidth(menu_width)
    # Windows' offscreen font produces wide caption buttons. Also exercise
    # that pressure on platforms whose default caption font is narrower.
    if control_width is not None:
        for button in main_window._window_controls.findChildren(QToolButton):
            button.setFixedWidth(control_width)
    font = QFont(menu_bar.font())
    font.setPointSize(max(font.pointSize() + 8, 20))
    menu_bar.setFont(font)
    QApplication.processEvents()
    main_window._update_responsive_shell()

    top_level = menu_bar.actions()
    overflow = main_window._application_overflow_menu.actions()
    for action in main_window._responsive_menu_actions:
        assert (action in top_level) + (action in overflow) == 1
    assert main_window._application_overflow_menu.menuAction().isVisible() == bool(
        overflow
    )
    rendered_right = max(menu_bar.actionGeometry(action).right() + 1 for action in top_level)
    assert rendered_right <= main_window._window_controls.geometry().left()
    assert main_window._actions["open"] in _file_menu_actions(main_window)


def test_blank_grid_empty_state_uses_the_registered_open_action(main_window, monkeypatch):
    grid = main_window._active_tab().thumbnail_grid
    button = grid.findChild(QPushButton, "EmptyStateOpenButton")
    assert button is not None
    assert not button.isHidden()
    assert button.accessibleName() == "Open PDF"
    assert grid._empty_title.text() == "Open a PDF"
    assert grid._empty_hint.text() == "Arrange pages, extract selections, or combine documents"
    assert grid._empty_kbd.text() == "or drop a file here"
    assert "select" not in grid._empty_kbd.text().lower()
    assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert main_window._toolbar.isHidden()
    for action in (
        main_window._actions["select_all"],
        main_window._actions["extract_selected"],
        main_window._actions["delete_pages"],
    ):
        assert main_window._toolbar.widgetForAction(action).isHidden()

    triggered: list[bool] = []
    main_window._actions["open"].triggered.connect(lambda: triggered.append(True))
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([], "")
    )
    button.click()
    assert triggered == [True]


def test_tool_page_never_inherits_pdf_status_or_chrome(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: "Loaded" in main_window.statusBar().currentMessage())
    pdf_status = main_window.statusBar().currentMessage()

    tool_page = QWidget()
    tool_page.tool_page_id = "test-tool-status"
    tool_page.WINDOW_TITLE = "Test tool"
    main_window._tab_manager.add_page(tool_page, "Test tool")

    assert main_window._toolbar.isHidden()
    assert main_window._selection_status.isHidden()
    assert main_window.windowTitle() == "PageDrop: Test tool"
    assert main_window.statusBar().currentMessage() != pdf_status


def test_undo_labels_and_viewer_guidance_follow_current_history(
    main_window, five_page_pdf, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    tab = main_window._active_tab()
    assert tab is not None
    qtbot.waitUntil(lambda: tab.edit_model is not None)
    tab.edit_model.remove_pages([0, 1])
    main_window._update_undo_redo_actions()
    assert main_window._undo_action.text() == "Undo delete 2 pages"

    main_window._open_preview()
    qtbot.waitUntil(tab.is_viewer_mode)
    main_window._update_undo_redo_actions()
    assert not main_window._undo_action.isEnabled()
    assert main_window._undo_action.toolTip() == (
        "Return to the page grid to undo delete 2 pages"
    )


# --- title bar, window controls and edge resize ---------------------------------


def _mouse(kind, local, global_pos, button=Qt.MouseButton.LeftButton, buttons=None):
    if buttons is None:
        buttons = (
            Qt.MouseButton.NoButton
            if kind == QEvent.Type.MouseButtonRelease
            else button
        )
    return QMouseEvent(
        kind,
        QPointF(*local),
        QPointF(*global_pos),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


@pytest.fixture
def no_override_cursor():
    yield
    while QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()


def test_menu_bar_is_the_single_title_bar_menu(main_window):
    from PyQt6.QtWidgets import QMenuBar

    assert main_window.menuBar() is main_window.menuBar()
    assert main_window.menuBar() is main_window._menu_bar
    assert main_window.menuWidget() is main_window._title_bar
    assert main_window.findChildren(QMenuBar) == [main_window.menuBar()]


def test_window_controls_are_keyboard_reachable(main_window):
    for name in ("WindowMinimize", "WindowMaximize", "WindowClose"):
        button = main_window.findChild(QToolButton, name)
        assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus
        assert button.accessibleName()


def test_hiding_menu_and_toolbar_keeps_window_controls_working(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert main_window._window_controls.isVisible()

    main_window._chrome_visible_action.trigger()
    assert main_window.menuBar().isHidden()
    assert main_window._toolbar.isHidden()
    assert main_window._title_bar.isVisible()
    controls = main_window._window_controls
    qtbot.waitUntil(lambda: controls.isVisible() and controls.width() > 0)
    buttons = controls.findChildren(QToolButton)
    assert len(buttons) == 3
    assert all(button.isVisible() for button in buttons)
    # Controls stay on the right edge with the menu gone.
    assert controls.geometry().right() == main_window._title_bar.rect().right()

    maximize = main_window.findChild(QToolButton, "WindowMaximize")
    maximize.click()
    qtbot.waitUntil(main_window.isMaximized)
    maximize.click()
    qtbot.waitUntil(lambda: not main_window.isMaximized())

    minimize = main_window.findChild(QToolButton, "WindowMinimize")
    minimize.click()
    qtbot.waitUntil(main_window.isMinimized)
    main_window.showNormal()
    qtbot.waitUntil(lambda: not main_window.isMinimized())

    main_window._chrome_visible_action.trigger()
    assert not main_window.menuBar().isHidden()
    assert not main_window._toolbar.isHidden()
    qtbot.waitUntil(main_window.menuBar().isVisible)

    main_window._chrome_visible_action.trigger()
    main_window.findChild(QToolButton, "WindowClose").click()
    qtbot.waitUntil(lambda: not main_window.isVisible())


def test_double_click_on_title_toggles_maximize(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    double = _mouse(QEvent.Type.MouseButtonDblClick, (10, 10), (110, 110))

    assert main_window.eventFilter(main_window._title_label, double)
    qtbot.waitUntil(main_window.isMaximized)
    assert main_window.eventFilter(main_window._title_bar, double)
    qtbot.waitUntil(lambda: not main_window.isMaximized())


def test_double_click_on_menu_action_does_not_toggle_maximize(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    menu_bar = main_window.menuBar()
    file_action = menu_bar.actions()[0]
    spot = menu_bar.actionGeometry(file_action).center()
    double = _mouse(
        QEvent.Type.MouseButtonDblClick, (spot.x(), spot.y()), (spot.x(), spot.y())
    )

    assert not main_window.eventFilter(menu_bar, double)
    assert not main_window.isMaximized()

    blank = _mouse(QEvent.Type.MouseButtonDblClick, (menu_bar.width() - 2, 2), (5, 5))
    assert main_window.eventFilter(menu_bar, blank)
    qtbot.waitUntil(main_window.isMaximized)


def test_title_drag_starts_only_after_the_drag_distance(main_window, qtbot, monkeypatch):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    moves = []
    monkeypatch.setattr(
        main_window.windowHandle(), "startSystemMove", lambda: moves.append(1) or True
    )
    title = main_window._title_label
    threshold = QApplication.startDragDistance()
    press = _mouse(QEvent.Type.MouseButtonPress, (10, 10), (110, 110))
    assert main_window.eventFilter(title, press)
    assert moves == []

    small = _mouse(
        QEvent.Type.MouseMove,
        (10 + threshold - 2, 10),
        (110 + threshold - 2, 110),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
    )
    main_window.eventFilter(title, small)
    assert moves == []

    far = _mouse(
        QEvent.Type.MouseMove,
        (10 + threshold, 10),
        (110 + threshold, 110),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
    )
    assert main_window.eventFilter(title, far)
    assert moves == [1]
    # A single drag asks the system once.
    main_window.eventFilter(title, far)
    assert moves == [1]


@pytest.mark.parametrize(
    ("pos", "edges", "cursor"),
    [
        ((0, 300), Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
        ((799, 300), Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
        ((400, 0), Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
        ((400, 599), Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
        ((0, 0), Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeFDiagCursor),
        (
            (799, 599),
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
            Qt.CursorShape.SizeFDiagCursor,
        ),
        ((799, 0), Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeBDiagCursor),
        ((0, 599), Qt.Edge.LeftEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeBDiagCursor),
        ((400, 300), Qt.Edge(0), None),
        ((6, 300), Qt.Edge(0), None),
        ((793, 593), Qt.Edge(0), None),
    ],
)
def test_resize_edge_hit_testing(pos, edges, cursor):
    from PyQt6.QtCore import QPoint, QSize

    from pagedrop.ui.main_window import (
        RESIZE_MARGIN,
        cursor_for_edges,
        resize_edges_at,
    )

    assert RESIZE_MARGIN == 6
    found = resize_edges_at(QPoint(*pos), QSize(800, 600))
    assert found == edges
    assert cursor_for_edges(found) == cursor


@pytest.fixture
def edge_window(main_window, qtbot, monkeypatch, no_override_cursor):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    monkeypatch.setattr(main_window, "_uses_qt_edge_resize", lambda: True)
    return main_window


def test_hovering_the_margin_sets_and_restores_the_resize_cursor(edge_window):
    handle = edge_window.windowHandle()
    hover = _mouse(
        QEvent.Type.MouseMove, (3, 300), (3, 300), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton
    )
    edge_window.eventFilter(handle, hover)
    assert QApplication.overrideCursor().shape() == Qt.CursorShape.SizeHorCursor

    corner = _mouse(
        QEvent.Type.MouseMove, (3, 3), (3, 3), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton
    )
    edge_window.eventFilter(handle, corner)
    assert QApplication.overrideCursor().shape() == Qt.CursorShape.SizeFDiagCursor

    inside = _mouse(
        QEvent.Type.MouseMove, (300, 300), (300, 300), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton
    )
    edge_window.eventFilter(handle, inside)
    assert QApplication.overrideCursor() is None

    edge_window.eventFilter(handle, hover)
    assert QApplication.overrideCursor() is not None
    edge_window.eventFilter(handle, QEvent(QEvent.Type.Leave))
    assert QApplication.overrideCursor() is None

    edge_window.eventFilter(handle, hover)
    edge_window.eventFilter(edge_window, QEvent(QEvent.Type.WindowDeactivate))
    assert QApplication.overrideCursor() is None


def test_resize_cursor_does_not_leak_on_hide_or_close(edge_window, qtbot):
    handle = edge_window.windowHandle()
    hover = _mouse(
        QEvent.Type.MouseMove, (3, 300), (3, 300), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton
    )
    edge_window.eventFilter(handle, hover)
    edge_window.hide()
    assert QApplication.overrideCursor() is None

    edge_window.show()
    qtbot.waitExposed(edge_window, timeout=5000)
    edge_window.eventFilter(edge_window.windowHandle(), hover)
    assert QApplication.overrideCursor() is not None
    edge_window.close()
    assert QApplication.overrideCursor() is None


def test_margin_press_starts_a_system_resize(edge_window, monkeypatch):
    handle = edge_window.windowHandle()
    requested = []
    monkeypatch.setattr(
        handle, "startSystemResize", lambda edges: requested.append(edges) or True
    )
    press = _mouse(QEvent.Type.MouseButtonPress, (edge_window.width() - 2, 400), (500, 500))
    assert edge_window.eventFilter(handle, press)
    assert requested == [Qt.Edge.RightEdge]

    # The margin wins over the title bar: a press on the top edge resizes.
    top = _mouse(QEvent.Type.MouseButtonPress, (200, 1), (200, 1))
    assert edge_window.eventFilter(handle, top)
    assert requested[-1] == Qt.Edge.TopEdge

    inside = _mouse(QEvent.Type.MouseButtonPress, (300, 300), (300, 300))
    assert not edge_window.eventFilter(handle, inside)
    assert len(requested) == 2


def test_manual_resize_fallback_pins_the_opposite_edge(edge_window, monkeypatch):
    handle = edge_window.windowHandle()
    monkeypatch.setattr(handle, "startSystemResize", lambda edges: False)
    edge_window.setGeometry(100, 100, 960, 680)
    start = edge_window.geometry()

    press = _mouse(QEvent.Type.MouseButtonPress, (958, 678), (1058, 778))
    assert edge_window.eventFilter(handle, press)
    drag = _mouse(
        QEvent.Type.MouseMove, (0, 0), (1108, 808), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton
    )
    assert edge_window.eventFilter(handle, drag)
    grown = edge_window.geometry()
    assert grown.topLeft() == start.topLeft()
    assert (grown.width(), grown.height()) == (1010, 710)
    assert edge_window.eventFilter(
        handle, _mouse(QEvent.Type.MouseButtonRelease, (0, 0), (1108, 808))
    )
    assert edge_window._edge_resize is None

    # Dragging the left/top edge far inward stops at the minimum size and
    # leaves the right/bottom edge where it was.
    before = edge_window.geometry()
    press = _mouse(QEvent.Type.MouseButtonPress, (1, 1), (before.x() + 1, before.y() + 1))
    assert edge_window.eventFilter(handle, press)
    drag = _mouse(
        QEvent.Type.MouseMove,
        (0, 0),
        (before.x() + 2000, before.y() + 2000),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
    )
    edge_window.eventFilter(handle, drag)
    shrunk = edge_window.geometry()
    assert shrunk.width() == edge_window.minimumSize().width()
    assert shrunk.height() == edge_window.minimumSize().height()
    assert shrunk.right() == before.right()
    assert shrunk.bottom() == before.bottom()
    edge_window.eventFilter(handle, _mouse(QEvent.Type.MouseButtonRelease, (0, 0), (0, 0)))


@pytest.mark.skipif(
    __import__("sys").platform == "win32", reason="native resize is used on Windows"
)
def test_qt_edge_resize_is_off_when_maximized_or_not_frameless(main_window, qtbot):
    assert not main_window._uses_qt_edge_resize()  # framed offscreen window
    main_window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert main_window._uses_qt_edge_resize()
    main_window.showMaximized()
    qtbot.waitUntil(main_window.isMaximized)
    assert not main_window._uses_qt_edge_resize()
    handle = main_window.windowHandle()
    hover = _mouse(
        QEvent.Type.MouseMove, (3, 300), (3, 300), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton
    )
    main_window.eventFilter(handle, hover)
    assert QApplication.overrideCursor() is None


def test_restored_geometry_is_applied_before_the_window_is_shown(
    qapp, isolated_settings, monkeypatch, qtbot
):
    from pagedrop.ui.window_manager import WindowManager

    calls = []
    monkeypatch.setattr(
        MainWindow, "restore_saved_geometry", lambda self: calls.append("restore") or True
    )
    monkeypatch.setattr(MainWindow, "show", lambda self: calls.append("show"))
    manager = WindowManager(qapp)
    window = manager.open_new_window(restore_geometry=True)
    qtbot.addWidget(window)
    assert calls == ["restore", "show"]

    calls.clear()
    other = manager.open_new_window()
    qtbot.addWidget(other)
    assert calls == ["show"]


def _focus_chain(window):
    chain, widget = [], window.nextInFocusChain()
    while widget is not window:
        if widget.focusPolicy() in (
            Qt.FocusPolicy.StrongFocus,
            Qt.FocusPolicy.TabFocus,
        ):
            chain.append(widget)
        widget = widget.nextInFocusChain()
    return chain


def test_window_controls_come_last_in_the_focus_chain(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    chain = _focus_chain(main_window)
    controls = list(main_window._window_control_buttons)
    assert len(controls) == 3
    assert chain[0] not in controls
    zoom = main_window._zoom_controls.focus_widgets()
    last_zoom = max(chain.index(w) for w in zoom)
    assert [chain.index(w) for w in controls] == sorted(chain.index(w) for w in controls)
    assert min(chain.index(w) for w in controls) > last_zoom
    main_window.activateWindow()
    qtbot.waitUntil(main_window.isActiveWindow, timeout=3000)
    assert main_window.focusWidget() not in controls


def test_title_drag_continues_across_a_menu_action(main_window, qtbot, monkeypatch):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    moves = []
    monkeypatch.setattr(
        main_window.windowHandle(), "startSystemMove", lambda: moves.append(1) or True
    )
    menu_bar = main_window.menuBar()
    action_rect = menu_bar.actionGeometry(menu_bar.actions()[0])
    blank_x = menu_bar.width() - 2
    assert menu_bar.actionAt(QPoint(blank_x, 2)) is None
    press = _mouse(QEvent.Type.MouseButtonPress, (blank_x, 2), (blank_x, 2))
    assert main_window.eventFilter(menu_bar, press)

    spot = action_rect.center()
    far = _mouse(
        QEvent.Type.MouseMove,
        (spot.x(), spot.y()),
        (spot.x() - 40, spot.y() + 40),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
    )
    assert main_window.eventFilter(menu_bar, far)
    assert moves == [1]

    # Without a press in flight, the same spot is a normal menu hover.
    assert not main_window.eventFilter(menu_bar, far)


def _toolbar_fits(window: MainWindow) -> bool:
    """True when every shown toolbar widget is inside the bar and Qt's own
    extension button, which keyboard users cannot reach, stays unused."""
    toolbar = window._toolbar
    rect = toolbar.rect()
    for action in toolbar.actions():
        widget = toolbar.widgetForAction(action)
        if widget is not None and widget.isVisible() and not rect.contains(widget.geometry()):
            return False
    extension = toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
    return extension is None or not extension.isVisible()


def _open_loaded_window(main_window, five_page_pdf, qtbot, *, width: int, height: int = 680):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    main_window.resize(width, height)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    return main_window._active_tab()


@pytest.mark.parametrize("loaded", [False, True], ids=["blank tab", "loaded pdf"])
def test_window_content_fits_the_compact_floor(main_window, five_page_pdf, qtbot, loaded):
    if loaded:
        main_window._load_pdf(str(five_page_pdf))
        wait_for_pdf_loaded(qtbot, main_window)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    qtbot.waitUntil(
        lambda: main_window.size().width() == MIN_WINDOW_WIDTH
        and main_window.size().height() == MIN_WINDOW_HEIGHT
    )

    hint = main_window.centralWidget().minimumSizeHint()
    assert hint.width() <= MIN_WINDOW_WIDTH
    assert hint.height() <= MIN_WINDOW_HEIGHT - main_window.menuWidget().height()
    # The status bar sits under the central widget, so the whole window must fit too.
    window_hint = main_window.minimumSizeHint()
    assert window_hint.width() <= MIN_WINDOW_WIDTH
    assert window_hint.height() <= MIN_WINDOW_HEIGHT


def test_viewer_content_fits_the_compact_floor(main_window, five_page_pdf, qtbot):
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=MIN_WINDOW_WIDTH)
    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    main_window._open_preview_at(0)
    qtbot.waitUntil(tab.is_preview_visible)
    # Expanded side panels are the widest the viewer gets.
    tab.preview_widget._set_navigation_panel_collapsed(False, persist=False)
    tab.preview_widget._set_annot_rail_collapsed(False, persist=False)

    assert main_window.centralWidget().minimumSizeHint().width() <= MIN_WINDOW_WIDTH
    assert main_window.minimumSizeHint().width() <= MIN_WINDOW_WIDTH
    toolbar_scroll = tab.preview_widget._toolbar_scroll
    assert tab.preview_widget.minimumSizeHint().width() <= MIN_WINDOW_WIDTH
    # The viewer's own toolbar scrolls sideways instead of clipping.
    assert toolbar_scroll.widget() is tab.preview_widget._toolbar
    qtbot.waitUntil(lambda: toolbar_scroll.horizontalScrollBar().maximum() > 0)
    assert toolbar_scroll.height() >= tab.preview_widget._toolbar.sizeHint().height()
    # The expanded markup rail scrolls its tools rather than squashing them.
    rail_scroll = tab.preview_widget._annot_tools_scroll
    qtbot.waitUntil(lambda: rail_scroll.verticalScrollBar().maximum() > 0)
    assert not rail_scroll.horizontalScrollBar().isVisible()
    host = tab.preview_widget._annot_tools_host
    assert host.height() >= host.minimumSizeHint().height()
    tab.preview_widget._set_annot_rail_collapsed(True, persist=False)
    assert rail_scroll.isHidden()


def test_toolbar_moves_trailing_actions_to_more_when_narrow(
    main_window, five_page_pdf, qtbot
):
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=MIN_WINDOW_WIDTH)
    actions = main_window._actions
    toolbar = main_window._toolbar
    overflow_menu = main_window._toolbar_overflow_menu
    tab.thumbnail_grid.selection_manager.select_single(2)
    qtbot.waitUntil(lambda: main_window._selection_toolbar_label.text() == "Page 3 selected")
    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    qtbot.waitUntil(
        lambda: toolbar.width() <= MIN_WINDOW_WIDTH
        and actions["delete_pages"] in overflow_menu.actions()
        and main_window._toolbar_overflow.isVisible()
        and not main_window._selection_toolbar_label.isVisible()
        and _toolbar_fits(main_window)
    )

    # Last to go first: the label, then the trailing page actions; Open,
    # Pages / Preview, Save as and More stay on the bar.
    assert not main_window._selection_toolbar_label.isVisible()
    for key in ("open", "preview", "save_as"):
        assert toolbar.widgetForAction(actions[key]).isVisible()
    assert main_window._toolbar_overflow.isVisible()
    assert main_window._toolbar_overflow in focusable_toolbar_widgets(toolbar)
    assert toolbar.widgetForAction(actions["delete_pages"]) is None
    displaced = [a for a in overflow_menu.actions() if a in main_window._toolbar_displaceable]
    assert actions["delete_pages"] in displaced and actions["extract_selected"] in displaced
    assert actions["select_all"] not in displaced
    assert actions["export_all"] in overflow_menu.actions()
    assert actions["move_to"] in overflow_menu.actions()
    # Shared commands stay visible; only their toolbar button is gone.
    assert all(action.isVisible() for action in actions.values() if action in displaced)
    # The status bar still carries the selection count once the label is gone.
    assert main_window._selection_status.text() == "Page 3 selected"

    # Wide enough for every button whatever font an earlier test left behind.
    main_window.resize(1600, 680)
    qtbot.waitUntil(
        lambda: overflow_menu.actions() == [actions["export_all"], actions["move_to"]]
        and toolbar.widgetForAction(actions["delete_pages"]) is not None
        and main_window._selection_toolbar_label.isVisible()
        and _toolbar_fits(main_window)
    )
    for key in ("select_all", "rotate_cw", "extract_selected", "delete_pages"):
        assert toolbar.widgetForAction(actions[key]).isVisible()
    assert toolbar.widgetForAction(actions["rotate_cw"]).accessibleName() == actions[
        "rotate_cw"
    ].text()
    assert toolbar.widgetForAction(actions["extract_selected"]).toolButtonStyle() == (
        Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    )


def test_toolbar_never_needs_the_qt_extension_button_at_any_width(
    main_window, five_page_pdf, qtbot
):
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=1600)
    toolbar = main_window._toolbar
    for selected in (False, True):
        if selected:
            tab.thumbnail_grid.selection_manager.select_single(1)
        else:
            tab.thumbnail_grid.selection_manager.clear()
        for width in (1600, 960, 700, 560, MIN_WINDOW_WIDTH, 640, 1600):
            main_window.resize(width, 680)
            qtbot.waitUntil(
                lambda width=width: abs(toolbar.width() - width) < 10
                and _toolbar_fits(main_window)
            )
            assert toolbar.widgetForAction(main_window._actions["open"]).isVisible()
            assert main_window._toolbar_overflow.isVisible()
            assert focusable_toolbar_widgets(toolbar)[0] is toolbar.widgetForAction(
                main_window._actions["open"]
            )


def test_displaced_toolbar_actions_stay_disabled_in_more_and_keep_their_shortcut(
    main_window, five_page_pdf, qtbot
):
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=MIN_WINDOW_WIDTH)
    actions = main_window._actions
    toolbar = main_window._toolbar
    overflow_menu = main_window._toolbar_overflow_menu
    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    qtbot.waitUntil(lambda: actions["delete_pages"] in overflow_menu.actions())

    # Nothing is selected: displaced commands appear in More, disabled.
    for key in ("extract_selected", "delete_pages"):
        assert actions[key] in overflow_menu.actions()
        assert not actions[key].isEnabled()
        assert actions[key].isVisible()

    # A larger font widens the buttons and pushes more commands into More.
    font = main_window.font()
    font.setPointSize(font.pointSize() + 10)
    main_window.setFont(font)
    tab.thumbnail_grid.selection_manager.select_single(0)
    duplicate = actions["duplicate_pages"]
    qtbot.waitUntil(
        lambda: duplicate in overflow_menu.actions()
        and duplicate.isEnabled()
        and _toolbar_fits(main_window)
    )
    assert toolbar.widgetForAction(duplicate) is None
    assert duplicate.isVisible()

    assert tab.edit_model.logical_count() == 5
    main_window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is main_window)
    qtbot.keyClick(main_window, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: tab.edit_model.logical_count() == 6)


def _assert_hosted_page_scrolls(main_window, page, reach, qtbot):
    """A hosted tool page keeps the window small, scrolls at the floor, and is
    scroll-bar free when there is room."""
    scroll = page.findChild(QScrollArea, "ToolPageScroll")
    assert scroll is not None
    assert page.minimumSize() == QSize(0, 0)
    hint = main_window.minimumSizeHint()
    assert hint.width() <= MIN_WINDOW_WIDTH
    assert hint.height() <= MIN_WINDOW_HEIGHT

    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    qtbot.waitUntil(
        lambda: main_window.size() == QSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        and scroll.verticalScrollBar().maximum() > 0
    )
    scroll.ensureWidgetVisible(reach)
    top_left = reach.mapTo(scroll.viewport(), QPoint(0, 0))
    assert scroll.viewport().rect().contains(QRect(top_left, reach.size()))

    main_window.resize(960, 680)
    qtbot.waitUntil(
        lambda: not scroll.verticalScrollBar().isVisible()
        and not scroll.horizontalScrollBar().isVisible()
    )


def test_hosted_tool_shell_scrolls_instead_of_raising_the_window_minimum(
    main_window, qtbot
):
    from PyQt6.QtWidgets import QFormLayout, QLineEdit

    from pagedrop.ui.tool_shell import ToolShellWindow

    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    shell = ToolShellWindow(title="Test tool", description="Reverse every page.")
    options = QWidget()
    form = QFormLayout(options)
    for row in range(6):
        form.addRow(f"Option {row}", QLineEdit())
    shell.set_options_widget(options)
    assert shell.minimumSize() == QSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    main_window.open_tool_page(shell, page_id="tool:test")

    _assert_hosted_page_scrolls(main_window, shell, shell._run_btn, qtbot)
    # The body is the page's layout; overlays stay on the page itself.
    assert shell._body_layout.indexOf(shell._drop_zone) >= 0
    assert shell._busy_overlay.parentWidget() is shell
    assert shell._toast.parentWidget() is shell


def test_hosted_compare_page_scrolls_instead_of_raising_the_window_minimum(
    main_window, pdf_fixtures_dir, qtbot
):
    from pagedrop.core.pdf_tools import compare_pdf_text_diff
    from pagedrop.ui.compare_window import CompareWindow

    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    page = CompareWindow(editor=main_window)
    assert page.minimumSize() == QSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    main_window.open_tool_page(page, page_id=CompareWindow.PAGE_ID)
    original = str(pdf_fixtures_dir / "compare_original.pdf")
    revised = str(pdf_fixtures_dir / "compare_revised.pdf")
    page._apply_compare_report(original, revised, compare_pdf_text_diff(original, revised))

    _assert_hosted_page_scrolls(main_window, page, page._compare_btn, qtbot)
    wait_for_compare_render(qtbot, page)
