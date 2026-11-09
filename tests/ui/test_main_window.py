"""Phase 3 unit tests — MainWindow."""

from __future__ import annotations

import pytest

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

from pagedrop.assets import register_fonts
from pagedrop.ui.keyboard_nav import focusable_toolbar_widgets
from pagedrop.ui.main_window import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, MainWindow
from pagedrop.ui.window_chrome import TITLE_MAX_WIDTH
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
    assert a["appearance_system"].text().replace("&", "") == "System appearance"
    assert a["appearance_light"].text().replace("&", "") == "Light appearance"
    assert a["appearance_dark"].text().replace("&", "") == "Dark appearance"
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
    qtbot.waitUntil(lambda: extract_button is not None and extract_button.isEnabled())
    assert extract_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert main_window._selection_toolbar_label.text() == "Page 2 selected"
    assert main_window._toolbar.widgetForAction(main_window._actions["preview"]) is None


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
    assert rotate.accessibleName() == "Rotate right"
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
    assert main_window._title_label.width() <= TITLE_MAX_WIDTH
    overflow_actions = main_window._application_overflow_menu.actions()
    top_level_actions = main_window.menuBar().actions()
    for action in (
        main_window._pages_menu_action,
        main_window._tools_menu_action,
        main_window._help_menu_action,
    ):
        assert action in top_level_actions or action in overflow_actions


def _top_level_menu(window, title: str):
    for action in window.menuBar().actions():
        if action.text().replace("&", "") == title:
            return action.menu()
    raise AssertionError(f"{title} menu not found")


def _menu_keys(window, menu) -> list[str | None]:
    by_action = {id(action): key for key, action in window._actions.items()}
    return [
        None if action.isSeparator() else by_action[id(action)]
        for action in menu.actions()
    ]


def test_top_level_menus_are_in_task_order(main_window):
    main_window.resize(1600, 680)
    main_window._update_responsive_shell()
    titles = [
        action.text().replace("&", "")
        for action in main_window.menuBar().actions()
        if action.isVisible()
    ]
    assert titles == ["File", "Edit", "View", "Pages", "Tools", "Help"]
    assert not main_window._application_overflow_menu.menuAction().isVisible()
    mnemonics = [
        action.text()[action.text().index("&") + 1].casefold()
        for action in main_window.menuBar().actions()
        if "&" in action.text()
    ]
    assert len(mnemonics) == len(set(mnemonics))


def test_pages_menu_holds_the_page_commands(main_window):
    menu = _top_level_menu(main_window, "Pages")
    assert _menu_keys(main_window, menu) == [
        "select_all",
        "deselect_all",
        None,
        "rotate_ccw",
        "rotate_cw",
        "duplicate_pages",
        "extract_selected",
        "extract_selected_to_tab",
        "extract_selected_to_window",
        "delete_pages",
        None,
        "move_up",
        "move_down",
        "move_to",
    ]
    assert main_window._pages_menu_action is menu.menuAction()
    edit_menu = _top_level_menu(main_window, "Edit")
    assert main_window._actions["select_all"] not in edit_menu.actions()
    assert main_window._actions["deselect_all"] not in edit_menu.actions()
    select_all = main_window._actions["select_all"]
    assert select_all.shortcut() == QKeySequence(QKeySequence.StandardKey.SelectAll)


def test_select_all_shortcut_still_works_from_the_pages_menu(
    main_window, five_page_pdf, qtbot
):
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=960)
    grid = tab.thumbnail_grid
    qtbot.keyClick(grid, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: len(grid.selection_manager.selection) == 5)
    main_window._actions["deselect_all"].trigger()
    qtbot.waitUntil(lambda: not grid.selection_manager.selection)


def test_tools_menu_holds_the_tool_launchers(main_window):
    menu = _top_level_menu(main_window, "Tools")
    assert _menu_keys(main_window, menu) == ["merge", "create_pdf", None, "tools"]
    assert main_window._tools_menu_action is menu.menuAction()
    assert main_window._actions["tools"].text() == "All &tools"
    assert main_window._actions["tools"].shortcut() == QKeySequence("Ctrl+Shift+O")
    top_level = main_window.menuBar().actions()
    assert main_window._actions["merge"] not in top_level
    assert main_window._actions["create_pdf"] not in top_level
    assert main_window._actions["tools"] not in top_level


def test_responsive_menu_actions_are_the_movable_menus_in_order(main_window):
    expected = [
        _top_level_menu(main_window, title).menuAction()
        for title in ("Edit", "View", "Pages", "Tools", "Help")
    ]
    assert list(main_window._responsive_menu_actions) == expected


@pytest.mark.parametrize("width", [MIN_WINDOW_WIDTH, 600, 800, 1200])
def test_title_label_elides_to_the_text_it_can_draw(main_window, qtbot, width):
    # The title strip is what the menus leave over, and the menus' width depends
    # on the font and style sheet. Use the ones the app starts with so the result
    # does not depend on which earlier test registered the font or styled the app.
    register_fonts()
    _style_window(main_window)
    main_window.resize(width, 480)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    main_window.setWindowTitle("PageDrop: " + "a_very_long_document_name_" * 6 + ".pdf (10 pages)")
    main_window._update_responsive_shell()

    label = main_window._title_label
    margins = label.contentsMargins()
    usable = label.width() - margins.left() - margins.right()
    assert label.toolTip() == main_window.windowTitle()
    assert label.text() != main_window.windowTitle()
    assert label.text() == "" or label.text().endswith("…")
    assert label.fontMetrics().horizontalAdvance(label.text()) <= usable
    assert label.width() <= TITLE_MAX_WIDTH


def test_title_label_shows_a_short_title_in_full(main_window, qtbot):
    main_window.resize(960, 680)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    main_window.setWindowTitle("PageDrop: ten_page.pdf (10 pages)")
    main_window._update_responsive_shell()

    label = main_window._title_label
    assert label.text() == main_window.windowTitle()
    assert label.fontMetrics().horizontalAdvance(label.text()) <= label.width()


