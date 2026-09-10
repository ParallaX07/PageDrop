"""Keyboard accessibility — toolbar arrows, tab order, menu mnemonics."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QToolButton

from pagedrop.ui.keyboard_nav import focusable_toolbar_widgets
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow
from tests.conftest import RENDER_TIMEOUT_MS, wait_for_pdf_loaded


def _toolbar_tool_buttons(toolbar) -> list[QToolButton]:
    """All QToolButtons for toolbar actions (ignore visibility/enabled)."""
    buttons: list[QToolButton] = []
    for action in toolbar.actions():
        widget = toolbar.widgetForAction(action)
        if isinstance(widget, QToolButton):
            buttons.append(widget)
    return buttons


def test_menu_mnemonics_are_unambiguous(main_window):
    menubar = main_window.menuBar()
    top_labels = [action.text() for action in menubar.actions()]
    assert "&File" in top_labels
    assert "&Merge PDFs" in top_labels
    assert "&Create PDF" in top_labels

    file_menu = next(
        action.menu()
        for action in menubar.actions()
        if action.text().replace("&", "") == "File"
    )
    file_labels = [
        action.text()
        for action in file_menu.actions()
        if not action.isSeparator()
    ]
    assert "&Open PDF" in file_labels
    assert "&Close tab" in file_labels
    assert "Save &as" in file_labels
    assert "New &window" in file_labels
    assert "E&xit" in file_labels

    def mnemonic_letters(labels: list[str]) -> list[str]:
        letters: list[str] = []
        for label in labels:
            amp = label.find("&")
            if amp >= 0 and amp + 1 < len(label):
                letters.append(label[amp + 1].casefold())
        return letters

    top_mnemonics = mnemonic_letters(top_labels)
    assert len(top_mnemonics) == len(set(top_mnemonics))
    file_mnemonics = mnemonic_letters(file_labels)
    assert len(file_mnemonics) == len(set(file_mnemonics))


def test_toolbar_arrow_keys_move_focus(main_window, five_page_pdf, qtbot):
    toolbar = main_window._toolbar
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: main_window._active_tab().loader is not None)

    # show() — showMinimized can leave toolbar children !isVisible() on some WPAs.
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)

    buttons = [
        w for w in focusable_toolbar_widgets(toolbar) if isinstance(w, QToolButton)
    ]
    assert len(buttons) >= 2

    buttons[0].setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(lambda: buttons[0].hasFocus(), timeout=2000)

    qtbot.keyClick(buttons[0], Qt.Key.Key_Right)
    assert buttons[1].hasFocus()

    qtbot.keyClick(buttons[1], Qt.Key.Key_Left)
    assert buttons[0].hasFocus()


def test_status_bar_is_not_tab_focusable(main_window):
    assert main_window.statusBar().focusPolicy() == Qt.FocusPolicy.NoFocus
    assert main_window._progress_bar.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_toolbar_buttons_use_strong_focus(main_window, five_page_pdf, qtbot):
    toolbar = main_window._toolbar
    assert hasattr(toolbar, "_pagedrop_arrow_nav")

    buttons = _toolbar_tool_buttons(toolbar)
    assert buttons
    for button in buttons:
        assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus

    assert toolbar.isHidden()
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: main_window._active_tab().loader is not None)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert focusable_toolbar_widgets(toolbar)


def test_toolbar_overflow_menu_restores_focus_to_its_invoker(
    main_window, five_page_pdf, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: main_window._active_tab().loader is not None)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)

    invoker = main_window._toolbar_overflow
    invoker.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(invoker.hasFocus)
    menu = invoker.menu()
    assert menu is not None
    menu.popup(invoker.mapToGlobal(invoker.rect().bottomLeft()))
    qtbot.waitUntil(menu.isVisible)
    menu.hide()
    qtbot.waitUntil(invoker.hasFocus)


def test_viewer_tab_order_and_escape_returns_to_grid(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    tab = main_window._active_tab()
    assert tab is not None
    main_window._open_preview()
    qtbot.waitUntil(
        lambda: tab.is_viewer_mode() and len(tab.viewer_widget._tiles) >= 1,
        timeout=RENDER_TIMEOUT_MS,
    )
    viewer = tab.viewer_widget

    viewer._search_edit.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.keyClick(viewer._search_edit, Qt.Key.Key_Tab)
    previous = next(
        button
        for button in viewer._find_group.findChildren(QToolButton)
        if button.accessibleName() == "Previous search result"
    )
    qtbot.waitUntil(previous.hasFocus, timeout=2000)

    viewer.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.keyClick(viewer, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not tab.is_viewer_mode(), timeout=2000)
    assert tab.content_stack.currentWidget() is tab.thumbnail_grid


def test_tools_hub_toolbar_arrow_keys(qtbot):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window, timeout=5000)

    toolbar = window._toolbar
    assert hasattr(toolbar, "_pagedrop_arrow_nav")
    # Search stays a normal line edit (arrows move the caret); Compact gets StrongFocus.
    assert window._compact_btn.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert window._compact_btn in focusable_toolbar_widgets(toolbar)


def test_tool_shell_run_lives_in_actions_row(qtbot):
    """R11: Run sits in #ToolShellActions — not a one-button QToolBar."""
    from PyQt6.QtWidgets import QPushButton, QToolBar

    shell = ToolShellWindow(title="Demo", description="Test shell")
    qtbot.addWidget(shell)
    shell.show()
    qtbot.waitExposed(shell, timeout=5000)
    assert shell._actions_host.objectName() == "ToolShellActions"
    assert shell._actions_host.isVisible()
    assert shell._run_btn.parentWidget() is shell._actions_host
    assert shell._run_btn.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert shell.findChild(QToolBar, "ToolShellToolbar") is None
    # Only one Run button on the shell.
    runs = [
        w
        for w in shell.findChildren(QPushButton)
        if w.objectName() == "ToolbarPrimary" and w.text() == "Run"
    ]
    assert runs == [shell._run_btn]
