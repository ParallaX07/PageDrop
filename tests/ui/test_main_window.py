"""Phase 3 unit tests — MainWindow."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QFont, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QPushButton,
    QToolBar,
    QToolButton,
    QWidget,
)

from pagedrop.ui.main_window import MainWindow


def _file_menu_actions(window: MainWindow):
    menubar = window.menuBar()
    for action in menubar.actions():
        if action.text().replace("&", "") == "File":
            return list(action.menu().actions())
    raise AssertionError("File menu not found")


def _find_action_by_text(actions, *candidates: str):
    normalized = {text.replace("&", "") for text in candidates}
    for action in actions:
        label = action.text().replace("&", "")
        if label in normalized:
            return action
    raise AssertionError(f"No action matching {candidates}")


def test_window_title_default(main_window):
    assert main_window.windowTitle() == "PageDrop"


def test_custom_title_controls_are_in_the_menu_bar(main_window, qtbot):
    if QApplication.platformName() == "offscreen":
        assert not main_window.windowFlags() & Qt.WindowType.FramelessWindowHint
    else:
        assert main_window.windowFlags() & Qt.WindowType.FramelessWindowHint
    title = main_window.findChild(type(main_window._title_label), "WindowTitle")
    assert title.text() == "PageDrop"
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
        <= main_window.menuBar().rect().right()
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


def test_shell_uses_rendered_geometry_after_menu_font_growth(main_window, qtbot):
    main_window.resize(720, 480)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    menu_bar = main_window.menuBar()
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