def test_title_row_is_34px_at_the_default_font_and_grows_with_a_larger_one(
    main_window, qtbot
):
    # The row is what the menu bar needs, so measure it with the font and style
    # sheet the app starts with.
    register_fonts()
    _style_window(main_window)
    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert main_window._title_bar.minimumHeight() == 34
    assert main_window._menu_bar.sizeHint().height() <= 34
    assert main_window._title_bar.height() == 34
    assert main_window.minimumSize() == QSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

    from pagedrop.ui.theme import app_stylesheet

    main_window.setStyleSheet(app_stylesheet(light=True) + "QMenuBar { font-size: 28px; }")
    qtbot.waitUntil(lambda: main_window._title_bar.height() > 34, timeout=3000)


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
        for action in main_window._responsive_menu_actions:
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


def test_blank_start_screen_uses_the_registered_open_action(main_window, monkeypatch):
    tab = main_window._active_tab()
    screen = tab.start_screen
    assert tab.content_stack.currentWidget() is screen
    button = screen.findChild(QPushButton, "EmptyStateOpenButton")
    assert button is screen.open_button
    assert not button.isHidden()
    assert button.accessibleName() == "Open PDF"
    assert screen.findChild(QLabel, "GridEmptyState").text() == "Open a PDF"
    drop_hint = screen.findChild(QLabel, "GridEmptyKbd")
    assert drop_hint.text() == "or drop a file here"
    assert "select" not in drop_hint.text().lower()
    assert screen.accessibleDescription() == (
        "Arrange pages, extract selections, or combine documents"
    )
    assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert main_window._toolbar.isHidden()
    for action in (
        main_window._actions["extract_selected"],
        main_window._actions["delete_pages"],
    ):
        assert main_window._toolbar.widgetForAction(action) is not None
        assert not action.isEnabled()

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
    assert not main_window._selection_toolbar_label.isVisible()
    assert main_window.windowTitle() == "PageDrop: Test tool"
    assert main_window.statusBar().currentMessage() != pdf_status


def test_pages_menu_and_preview_are_disabled_on_a_tool_page_and_follow_the_pdf_again(
    main_window, five_page_pdf, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    pdf_tab = main_window._active_tab()
    pdf_tab.thumbnail_grid.selection_manager.select_single(2)
    qtbot.waitUntil(lambda: main_window._actions["delete_pages"].isEnabled())
    page_actions = [
        action
        for action in _top_level_menu(main_window, "Pages").actions()
        if not action.isSeparator()
    ]
    commands = [main_window._actions["preview"], *page_actions]
    assert all(action.isEnabled() for action in commands)

    tool_page = QWidget()
    tool_page.tool_page_id = "test-tool-actions"
    main_window._tab_manager.add_page(tool_page, "Test tool")
    assert main_window._active_tab() is None
    assert [action.text() for action in commands if action.isEnabled()] == []

    main_window._tab_manager.setCurrentWidget(pdf_tab)
    assert all(action.isEnabled() for action in commands)
    pdf_tab.thumbnail_grid.selection_manager.set_selection(set())
    qtbot.waitUntil(lambda: not main_window._actions["delete_pages"].isEnabled())
    assert main_window._actions["preview"].isEnabled()
    assert main_window._actions["select_all"].isEnabled()
    assert not main_window._actions["deselect_all"].isEnabled()
    assert not main_window._actions["rotate_cw"].isEnabled()


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
    for name in ("ChromeToggleButton", "WindowMinimize", "WindowMaximize", "WindowClose"):
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
    assert len(buttons) == 4
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


def _style_window(window: MainWindow) -> None:
    """Give the window the app style sheet so button padding is the real one."""
    from pagedrop.ui.theme import app_stylesheet

    window.setStyleSheet(app_stylesheet(light=True))


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
    _style_window(main_window)
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
        and _toolbar_fits(main_window)
    )

    # The trailing commands go to More; the selection cell, Open, Save as and
    # More stay on the bar.
    assert main_window._selection_toolbar_label.isVisible()
    assert main_window._selection_toolbar_label.text() == "Page 3 selected"
    for key in ("open", "save_as"):
        assert toolbar.widgetForAction(actions[key]).isVisible()
    assert main_window._toolbar_overflow.isVisible()
    assert main_window._toolbar_overflow in focusable_toolbar_widgets(toolbar)
    assert toolbar.widgetForAction(actions["delete_pages"]) is None
    displaced = [a for a in overflow_menu.actions() if a in main_window._toolbar_displaceable]
    assert actions["delete_pages"] in displaced
    assert actions["preview"] in displaced and actions["tools"] in displaced
    assert not main_window._view_switch.isVisible()
    assert actions["export_all"] in overflow_menu.actions()
    assert actions["move_to"] in overflow_menu.actions()
    # Shared commands stay visible; only their toolbar button is gone.
    assert all(action.isVisible() for action in actions.values() if action in displaced)

    # Wide enough for every button whatever font an earlier test left behind.
    main_window.resize(1600, 680)
    qtbot.waitUntil(
        lambda: overflow_menu.actions() == [actions["export_all"], actions["move_to"]]
        and toolbar.widgetForAction(actions["delete_pages"]) is not None
        and main_window._selection_toolbar_label.isVisible()
        and main_window._view_switch.isVisible()
        and _toolbar_fits(main_window)
    )
    for key in ("rotate_cw", "extract_selected", "delete_pages", "tools"):
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
    _style_window(main_window)
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=MIN_WINDOW_WIDTH)
    actions = main_window._actions
    toolbar = main_window._toolbar
    overflow_menu = main_window._toolbar_overflow_menu
    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    qtbot.waitUntil(lambda: actions["delete_pages"] in overflow_menu.actions())

    # Nothing is selected: displaced commands appear in More, disabled.
    for key in ("delete_pages",):
        assert actions[key] in overflow_menu.actions()
        assert not actions[key].isEnabled()
        assert actions[key].isVisible()

    # A narrower window than the floor pushes more commands into More.
    main_window.setMinimumSize(0, 0)
    main_window.resize(300, MIN_WINDOW_HEIGHT)
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


