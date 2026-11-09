"""Page focus hides the tab row and toolbar while Pages view shows a document."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QToolButton, QWidget

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_viewer import PdfViewerWidget
from pagedrop.ui.settings import page_focus, set_page_focus
from tests.conftest import wait_for_pdf_loaded

SHORTCUT = "Ctrl+Shift+F"


def _open(window, pdf, qtbot, *, width: int = 1280, height: int = 800):
    window._load_pdf(str(pdf))
    wait_for_pdf_loaded(qtbot, window)
    window.resize(width, height)
    window.show()
    qtbot.waitExposed(window, timeout=5000)
    tab = window._active_tab()
    qtbot.waitUntil(lambda: tab.width() >= width - 40)
    return tab


def _pages_view(tab, qtbot):
    tab.show_preview_at(0)
    qtbot.waitUntil(tab.is_viewer_mode)
    return tab.preview_widget


def _rows(window):
    tab_manager = window._tab_manager
    return (
        tab_manager.tabBar(),
        tab_manager.cornerWidget(Qt.Corner.TopRightCorner),
        window._toolbar,
    )


def _rows_hidden(window) -> bool:
    return all(not row.isVisible() for row in _rows(window))


def _rows_shown(window) -> bool:
    return all(row.isVisible() for row in _rows(window))


def _bar_items(viewer):
    layout = viewer._toolbar.layout()
    return [layout.itemAt(i).widget() for i in range(layout.count())]


def _focus_on(window, qtbot):
    window._page_focus_action.trigger()
    qtbot.waitUntil(lambda: _rows_hidden(window))


# --- the action ----------------------------------------------------------------


def test_action_has_shortcut_menu_and_palette_entries(main_window):
    from pagedrop.ui.command_palette import collect_actions

    action = main_window._actions["toggle_page_focus"]
    assert action is main_window._page_focus_action
    assert action.text().replace("&", "") == "Focus on page"
    assert action.shortcut().toString() == SHORTCUT
    assert action.isCheckable() and not action.isChecked()
    assert action in main_window.actions()
    assert action.property("commandCategory") == "View"
    assert id(action) in {id(a) for a in collect_actions(main_window)}
    view = next(
        a.menu() for a in main_window.menuBar().actions() if a.text().replace("&", "") == "View"
    )
    assert action in view.actions()
    assert SHORTCUT not in {
        a.shortcut().toString()
        for key, a in main_window._actions.items()
        if key != "toggle_page_focus"
    }


def test_action_is_enabled_only_in_pages_view_with_a_document(
    main_window, five_page_pdf, qtbot
):
    action = main_window._page_focus_action
    assert not action.isEnabled()  # blank tab

    tab = _open(main_window, five_page_pdf, qtbot)
    assert not action.isEnabled()  # grid

    _pages_view(tab, qtbot)
    assert action.isEnabled()

    tab.close_preview()
    qtbot.waitUntil(lambda: not action.isEnabled())

    tool_page = QWidget()
    tool_page.tool_page_id = "test-tool-focus"
    tool_page.WINDOW_TITLE = "Test tool"
    main_window._tab_manager.add_page(tool_page, "Test tool")
    assert not action.isEnabled()


# --- hiding and restoring the rows --------------------------------------------


def test_toggle_hides_the_rows_and_gives_the_page_more_height(
    main_window, five_page_pdf, qtbot
):
    tab = _open(main_window, five_page_pdf, qtbot)
    viewer = _pages_view(tab, qtbot)
    qtbot.waitUntil(lambda: _rows_shown(main_window))
    before = tab.content_stack.height()
    toolbar_height = main_window._toolbar.height()
    action = main_window._page_focus_action
    assert not action.isChecked()

    action.trigger()
    qtbot.waitUntil(lambda: _rows_hidden(main_window))
    assert action.isChecked()
    assert page_focus() is True
    assert main_window._title_bar.isVisible()
    assert main_window.menuBar().isVisible()
    assert viewer._toolbar.isVisible()
    qtbot.waitUntil(lambda: tab.content_stack.height() >= before + toolbar_height)

    action.trigger()
    qtbot.waitUntil(lambda: _rows_shown(main_window))
    assert not action.isChecked()
    assert page_focus() is False
    qtbot.waitUntil(lambda: tab.content_stack.height() == before)


def test_the_shortcut_toggles_focus_from_the_viewer(main_window, five_page_pdf, qtbot):
    tab = _open(main_window, five_page_pdf, qtbot)
    viewer = _pages_view(tab, qtbot)
    main_window.activateWindow()
    viewer.setFocus()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is main_window)

    qtbot.keyClick(
        viewer,
        Qt.Key.Key_F,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    qtbot.waitUntil(lambda: _rows_hidden(main_window))
    qtbot.keyClick(
        viewer,
        Qt.Key.Key_F,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    qtbot.waitUntil(lambda: _rows_shown(main_window))


def _exit_by_escape(window, tab, qtbot):
    qtbot.keyClick(tab.preview_widget, Qt.Key.Key_Escape)


def _exit_by_viewer_closed(window, tab, qtbot):
    tab.preview_widget.closed.emit()


def _exit_by_preview_action(window, tab, qtbot):
    window._open_preview()


def _exit_by_close_preview(window, tab, qtbot):
    tab.close_preview()


def _exit_by_new_tab(window, tab, qtbot):
    window._new_blank_tab()


def _exit_by_tab_switch(window, tab, qtbot):
    window._switch_to_next_tab()


def _exit_by_tab_close(window, tab, qtbot):
    window._close_tab()


def _exit_by_document_close(window, tab, qtbot):
    tab.close_loader()


@pytest.mark.parametrize(
    "leave",
    [
        _exit_by_escape,
        _exit_by_viewer_closed,
        _exit_by_preview_action,
        _exit_by_close_preview,
        _exit_by_new_tab,
        _exit_by_tab_switch,
        _exit_by_tab_close,
        _exit_by_document_close,
    ],
)
def test_every_way_out_of_pages_view_restores_the_rows_and_keeps_the_preference(
    main_window, five_page_pdf, qtbot, leave
):
    tab = _open(main_window, five_page_pdf, qtbot)
    if leave in (_exit_by_tab_switch, _exit_by_tab_close):
        main_window._new_blank_tab()
        main_window._tab_manager.setCurrentWidget(tab)
    _pages_view(tab, qtbot)
    _focus_on(main_window, qtbot)

    leave(main_window, tab, qtbot)
    tab_bar, corner, toolbar = _rows(main_window)
    qtbot.waitUntil(lambda: tab_bar.isVisible() and corner.isVisible())
    # A blank tab has no toolbar; every other way out brings it back.
    active = main_window._active_tab()
    assert toolbar.isVisible() == (active is not None and not active.is_blank)
    assert page_focus() is True


def test_reentering_pages_view_with_the_preference_on_hides_the_rows_again(
    main_window, five_page_pdf, qtbot
):
    tab = _open(main_window, five_page_pdf, qtbot)
    _pages_view(tab, qtbot)
    _focus_on(main_window, qtbot)
    tab.close_preview()
    qtbot.waitUntil(lambda: _rows_shown(main_window))

    tab.show_preview_at(0)
    qtbot.waitUntil(lambda: _rows_hidden(main_window))
    assert page_focus() is True


def test_a_window_opens_with_the_preference_and_hides_rows_only_in_pages_view(
    isolated_settings, five_page_pdf, qtbot
):
    set_page_focus(True)
    window = MainWindow()
    qtbot.addWidget(window)
    try:
        window.show()
        qtbot.waitExposed(window, timeout=5000)
        assert window._page_focus_action.isChecked()
        assert not window._page_focus_action.isEnabled()
        assert window._tab_manager.tabBar().isVisible()

        tab = _open(window, five_page_pdf, qtbot)
        assert window._tab_manager.tabBar().isVisible() and window._toolbar.isVisible()
        _pages_view(tab, qtbot)
        qtbot.waitUntil(lambda: _rows_hidden(window))
    finally:
        window._temp_manager.cleanup()


# --- one gate for the toolbar -------------------------------------------------


def test_the_toolbar_stays_hidden_while_focused_however_it_is_synced(
    main_window, five_page_pdf, qtbot
):
    tab = _open(main_window, five_page_pdf, qtbot)
    _pages_view(tab, qtbot)
    _focus_on(main_window, qtbot)

    main_window._sync_toolbar_from_active_tab()
    main_window._set_toolbar_host(tab)
    tab.attach_context_toolbar(main_window._toolbar)
    main_window._update_toolbar_visibility()
    main_window._set_chrome_visible(True)
    assert _rows_hidden(main_window)

    # Dragging a window wider or narrower must not bring it back either.
    main_window.resize(1000, 700)
    qtbot.waitUntil(lambda: main_window.width() <= 1000)
    main_window._sync_pane_actions()
    assert _rows_hidden(main_window)


def test_leaving_focus_keeps_the_toolbar_hidden_when_menu_and_toolbar_are_hidden(
    main_window, five_page_pdf, qtbot
):
    tab = _open(main_window, five_page_pdf, qtbot)
    _pages_view(tab, qtbot)
    _focus_on(main_window, qtbot)
    main_window._chrome_visible_action.trigger()  # Ctrl+Shift+H: hide menu and toolbar
    assert not main_window._chrome_visible_action.isChecked()

    tab.close_preview()
    qtbot.waitUntil(lambda: main_window._tab_manager.tabBar().isVisible())
    assert not main_window._toolbar.isVisible()

    main_window._chrome_visible_action.trigger()
    qtbot.waitUntil(main_window._toolbar.isVisible)


def test_blank_and_tool_tabs_never_hide_the_rows(main_window, five_page_pdf, qtbot):
    set_page_focus(True)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    main_window._sync_pane_actions()
    assert main_window._tab_manager.tabBar().isVisible()
    assert not main_window._toolbar.isVisible()  # a blank tab has no toolbar

    tab = _open(main_window, five_page_pdf, qtbot)
    tool_page = QWidget()
    tool_page.tool_page_id = "test-tool-focus-rows"
    tool_page.WINDOW_TITLE = "Test tool"
    main_window._tab_manager.add_page(tool_page, "Test tool")
    assert main_window._tab_manager.tabBar().isVisible()
    assert main_window._tab_manager.cornerWidget(Qt.Corner.TopRightCorner).isVisible()

    main_window._tab_manager.setCurrentWidget(tab)
    _pages_view(tab, qtbot)
    qtbot.waitUntil(lambda: _rows_hidden(main_window))
    main_window._tab_manager.setCurrentWidget(tool_page)
    qtbot.waitUntil(lambda: main_window._tab_manager.tabBar().isVisible())
    assert main_window._tab_manager.cornerWidget(Qt.Corner.TopRightCorner).isVisible()


# --- the viewer button --------------------------------------------------------


def test_tooltip_icon_and_name_flip_with_the_state(main_window, five_page_pdf, qtbot):
    tab = _open(main_window, five_page_pdf, qtbot)
    viewer = _pages_view(tab, qtbot)
    action, button = main_window._page_focus_action, viewer._focus_button
    off_icon = button.icon().pixmap(16, 16).toImage()

    assert action.toolTip() == action.statusTip() == f"Focus on page ({SHORTCUT})"
    assert button.toolTip() == f"Focus on page ({SHORTCUT})"
    assert button.accessibleName() == "Focus on page"

    button.click()
    qtbot.waitUntil(lambda: _rows_hidden(main_window))
    assert action.toolTip() == action.statusTip() == f"Exit focus ({SHORTCUT})"
    assert button.toolTip() == f"Exit focus ({SHORTCUT})"
    assert button.accessibleName() == "Exit focus"
    assert button.isChecked()
    assert button.icon().pixmap(16, 16).toImage() != off_icon

    button.click()
    qtbot.waitUntil(lambda: _rows_shown(main_window))
    assert button.accessibleName() == "Focus on page"
    assert button.icon().pixmap(16, 16).toImage() == off_icon


def test_the_icon_is_retinted_when_the_theme_changes(main_window, five_page_pdf, qtbot):
    from pagedrop.ui import icons

    tab = _open(main_window, five_page_pdf, qtbot)
    viewer = _pages_view(tab, qtbot)
    before = viewer._focus_button.icon().pixmap(16, 16).toImage()
    seen = []
    original = icons.icon

    def spy(name, **kwargs):
        seen.append(name)
        return original(name, **kwargs)

    icons.icon = spy
    try:
        main_window._refresh_action_icons()
    finally:
        icons.icon = original
    assert "arrows-out" in seen
    assert viewer._focus_button.icon().pixmap(16, 16).toImage() == before


def test_the_button_sits_just_left_of_the_right_sidebar_toggle(
    main_window, five_page_pdf, qtbot
):
    tab = _open(main_window, five_page_pdf, qtbot)
    viewer = _pages_view(tab, qtbot)
    items = _bar_items(viewer)
    assert items[-1] is viewer._sidebar_right_button
    assert items[-2] is viewer._focus_button
    assert viewer._focus_button.objectName() == "ToolbarSidebarToggle"
    assert viewer._focus_button.defaultAction() is main_window._page_focus_action
    assert viewer._focus_button.isVisible()
    assert viewer._focus_button.geometry().right() < viewer._sidebar_right_button.x()

    chain, widget = [], viewer._sidebar_left_button
    for _ in range(60):
        chain.append(widget)
        widget = widget.nextInFocusChain()
        if widget is viewer._sidebar_left_button:
            break
    assert chain.index(viewer._print_button) < chain.index(viewer._focus_button)
    assert chain.index(viewer._focus_button) < chain.index(viewer._sidebar_right_button)


def test_the_viewer_bar_counts_the_buttons_width(main_window, five_page_pdf, qtbot):
    tab = _open(main_window, five_page_pdf, qtbot)
    viewer = _pages_view(tab, qtbot)
    with_button = viewer._toolbar_width_for(viewer._layout_buttons, True)
    viewer._focus_button.hide()
    without = viewer._toolbar_width_for(viewer._layout_buttons, True)
    assert with_button >= without + viewer._focus_button.sizeHint().width()


def test_a_tab_moved_to_another_window_rebinds_the_button(
    main_window, five_page_pdf, qtbot
):
    tab = _open(main_window, five_page_pdf, qtbot)
    viewer = tab.preview_widget
    other = MainWindow()
    qtbot.addWidget(other)
    try:
        other.show()
        qtbot.waitExposed(other, timeout=5000)
        other._adopt_tab(tab)
        qtbot.waitUntil(lambda: other._active_tab() is tab)
        _pages_view(tab, qtbot)

        assert viewer._focus_button.defaultAction() is other._page_focus_action
        assert viewer._focus_button.defaultAction() is not main_window._page_focus_action
        viewer._focus_button.click()
        qtbot.waitUntil(lambda: _rows_hidden(other))
        assert other._page_focus_action.isChecked()
    finally:
        other._temp_manager.cleanup()


def test_a_standalone_viewer_shows_no_focus_button(qtbot):
    viewer = PdfViewerWidget()
    qtbot.addWidget(viewer)
    viewer.resize(900, 400)
    viewer.show()
    qtbot.waitExposed(viewer)
    assert not viewer._focus_button.isVisible()
    assert viewer._focus_button.defaultAction() is None


# --- keyboard ----------------------------------------------------------------


def test_focus_leaves_a_hiding_row_for_the_viewer(main_window, five_page_pdf, qtbot):
    tab = _open(main_window, five_page_pdf, qtbot)
    viewer = _pages_view(tab, qtbot)
    main_window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is main_window)
    open_button = main_window._toolbar.widgetForAction(main_window._actions["open"])
    assert isinstance(open_button, QToolButton)
    open_button.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(lambda: QApplication.focusWidget() is open_button)

    main_window._page_focus_action.trigger()
    qtbot.waitUntil(lambda: _rows_hidden(main_window))
    focus = QApplication.focusWidget()
    assert focus is viewer or viewer.isAncestorOf(focus)


def test_hidden_toolbar_controls_are_not_tab_stops(main_window, five_page_pdf, qtbot):
    from pagedrop.ui.keyboard_nav import focusable_toolbar_widgets

    tab = _open(main_window, five_page_pdf, qtbot)
    _pages_view(tab, qtbot)
    assert focusable_toolbar_widgets(main_window._toolbar)
    _focus_on(main_window, qtbot)
    assert focusable_toolbar_widgets(main_window._toolbar) == []

    main_window._apply_tab_order()
    chain, widget = [], main_window._tab_manager
    for _ in range(300):
        widget = widget.nextInFocusChain()
        if widget is main_window._tab_manager:
            break
        chain.append(widget)
    toolbar = main_window._toolbar
    assert not any(w.isVisible() and toolbar.isAncestorOf(w) for w in chain)


def test_save_as_shortcut_still_works_while_focused(
    main_window, five_page_pdf, qtbot, monkeypatch
):
    tab = _open(main_window, five_page_pdf, qtbot)
    viewer = _pages_view(tab, qtbot)
    _focus_on(main_window, qtbot)
    main_window.activateWindow()
    viewer.setFocus()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is main_window)
    asked = []

    def fake_dialog(*args, **kwargs):
        asked.append(args)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake_dialog))
    assert main_window._save_as_action.shortcut().toString() == "Ctrl+Shift+S"
    qtbot.keyClick(
        viewer,
        Qt.Key.Key_S,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    qtbot.waitUntil(lambda: bool(asked))


# --- chrome ------------------------------------------------------------------


def test_the_title_row_stays_usable_while_focused(main_window, five_page_pdf, qtbot):
    tab = _open(main_window, five_page_pdf, qtbot)
    _pages_view(tab, qtbot)
    _focus_on(main_window, qtbot)

    assert main_window._title_bar.isVisible()
    buttons = main_window._window_controls.findChildren(QToolButton)
    assert buttons and all(button.isVisible() for button in buttons)
    maximize = main_window.findChild(QToolButton, "WindowMaximize")
    maximize.click()
    qtbot.waitUntil(main_window.isMaximized)
    maximize.click()
    qtbot.waitUntil(lambda: not main_window.isMaximized())
    assert _rows_hidden(main_window)


def test_the_floating_message_follows_the_taller_page_area(
    main_window, five_page_pdf, qtbot
):
    tab = _open(main_window, five_page_pdf, qtbot)
    _pages_view(tab, qtbot)
    main_window._transient_status("Copied page text")
    pill = main_window._floating.pill
    qtbot.waitUntil(pill.isVisible)
    _focus_on(main_window, qtbot)

    def inside() -> bool:
        stack = tab.content_stack
        area_bottom = stack.mapTo(main_window, stack.rect().bottomLeft()).y()
        pill_bottom = pill.mapTo(main_window, pill.rect().bottomLeft()).y()
        return 0 <= area_bottom - pill_bottom <= 24

    qtbot.waitUntil(inside)
