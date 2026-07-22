"""Onboarding & Help — tips overlay, shortcut reference, toolbar status tips."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QStatusTipEvent
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QToolBar

from pagedrop.ui.onboarding import (
    FIRST_RUN_TIPS,
    KeyboardShortcutsDialog,
    SHORTCUT_GROUPS,
)
from pagedrop.ui.settings import has_seen_tips, set_has_seen_tips


def test_has_seen_tips_pref_round_trip(isolated_settings):
    assert has_seen_tips() is False
    set_has_seen_tips(True)
    assert has_seen_tips() is True


def test_first_run_tips_content_covers_required_callouts():
    names = {name for name, _body in FIRST_RUN_TIPS}
    assert names == {"Open", "Drop zone", "Zoom", "Preview", "Tabs"}


def test_tips_overlay_dismiss_persists(isolated_settings, main_window, qtbot):
    assert has_seen_tips() is False
    main_window.show()
    qtbot.waitExposed(main_window)
    main_window._show_tips_overlay()
    assert main_window._tips_overlay.isVisible()

    got_it = main_window._tips_overlay.findChild(QPushButton, "TipsOverlayDismiss")
    assert got_it is not None
    qtbot.mouseClick(got_it, Qt.MouseButton.LeftButton)
    assert not main_window._tips_overlay.isVisible()
    assert has_seen_tips() is True


def test_testing_env_skips_auto_tips(isolated_settings, main_window, qtbot):
    # conftest sets PAGEDROP_TESTING=1; auto tips must not appear.
    qtbot.wait(50)
    assert not main_window._tips_overlay.isVisible()
    assert has_seen_tips() is False


def test_shortcut_groups_document_ctrl_tab_mru():
    tabs = dict(SHORTCUT_GROUPS)["Tabs"]
    by_label = dict(tabs)
    assert "Previous tab (MRU)" in by_label
    assert "Ctrl+Tab" in by_label["Previous tab (MRU)"]


def test_help_menu_keyboard_shortcuts_action(main_window):
    help_menus = [
        a.menu()
        for a in main_window.menuBar().actions()
        if a.menu() is not None and a.text().replace("&", "") == "Help"
    ]
    assert help_menus
    help_menu = help_menus[0]
    labels = {a.text().replace("&", "") for a in help_menu.actions()}
    assert "Keyboard Shortcuts" in labels
    assert "Show Tips" in labels

    action = next(
        a
        for a in help_menu.actions()
        if a.text().replace("&", "") == "Keyboard Shortcuts"
    )
    assert action.shortcut() == QKeySequence("Ctrl+/")


def test_keyboard_shortcuts_dialog_lists_categories(qtbot):
    dialog = KeyboardShortcutsDialog()
    qtbot.addWidget(dialog)
    joined = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Tabs" in joined
    assert "Previous tab (MRU)" in joined
    assert "Ctrl+Tab" in joined


_TOOLBAR_HINT_LABELS = {
    "Open",
    "Preview",
    "Select All",
    "Deselect All",
    "Move up",
    "Move down",
    "Delete page(s)",
    "Duplicate",
    "Rotate CW",
    "Rotate CCW",
}


def test_toolbar_actions_have_status_tips(main_window):
    toolbar = main_window.findChild(QToolBar)
    assert toolbar is not None
    for action in toolbar.actions():
        if action.isSeparator() or action.text() not in _TOOLBAR_HINT_LABELS:
            continue
        assert action.statusTip(), f"missing status tip on {action.text()!r}"
        assert action.toolTip() == action.statusTip()

    assert "Ctrl+scroll" in main_window._zoom_controls.statusTip()


def test_toolbar_hover_shows_status_tip(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    tip = main_window._select_all_action.statusTip()
    assert tip
    QApplication.sendEvent(main_window, QStatusTipEvent(tip))
    assert main_window.statusBar().currentMessage() == tip