_COMMAND_BAR_ORDER = [
    "open",
    "save_as",
    "|",
    "selection",
    "rotate_ccw",
    "rotate_cw",
    "duplicate_pages",
    "extract_selected",
    "|",
    "delete_pages",
    "view",
    "tools",
    "more",
]
_COMMAND_BAR_LABELS = {
    "open": "Open",
    "save_as": "Save as",
    "rotate_ccw": "Rotate left",
    "rotate_cw": "Rotate right",
    "duplicate_pages": "Duplicate",
    "extract_selected": "Extract",
    "delete_pages": "Delete",
    "tools": "Tools",
}
_DROPPABLE_LABELS = ["open", "rotate_ccw", "rotate_cw", "duplicate_pages", "extract_selected", "delete_pages", "tools"]


def _command_bar_sequence(window: MainWindow) -> list[str]:
    """The bar's contents left to right; the zero-width anchor and spacer are layout only."""
    named = {action: key for key, action in window._actions.items()}
    named[window._selection_toolbar_action] = "selection"
    named[window._view_switch_action] = "view"
    named[window._toolbar_overflow_action] = "more"
    sequence = []
    for action in window._toolbar.actions():
        if action.isSeparator():
            sequence.append("|")
        elif action in named:
            sequence.append(named[action])
    return sequence


def _label_style(window: MainWindow, key: str):
    return window._toolbar.widgetForAction(window._actions[key]).toolButtonStyle()


def test_command_bar_is_grouped_as_file_selection_and_view(main_window):
    assert _command_bar_sequence(main_window) == _COMMAND_BAR_ORDER
    toolbar = main_window._toolbar
    # The view group is pushed to the right edge by one expanding spacer.
    actions = toolbar.actions()
    spacer = main_window._toolbar_spacer
    assert toolbar.widgetForAction(actions[actions.index(main_window._view_switch_action) - 1]) is spacer
    assert spacer.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert sum(1 for action in actions if action.isSeparator()) == 2
    for key in ("select_all", "deselect_all", "move_up", "move_down"):
        assert toolbar.widgetForAction(main_window._actions[key]) is None


def test_command_bar_buttons_carry_short_labels_beside_their_icons(main_window):
    toolbar = main_window._toolbar
    for key, label in _COMMAND_BAR_LABELS.items():
        button = toolbar.widgetForAction(main_window._actions[key])
        assert button.text() == label, key
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        assert not button.icon().isNull()
        assert button.toolTip(), key
    # Menus and the palette keep the full wording; the button names itself with it.
    actions = main_window._actions
    assert actions["rotate_cw"].text() == "Rotate right"
    assert actions["rotate_ccw"].text() == "Rotate left"
    assert "counter-clockwise" in actions["rotate_ccw"].toolTip()
    assert "clockwise" in actions["rotate_cw"].toolTip()
    assert actions["delete_pages"].text() == "Delete selected pages"
    assert actions["tools"].text() == "All &tools"
    assert toolbar.widgetForAction(actions["delete_pages"]).accessibleName() == (
        "Delete selected pages"
    )
    assert toolbar.widgetForAction(actions["tools"]).accessibleName() == "All tools"


def test_command_bar_separators_use_the_line_token(main_window):
    from pagedrop.ui.theme import LIGHT, app_stylesheet

    sheet = app_stylesheet(light=True)
    start = sheet.index("QToolBar::separator:horizontal")
    assert f"background: {LIGHT.line};" in sheet[start : sheet.index("}", start)]


def test_removed_toolbar_commands_keep_their_shortcuts(main_window, five_page_pdf, qtbot):
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=960)
    grid = tab.thumbnail_grid
    main_window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is main_window)
    grid.setFocus()
    qtbot.waitUntil(grid.hasFocus)

    qtbot.keyClick(grid, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: len(grid.selection_manager.selection) == 5)
    main_window._actions["deselect_all"].trigger()
    qtbot.waitUntil(lambda: not grid.selection_manager.selection)

    grid.selection_manager.select_single(2)
    qtbot.waitUntil(lambda: main_window._actions["move_up"].isEnabled())
    qtbot.keyClick(grid, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: grid.selection_manager.selection == {1})
    qtbot.keyClick(grid, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: grid.selection_manager.selection == {2})
    assert main_window._actions["move_up"].shortcut() == QKeySequence("Ctrl+Up")
    assert main_window._actions["move_down"].shortcut() == QKeySequence("Ctrl+Down")


def test_page_commands_stay_on_the_bar_and_nothing_shifts_with_selection(
    main_window, five_page_pdf, qtbot
):
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=1600)
    toolbar = main_window._toolbar
    keys = ("rotate_ccw", "rotate_cw", "duplicate_pages", "extract_selected", "delete_pages")
    qtbot.waitUntil(lambda: _toolbar_fits(main_window) and main_window._view_switch.isVisible())

    def settled(read):
        """Read *read* once the layout has stopped moving."""
        seen: list = []

        def stable() -> bool:
            seen.append(read())
            return len(seen) > 2 and seen[-1] == seen[-2] == seen[-3]

        qtbot.waitUntil(stable)
        return seen[-1]

    def positions() -> list[int]:
        label = main_window._selection_toolbar_label
        xs = [label.mapTo(toolbar, QPoint(0, 0)).x()]
        for key in keys:
            xs.append(toolbar.widgetForAction(main_window._actions[key]).x())
        return xs

    before = settled(positions)
    for key in keys:
        button = toolbar.widgetForAction(main_window._actions[key])
        assert button.isVisible(), key
        assert not button.isEnabled(), key
    assert main_window._selection_toolbar_label.text() == "No selection"
    assert main_window._selection_toolbar_label.width() == 180

    tab.thumbnail_grid.selection_manager.select_single(1)
    qtbot.waitUntil(lambda: main_window._selection_toolbar_label.text() == "Page 2 selected")
    for key in keys:
        button = toolbar.widgetForAction(main_window._actions[key])
        assert button.isVisible(), key
        assert button.isEnabled(), key
    assert settled(positions) == before

    tab.thumbnail_grid.selection_manager.set_selection({0, 2, 3})
    qtbot.waitUntil(lambda: main_window._selection_toolbar_label.text() == "3 pages selected")
    assert settled(positions) == before


def _primary_buttons(window: MainWindow) -> list[QToolButton]:
    return [
        button
        for button in window._toolbar.findChildren(QToolButton)
        if button.objectName() == "ToolbarPrimary"
    ]


