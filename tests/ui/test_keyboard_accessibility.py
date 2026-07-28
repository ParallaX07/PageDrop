"""Keyboard accessibility — toolbar arrows, tab order, menu mnemonics."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QToolButton

from pagedrop.ui.keyboard_nav import focusable_toolbar_widgets


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


def test_toolbar_arrow_keys_move_focus(main_window, qtbot):
    toolbar = main_window._toolbar
    # Blank tab only enables Open; enable Preview so two arrow targets exist.
    main_window._preview_action.setEnabled(True)

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


def test_toolbar_buttons_use_strong_focus(main_window, qtbot):
    toolbar = main_window._toolbar
    assert hasattr(toolbar, "_pagedrop_arrow_nav")

    buttons = _toolbar_tool_buttons(toolbar)
    assert buttons
    for button in buttons:
        assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus

    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert focusable_toolbar_widgets(toolbar)