def test_save_as_is_the_only_primary_action_in_every_state(
    main_window, five_page_pdf, qtbot
):
    save_button = main_window._toolbar.widgetForAction(main_window._actions["save_as"])
    open_button = main_window._toolbar.widgetForAction(main_window._actions["open"])

    # Blank tab, nothing to save yet.
    assert _primary_buttons(main_window) == [save_button]
    assert open_button.objectName() != "ToolbarPrimary"

    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = main_window._active_tab()
    assert not tab.is_dirty
    assert _primary_buttons(main_window) == [save_button]
    assert save_button.isEnabled()

    tab.thumbnail_grid.selection_manager.select_single(0)
    main_window._duplicate_selected_pages()
    qtbot.waitUntil(lambda: tab.is_dirty)
    assert _primary_buttons(main_window) == [save_button]
    assert open_button.objectName() != "ToolbarPrimary"

    # A new blank tab and back keeps the same single primary.
    main_window._new_blank_tab()
    assert _primary_buttons(main_window) == [save_button]
    main_window._tab_manager.setCurrentWidget(tab)
    assert _primary_buttons(main_window) == [save_button]
    assert open_button.objectName() != "ToolbarPrimary"


def test_save_as_keeps_its_primary_look_when_its_action_changes(
    main_window, five_page_pdf, qtbot
):
    from pagedrop.ui.theme import current_theme

    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    action = main_window._actions["save_as"]
    button = main_window._toolbar.widgetForAction(action)
    # Qt reloads the action's own icon whenever the action changes; the primary
    # button must go back to its on-ink icon.
    action.setEnabled(False)
    action.setEnabled(True)
    assert main_window._toolbar.widgetForAction(action) is button
    assert button.objectName() == "ToolbarPrimary"
    from pagedrop.ui import icons

    expected = icons.icon("floppy-disk", color=current_theme().on_ink).pixmap(18, 18).toImage()
    assert button.icon().pixmap(18, 18).toImage() == expected


def _command_bar_state(window: MainWindow):
    """(icon-only keys on the bar, keys in More, labelled flags in bar order)."""
    toolbar = window._toolbar
    on_bar = []
    for key in _DROPPABLE_LABELS:
        button = toolbar.widgetForAction(window._actions[key])
        if button is not None:
            on_bar.append(
                (key, button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly)
            )
    more = {
        key
        for key, action in window._actions.items()
        if action in window._toolbar_overflow_menu.actions()
    }
    return on_bar, more


def _refit_changes_nothing(window: MainWindow) -> bool:
    """True once the bar is fitted and laid out: a fresh refit changes nothing."""

    def state():
        return (
            frozenset(window._toolbar_icon_only),
            frozenset(
                action
                for action in window._toolbar_overflow_menu.actions()
                if not action.isSeparator()
            ),
        )

    before = state()
    window._refit_toolbar()
    toolbar = window._toolbar
    toolbar.layout().activate()
    laid_out = all(
        toolbar.widgetForAction(action).isVisible()
        for action in toolbar.actions()
        if action.isVisible() and toolbar.widgetForAction(action) is not None
    )
    return state() == before and laid_out and _toolbar_fits(window)


def _settle_at(qtbot, window: MainWindow, width: int) -> None:
    window.resize(width, 680)
    qtbot.waitUntil(
        lambda: abs(window._toolbar.width() - width) < 10 and _toolbar_fits(window)
    )
    # A deferred refit may still be queued; wait until it has nothing to change.
    qtbot.waitUntil(lambda: _refit_changes_nothing(window))


def test_narrow_bar_drops_labels_from_the_right_before_using_more(
    main_window, five_page_pdf, qtbot
):
    _style_window(main_window)
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=1600)
    tab.thumbnail_grid.selection_manager.select_single(1)
    qtbot.waitUntil(lambda: main_window._selection_toolbar_label.text() == "Page 2 selected")
    command_keys = {"rotate_ccw", "rotate_cw", "duplicate_pages", "extract_selected", "delete_pages", "preview", "tools"}

    saw_mixed = saw_more = False
    for width in range(1600, MIN_WINDOW_WIDTH - 1, -40):
        _settle_at(qtbot, main_window, width)
        on_bar, more = _command_bar_state(main_window)
        # Save as is primary, so it always keeps its label.
        assert _label_style(main_window, "save_as") == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        # Labels go from the right: left of any bare icon, no label is missing.
        flags = [icon_only for _key, icon_only in on_bar]
        assert flags == sorted(flags), (width, on_bar)
        saw_mixed = saw_mixed or (any(flags) and not all(flags))
        displaced = more & command_keys
        # The count is shown nowhere else, so the cell holds on to the floor.
        assert main_window._selection_toolbar_label.isVisible(), width
        if displaced:
            saw_more = True
            # Nothing reaches More while a label is still showing.
            assert all(flags), (width, on_bar, displaced)
        # Dropped labels keep their tooltip and accessible name.
        for key, _icon_only in on_bar:
            button = main_window._toolbar.widgetForAction(main_window._actions[key])
            assert button.toolTip() and button.accessibleName(), key
    assert saw_mixed and saw_more

    _settle_at(qtbot, main_window, 1600)
    on_bar, more = _command_bar_state(main_window)
    assert not any(icon_only for _key, icon_only in on_bar)
    assert len(on_bar) == len(_DROPPABLE_LABELS)
    assert not more & command_keys
    assert main_window._selection_toolbar_label.isVisible()
    assert main_window._view_switch.isVisible()


@pytest.mark.parametrize("selected", [False, True], ids=["no selection", "selection"])
def test_command_bar_fits_the_compact_floor_without_the_qt_extension_button(
    main_window, five_page_pdf, qtbot, selected
):
    _style_window(main_window)
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=MIN_WINDOW_WIDTH)
    if selected:
        tab.thumbnail_grid.selection_manager.select_single(0)
        qtbot.waitUntil(lambda: main_window._selection_toolbar_label.text() == "Page 1 selected")
    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    qtbot.waitUntil(
        lambda: main_window.size().width() == MIN_WINDOW_WIDTH and _toolbar_fits(main_window)
    )
    toolbar = main_window._toolbar
    for key in ("open", "save_as"):
        assert toolbar.widgetForAction(main_window._actions[key]).isVisible()
    assert main_window._toolbar_overflow.isVisible()
    # More holds only what left the bar plus its own always-there commands.
    on_bar_actions = set(toolbar.actions())
    for action in main_window._toolbar_overflow_menu.actions():
        if action.isSeparator():
            continue
        assert action not in on_bar_actions
    assert main_window._toolbar_overflow.width() <= toolbar.width()
    extension = toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
    assert extension is None or not extension.isVisible()


def _visible_texts(window: MainWindow) -> list[str]:
    return [
        widget.text()
        for widget in window.findChildren((QLabel, QToolButton))
        if widget.isVisible() and widget.text()
    ]


def test_selection_count_has_no_status_bar_copy(main_window, five_page_pdf, qtbot):
    assert not hasattr(main_window, "_selection_status")
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=1600)
    qtbot.waitUntil(lambda: _toolbar_fits(main_window))
    assert _visible_texts(main_window).count("No selection") == 1

    tab.thumbnail_grid.selection_manager.select_single(1)
    qtbot.waitUntil(lambda: main_window._selection_toolbar_label.text() == "Page 2 selected")
    texts = _visible_texts(main_window)
    assert texts.count("Page 2 selected") == 1
    assert "No selection" not in texts
    assert "selected" not in main_window.statusBar().currentMessage()
    status_labels = [
        label.text() for label in main_window.statusBar().findChildren(QLabel) if label.isVisible()
    ]
    assert not [text for text in status_labels if "selected" in text or text == "No selection"]
    assert main_window._selection_toolbar_label.accessibleName() == "Page 2 selected"

    tab.thumbnail_grid.selection_manager.set_selection({0, 2, 3})
    qtbot.waitUntil(lambda: main_window._selection_toolbar_label.text() == "3 pages selected")
    assert main_window._selection_toolbar_label.accessibleName() == (
        "3 pages selected: Pages 1, 3–4"
    )
    assert _visible_texts(main_window).count("3 pages selected") == 1


def test_thumbnail_size_caption_appears_once_in_the_status_bar(
    main_window, five_page_pdf, qtbot
):
    from PyQt6.QtGui import QFont

    _open_loaded_window(main_window, five_page_pdf, qtbot, width=1600)
    qtbot.waitUntil(lambda: main_window._thumbnail_zoom_label.isVisible())
    captions = [
        label
        for label in main_window.statusBar().findChildren(QLabel)
        if label.isVisible() and label.text() == "Thumbnail size"
    ]
    assert captions == [main_window._thumbnail_zoom_label]
    assert sum("Thumbnail size" in text for text in _visible_texts(main_window)) == 1
    # The caption is ordinary text; only the numeric readout is tabular.
    font = captions[0].font()
    assert not font.fixedPitch()
    assert font.styleHint() != QFont.StyleHint.Monospace
    assert main_window._zoom_controls._slider.accessibleName() == "Thumbnail size"


def _members_on_bar(window: MainWindow):
    return {action for action in window._toolbar.actions() if action.isVisible()}


def test_all_labels_show_at_1280_with_the_app_style_sheet(main_window, five_page_pdf, qtbot):
    _style_window(main_window)
    _open_loaded_window(main_window, five_page_pdf, qtbot, width=1280)
    qtbot.waitUntil(lambda: abs(main_window._toolbar.width() - 1280) < 10 and _toolbar_fits(main_window))
    qtbot.waitUntil(lambda: _refit_changes_nothing(main_window))
    on_bar, more = _command_bar_state(main_window)
    assert [key for key, _icon_only in on_bar] == _DROPPABLE_LABELS
    assert not [key for key, icon_only in on_bar if icon_only]
    for key in _COMMAND_BAR_LABELS:
        assert _label_style(main_window, key) == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert main_window._view_switch.isVisible()
    assert not more & {"preview", "tools"}


def test_width_estimate_matches_the_real_layout_and_labels_drop_only_when_needed(
    main_window, five_page_pdf, qtbot
):
    _style_window(main_window)
    _open_loaded_window(main_window, five_page_pdf, qtbot, width=1600)
    toolbar = main_window._toolbar
    spacer = main_window._toolbar_spacer
    for width in range(1600, MIN_WINDOW_WIDTH - 1, -23):
        _settle_at(qtbot, main_window, width)
        members = _members_on_bar(main_window)
        icon_only = main_window._toolbar_icon_only
        # Every member sits inside the bar, the last one included.
        assert _toolbar_fits(main_window), width
        last = max(
            (toolbar.widgetForAction(a) for a in members if toolbar.widgetForAction(a) is not None),
            key=lambda widget: widget.geometry().right(),
        )
        assert last.geometry().right() < toolbar.width(), width
        # The estimate the fit works from is the width the layout really uses:
        # the bar minus the spacer's free space.
        estimate = main_window._toolbar_width_for(members, icon_only)
        assert abs(estimate - (toolbar.width() - spacer.width())) <= 2, (width, estimate)
        # A label only goes when its width would not fit in the free space.
        bare = [a for a in main_window._toolbar_label_droppable if a in icon_only and toolbar.widgetForAction(a)]
        if bare and not any(
            action in main_window._toolbar_overflow_menu.actions()
            for action in main_window._toolbar_displaceable
        ):
            leftmost = bare[0]
            extra = main_window._toolbar_hint_widths[leftmost] - main_window._toolbar_icon_widths[leftmost]
            assert spacer.width() < extra, (width, spacer.width(), extra)


def test_selection_cell_leaves_the_bar_last_and_only_below_the_floor(
    main_window, five_page_pdf, qtbot
):
    _style_window(main_window)
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=MIN_WINDOW_WIDTH)
    tab.thumbnail_grid.selection_manager.select_single(0)
    qtbot.waitUntil(lambda: main_window._selection_toolbar_label.text() == "Page 1 selected")
    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    qtbot.waitUntil(
        lambda: main_window.size().width() == MIN_WINDOW_WIDTH and _toolbar_fits(main_window)
    )
    qtbot.waitUntil(lambda: _refit_changes_nothing(main_window))
    toolbar = main_window._toolbar
    actions = main_window._actions
    label = main_window._selection_toolbar_label
    assert label.isVisible() and label.text() == "Page 1 selected"
    for key in ("open", "save_as"):
        assert toolbar.widgetForAction(actions[key]).isVisible()
    assert main_window._toolbar_overflow.isVisible()
    assert _toolbar_fits(main_window)
    # Every command that has no room is in More while the cell is still showing.
    for key in ("delete_pages", "preview", "tools"):
        assert actions[key] in main_window._toolbar_overflow_menu.actions()

    # Only a window below the floor pushes the cell out, after every command.
    main_window.setMinimumSize(0, 0)
    main_window.resize(300, MIN_WINDOW_HEIGHT)
    qtbot.waitUntil(lambda: not label.isVisible() and _toolbar_fits(main_window))
    for action in main_window._toolbar_displaceable:
        assert action in main_window._toolbar_overflow_menu.actions()
    assert toolbar.widgetForAction(actions["save_as"]).isVisible()


def test_every_command_bar_label_is_inside_its_accessible_name(main_window):
    toolbar = main_window._toolbar
    for action in main_window._toolbar_label_actions:
        button = toolbar.widgetForAction(action)
        visible = action.iconText()
        assert visible, action.text()
        assert visible.casefold() in button.accessibleName().casefold(), (
            visible,
            button.accessibleName(),
        )


def test_rotate_commands_are_found_by_their_direction_in_the_palette(main_window):
    from pagedrop.ui.command_palette import ranked_actions

    actions = main_window._actions
    labelled = [action for action in actions.values() if action.text()]
    assert actions["rotate_ccw"] in ranked_actions(labelled, "counterclockwise")
    assert actions["rotate_cw"] in ranked_actions(labelled, "clockwise")
    assert ranked_actions(labelled, "rotate left")[0] is actions["rotate_ccw"]
    assert ranked_actions(labelled, "rotate right")[0] is actions["rotate_cw"]


def _menu_reachable_actions(window: MainWindow) -> set[int]:
    """Ids of every action in the menu bar, its submenus and the More overflow."""
    seen: set[int] = set()

    def walk(actions) -> None:
        for action in actions:
            seen.add(id(action))
            if action.menu() is not None:
                walk(action.menu().actions())

    walk(window.menuBar().actions())
    return seen


# Labelled actions with no menu entry: each has a shortcut that works with no
# menu open, and is still in the command palette.
_SHORTCUT_ONLY_ACTIONS = {
    "next_tab",
    "prev_tab",
    "new_tab",
    "go_to_page",
    "reset_zoom",
}


def test_no_registered_action_is_lost_from_menus_and_palette(main_window):
    from pagedrop.ui.command_palette import collect_actions

    registry = main_window._actions
    in_menu = _menu_reachable_actions(main_window)
    in_palette = {id(action) for action in collect_actions(main_window)}

    unlabelled = {key for key, action in registry.items() if not action.text().strip()}
    # The only label-less action is the viewer's Escape binding.
    assert unlabelled == {"escape"}

    for key, action in registry.items():
        if key in unlabelled:
            continue
        assert id(action) in in_palette, f"{key} is missing from the command palette"
        if key in _SHORTCUT_ONLY_ACTIONS:
            assert id(action) not in in_menu, f"{key} is in a menu: drop it from the exemptions"
        else:
            assert id(action) in in_menu, f"{key} is missing from every menu"

    for key in _SHORTCUT_ONLY_ACTIONS:
        assert not registry[key].shortcut().isEmpty(), f"{key} has no shortcut"


def test_view_menu_holds_preview_and_names_the_view_it_leads_to(
    main_window, five_page_pdf, qtbot
):
    view = _top_level_menu(main_window, "View")
    preview = main_window._actions["preview"]
    assert view.actions()[0] is preview
    assert preview.text() == "Preview"

    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=960)
    tab.thumbnail_grid.selection_manager.select_single(1)
    qtbot.waitUntil(preview.isEnabled)
    preview.trigger()
    qtbot.waitUntil(tab.is_viewer_mode)
    assert view.actions()[0].text() == "Back to grid"
    preview.trigger()
    qtbot.waitUntil(lambda: not tab.is_viewer_mode())
    assert view.actions()[0].text() == "Preview"


# --- editor side panes -------------------------------------------------------

_PANE_KEYS = {
    "sections": "toggle_sections",
    "document": "toggle_document_panel",
}


def _pane_action(window, pane: str):
    return window._actions[_PANE_KEYS[pane]]


def _widen(window, qtbot, width: int) -> None:
    window.resize(width, 680)
    qtbot.waitUntil(lambda: window._active_tab().width() >= width - 40)


def _open_wide_window(main_window, five_page_pdf, qtbot, width: int = 1200):
    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=width)
    qtbot.waitUntil(lambda: tab.width() >= width - 40)
    return tab


def test_pane_toggles_have_shortcuts_menu_entries_and_palette_entries(main_window):
    from pagedrop.ui.command_palette import collect_actions

    view = _top_level_menu(main_window, "View")
    in_palette = {id(action) for action in collect_actions(main_window)}
    expected = {
        "toggle_sections": ("Toggle sections", "Ctrl+Shift+B"),
        "toggle_document_panel": ("Toggle document panel", "Ctrl+Shift+I"),
    }
    for key, (label, shortcut) in expected.items():
        action = main_window._actions[key]
        assert action.text().replace("&", "") == label
        assert action.shortcut().toString() == shortcut
        assert action.isCheckable()
        assert action.toolTip()
        assert action in view.actions()
        assert id(action) in in_palette
        assert action.property("commandCategory") == "View"


def test_pane_toggles_are_disabled_without_a_document(main_window, five_page_pdf, qtbot):
    for pane in _PANE_KEYS:
        assert not _pane_action(main_window, pane).isEnabled()  # blank tab

    tab = _open_wide_window(main_window, five_page_pdf, qtbot)
    for pane in _PANE_KEYS:
        assert _pane_action(main_window, pane).isEnabled()

    tool_page = QWidget()
    tool_page.tool_page_id = "test-tool-panes"
    tool_page.WINDOW_TITLE = "Test tool"
    main_window._tab_manager.add_page(tool_page, "Test tool")
    for pane in _PANE_KEYS:
        assert not _pane_action(main_window, pane).isEnabled()

    main_window._tab_manager.setCurrentWidget(tab)
    for pane in _PANE_KEYS:
        assert _pane_action(main_window, pane).isEnabled()

    tab.close_loader()
    for pane in _PANE_KEYS:
        assert not _pane_action(main_window, pane).isEnabled()


def test_blank_tab_hides_both_panes_and_loading_shows_them(main_window, five_page_pdf, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    tab = main_window._active_tab()
    assert not tab.section_index.isVisible()
    assert not tab.document_panel.isVisible()

    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    main_window.resize(1200, 680)
    qtbot.waitUntil(lambda: tab.width() >= 1100)
    assert tab.section_index.isVisible()
    assert tab.document_panel.isVisible()

    tab.close_loader()
    assert not tab.section_index.isVisible()
    assert not tab.document_panel.isVisible()


def test_toggle_actions_drive_pane_visibility(main_window, five_page_pdf, qtbot):
    tab = _open_wide_window(main_window, five_page_pdf, qtbot)
    for pane, widget in (("sections", tab.section_index), ("document", tab.document_panel)):
        action = _pane_action(main_window, pane)
        assert widget.isVisible()
        assert action.isChecked()
        action.trigger()
        assert not widget.isVisible()
        assert not action.isChecked()
        action.trigger()
        assert widget.isVisible()
        assert action.isChecked()


def test_pane_choice_persists_to_a_new_window(main_window, five_page_pdf, qtbot):
    _open_wide_window(main_window, five_page_pdf, qtbot)
    _pane_action(main_window, "sections").trigger()
    _pane_action(main_window, "document").trigger()

    other = MainWindow()
    qtbot.addWidget(other)
    try:
        other._load_pdf(str(five_page_pdf))
        wait_for_pdf_loaded(qtbot, other)
        other.resize(1200, 680)
        other.show()
        qtbot.waitExposed(other, timeout=5000)
        tab = other._active_tab()
        qtbot.waitUntil(lambda: tab.width() >= 1100)
        assert not tab.section_index.isVisible()
        assert not tab.document_panel.isVisible()
        assert not _pane_action(other, "sections").isChecked()
        assert not _pane_action(other, "document").isChecked()
    finally:
        other._temp_manager.cleanup()


def test_another_tab_picks_up_the_choice_when_shown(main_window, five_page_pdf, qtbot):
    first = _open_wide_window(main_window, five_page_pdf, qtbot)
    main_window._new_blank_tab()
    second = main_window._active_tab()
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    qtbot.waitUntil(lambda: second.width() >= 1100)
    assert second.section_index.isVisible()

    _pane_action(main_window, "sections").trigger()
    assert not second.section_index.isVisible()
    main_window._tab_manager.setCurrentWidget(first)
    qtbot.waitUntil(lambda: not first.section_index.isVisible())
    assert not _pane_action(main_window, "sections").isChecked()
    assert first.document_panel.isVisible()
    assert _pane_action(main_window, "document").isChecked()


def test_check_state_follows_the_active_tab(main_window, five_page_pdf, qtbot):
    from pagedrop.ui.pdf_tab import DOCUMENT_PANEL_HIDE_BELOW

    first = _open_wide_window(main_window, five_page_pdf, qtbot)
    main_window._new_blank_tab()
    second = main_window._active_tab()
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    main_window.resize(DOCUMENT_PANEL_HIDE_BELOW - 100, 680)
    qtbot.waitUntil(lambda: second.width() < DOCUMENT_PANEL_HIDE_BELOW)
    action = _pane_action(main_window, "document")
    assert not action.isChecked()

    # Only the first tab has the panel turned on despite the narrow width.
    main_window._tab_manager.setCurrentWidget(first)
    qtbot.waitUntil(lambda: first.width() < DOCUMENT_PANEL_HIDE_BELOW)
    assert not action.isChecked()
    action.trigger()
    assert first.document_panel.isVisible()
    assert action.isChecked()

    main_window._tab_manager.setCurrentWidget(second)
    assert not second.document_panel.isVisible()
    assert not action.isChecked()
    main_window._tab_manager.setCurrentWidget(first)
    assert action.isChecked()


def test_remembered_widths_are_restored_and_saved_on_drag(main_window, five_page_pdf, qtbot):
    from pagedrop.ui.settings import document_panel_width, sections_width

    tab = _open_wide_window(main_window, five_page_pdf, qtbot)
    splitter = tab.workspace_splitter
    qtbot.waitUntil(lambda: splitter.sizes()[0] == 176 and splitter.sizes()[2] == 300)

    splitter.moveSplitter(220, 1)
    assert sections_width(0) == 220
    assert splitter.sizes()[0] == 220
    splitter.moveSplitter(splitter.width() - 340, 2)
    assert document_panel_width(0) == splitter.sizes()[2]
    assert 330 <= document_panel_width(0) <= 345

    # Hiding and showing again returns to the remembered widths.
    _pane_action(main_window, "sections").trigger()
    _pane_action(main_window, "sections").trigger()
    assert splitter.sizes()[0] == 220


def test_dragging_a_pane_towards_closed_keeps_its_remembered_width(
    main_window, five_page_pdf, qtbot
):
    from pagedrop.ui.pdf_tab import SIDE_PANE_MIN_WIDTH
    from pagedrop.ui.settings import sections_width

    tab = _open_wide_window(main_window, five_page_pdf, qtbot)
    splitter = tab.workspace_splitter
    qtbot.waitUntil(lambda: splitter.sizes()[0] == 176)
    splitter.moveSplitter(220, 1)
    assert sections_width(0) == 220

    splitter.moveSplitter(SIDE_PANE_MIN_WIDTH - 40, 1)
    assert sections_width(0) == 220

    splitter.moveSplitter(0, 1)
    _pane_action(main_window, "sections").trigger()
    assert splitter.sizes()[0] == 220


def test_dragging_a_pane_closed_counts_as_hiding_it(main_window, five_page_pdf, qtbot):
    from pagedrop.ui.settings import document_panel_visible, sections_visible

    tab = _open_wide_window(main_window, five_page_pdf, qtbot)
    splitter = tab.workspace_splitter
    splitter.moveSplitter(0, 1)
    assert not sections_visible()
    assert not _pane_action(main_window, "sections").isChecked()
    assert not tab.section_index.isVisible()
    assert document_panel_visible()

    splitter.moveSplitter(splitter.width(), 2)
    assert not document_panel_visible()
    assert not _pane_action(main_window, "document").isChecked()

    _pane_action(main_window, "sections").trigger()
    assert tab.section_index.isVisible()
    assert splitter.sizes()[0] == 176


def test_narrow_tab_collapses_document_panel_then_sections_and_widening_restores(
    main_window, five_page_pdf, qtbot
):
    from pagedrop.ui.pdf_tab import DOCUMENT_PANEL_HIDE_BELOW, SECTIONS_HIDE_BELOW
    from pagedrop.ui.settings import document_panel_visible, sections_visible

    assert SECTIONS_HIDE_BELOW < DOCUMENT_PANEL_HIDE_BELOW
    tab = _open_wide_window(main_window, five_page_pdf, qtbot)
    assert tab.section_index.isVisible() and tab.document_panel.isVisible()

    main_window.resize(DOCUMENT_PANEL_HIDE_BELOW - 100, 680)
    qtbot.waitUntil(lambda: tab.width() < DOCUMENT_PANEL_HIDE_BELOW)
    assert not tab.document_panel.isVisible()
    assert tab.section_index.isVisible()

    main_window.resize(SECTIONS_HIDE_BELOW - 60, 680)
    qtbot.waitUntil(lambda: tab.width() < SECTIONS_HIDE_BELOW)
    assert not tab.section_index.isVisible()
    assert not _pane_action(main_window, "sections").isChecked()

    # The narrow collapse never touched the remembered choice.
    assert sections_visible() and document_panel_visible()

    main_window.resize(1200, 680)
    qtbot.waitUntil(lambda: tab.section_index.isVisible() and tab.document_panel.isVisible())
    assert _pane_action(main_window, "sections").isChecked()
    assert _pane_action(main_window, "document").isChecked()


def test_toggling_a_pane_on_while_narrow_is_honoured_until_the_width_crosses_again(
    main_window, five_page_pdf, qtbot
):
    from pagedrop.ui.pdf_tab import DOCUMENT_PANEL_HIDE_BELOW

    tab = _open_wide_window(main_window, five_page_pdf, qtbot)
    main_window.resize(DOCUMENT_PANEL_HIDE_BELOW - 100, 680)
    qtbot.waitUntil(lambda: not tab.document_panel.isVisible())

    action = _pane_action(main_window, "document")
    assert not action.isChecked()
    action.trigger()
    assert tab.document_panel.isVisible()
    assert action.isChecked()

    # Resizing within the same side of the threshold keeps it.
    main_window.resize(DOCUMENT_PANEL_HIDE_BELOW - 140, 680)
    qtbot.waitUntil(lambda: tab.width() < DOCUMENT_PANEL_HIDE_BELOW - 100)
    assert tab.document_panel.isVisible()

    # Crossing the threshold and coming back applies the rule again.
    main_window.resize(1200, 680)
    qtbot.waitUntil(lambda: tab.width() >= DOCUMENT_PANEL_HIDE_BELOW)
    main_window.resize(DOCUMENT_PANEL_HIDE_BELOW - 100, 680)
    qtbot.waitUntil(lambda: not tab.document_panel.isVisible())


def test_toggling_a_pane_off_while_narrow_hides_it_for_good(main_window, five_page_pdf, qtbot):
    from pagedrop.ui.pdf_tab import DOCUMENT_PANEL_HIDE_BELOW
    from pagedrop.ui.settings import document_panel_visible

    tab = _open_wide_window(main_window, five_page_pdf, qtbot)
    main_window.resize(DOCUMENT_PANEL_HIDE_BELOW - 100, 680)
    qtbot.waitUntil(lambda: not tab.document_panel.isVisible())
    action = _pane_action(main_window, "document")
    action.trigger()
    action.trigger()
    assert not tab.document_panel.isVisible()
    assert not document_panel_visible()
    main_window.resize(1200, 680)
    qtbot.waitUntil(lambda: tab.width() >= DOCUMENT_PANEL_HIDE_BELOW)
    assert not tab.document_panel.isVisible()


def test_side_panes_do_not_raise_the_compact_floor_even_when_forced_on(
    main_window, five_page_pdf, qtbot
):
    tab = _open_wide_window(main_window, five_page_pdf, qtbot)
    main_window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    qtbot.waitUntil(lambda: main_window.width() == MIN_WINDOW_WIDTH)
    _pane_action(main_window, "sections").trigger()
    if not tab.section_index.isVisible():
        _pane_action(main_window, "sections").trigger()
    _pane_action(main_window, "document").trigger()
    if not tab.document_panel.isVisible():
        _pane_action(main_window, "document").trigger()
    assert tab.section_index.isVisible() and tab.document_panel.isVisible()
    assert main_window.minimumSizeHint().width() <= MIN_WINDOW_WIDTH
    assert main_window.width() == MIN_WINDOW_WIDTH


def test_tab_order_runs_sections_then_grid_then_document(main_window, five_page_pdf, qtbot):
    tab = _open_wide_window(main_window, five_page_pdf, qtbot)

    def chain(start):
        seen, widget = [], start
        while True:
            widget = widget.nextInFocusChain()
            if widget is start or widget in seen:
                return seen
            if widget.isVisibleTo(tab) and widget.focusPolicy() & Qt.FocusPolicy.TabFocus:
                seen.append(widget)

    sections = tab.section_index.focusProxy()
    document = tab.document_panel.focusProxy()
    order = chain(sections)
    assert order.index(tab.thumbnail_grid) < order.index(document)

    tab.show_preview_at(0)
    qtbot.waitUntil(tab.is_viewer_mode)
    order = chain(sections)
    assert tab.thumbnail_grid not in order
    viewer_positions = [i for i, w in enumerate(order) if tab.preview_widget.isAncestorOf(w) or w is tab.preview_widget]
    assert viewer_positions, "viewer takes focus between the panes"
    assert max(viewer_positions) < order.index(document)

    tab.close_preview()
    _pane_action(main_window, "document").trigger()
    assert document not in chain(sections)
