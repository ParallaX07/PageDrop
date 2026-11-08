"""Onboarding & Help — tips overlay, shortcut reference, toolbar status tips."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QKeySequence, QStatusTipEvent
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QScrollArea, QToolBar, QWidget

from pagedrop.ui.command_palette import action_label
from pagedrop.ui.onboarding import (
    FIRST_RUN_TIPS,
    KeyboardShortcutsDialog,
    show_context_hint,
)
from pagedrop.ui.settings import (
    KEY_CONTEXT_HINT_SELECTION_EXPORT,
    has_seen_context_hint,
    has_seen_tips,
    set_has_seen_tips,
)


def test_has_seen_tips_pref_round_trip(isolated_settings):
    assert has_seen_tips() is False
    set_has_seen_tips(True)
    assert has_seen_tips() is True


def test_first_run_tips_stay_essential():
    names = {name for name, _body in FIRST_RUN_TIPS}
    assert names == {"Open", "Drop zone"}


def test_context_hint_shows_once_without_taking_focus(isolated_settings, qtbot):
    host = QWidget()
    host.resize(400, 240)
    anchor = QPushButton("Export", host)
    anchor.move(20, 20)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)

    hint = show_context_hint(
        host,
        anchor,
        KEY_CONTEXT_HINT_SELECTION_EXPORT,
        "Drag selected pages to a folder to export them as PDF files.",
    )
    assert hint is not None and hint.isVisible()
    assert hint.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert has_seen_context_hint(KEY_CONTEXT_HINT_SELECTION_EXPORT)
    assert show_context_hint(host, anchor, KEY_CONTEXT_HINT_SELECTION_EXPORT, "Again") is None


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


def _dialog_rows(dialog):
    names = [lab.text() for lab in dialog.findChildren(QLabel, "ShortcutAction")]
    keys = [lab.text() for lab in dialog.findChildren(QLabel, "ShortcutKeys")]
    assert len(names) == len(keys)
    return list(zip(names, keys, strict=True))


def test_shortcut_dialog_lists_every_shortcut_action_once(main_window, qtbot):
    dialog = KeyboardShortcutsDialog(main_window._actions.values(), main_window)
    qtbot.addWidget(dialog)
    rows = _dialog_rows(dialog)
    names = [name for name, _ in rows]
    for action in main_window._actions.values():
        label = action_label(action)
        if label and action.shortcuts():
            assert names.count(label) == 1, label
            expected = ", ".join(
                s.toString(QKeySequence.SequenceFormat.NativeText)
                for s in action.shortcuts()
            )
            assert dict(rows)[label] == expected
        elif label:
            assert label not in names, f"{label!r} has no shortcut"
    assert dict(rows)["Previous tab (MRU)"] == QKeySequence("Ctrl+Tab").toString(
        QKeySequence.SequenceFormat.NativeText
    )
    assert "Tools" in dict(rows)


def test_shortcut_dialog_follows_changed_shortcut(main_window, qtbot):
    main_window._actions["go_to_page"].setShortcut(QKeySequence("Ctrl+Alt+J"))
    dialog = KeyboardShortcutsDialog(main_window._actions.values(), main_window)
    qtbot.addWidget(dialog)
    expected = QKeySequence("Ctrl+Alt+J").toString(QKeySequence.SequenceFormat.NativeText)
    assert dict(_dialog_rows(dialog))["Go to page"] == expected
    assert QKeySequence("Ctrl+G").toString(QKeySequence.SequenceFormat.NativeText) not in [
        keys for _, keys in _dialog_rows(dialog)
    ]


def test_shortcut_dialog_keeps_gestures_and_drops_pages_menu_pointer(main_window, qtbot):
    dialog = KeyboardShortcutsDialog(main_window._actions.values(), main_window)
    qtbot.addWidget(dialog)
    rows = dict(_dialog_rows(dialog))
    assert rows["Preview page"] == "Enter · double-click"
    assert rows["Thumbnail zoom"] == "Ctrl+scroll"
    assert rows["Clear selection or close preview"] == "Esc"
    assert rows["Select a range of pages"] == "Shift+click"
    assert rows["Add or remove a page from the selection"] == "Ctrl+click"
    assert "Arrow keys" in rows.values()
    joined = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Pages menu" not in joined
    assert "Select pages" not in rows  # no shortcut, so no row


def test_help_menu_keyboard_shortcuts_action(main_window):
    help_menus = [
        a.menu()
        for a in main_window.menuBar().actions()
        if a.menu() is not None and a.text().replace("&", "") == "Help"
    ]
    assert help_menus
    help_menu = help_menus[0]
    labels = {a.text().replace("&", "") for a in help_menu.actions()}
    assert "Keyboard shortcuts" in labels
    assert "Show tips" in labels

    action = next(
        a
        for a in help_menu.actions()
        if a.text().replace("&", "") == "Keyboard shortcuts"
    )
    assert action.shortcut() == QKeySequence("Ctrl+/")


def test_help_about_shows_current_application_version(main_window, monkeypatch):
    app = QApplication.instance()
    previous = app.applicationVersion()
    app.setApplicationVersion("1.2.3")
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box) or 0)
    try:
        help_menu = next(
            action.menu()
            for action in main_window.menuBar().actions()
            if action.text().replace("&", "") == "Help"
        )
        about = next(
            action for action in help_menu.actions()
            if action.text().replace("&", "") == "About PageDrop"
        )
        about.trigger()
        assert len(shown) == 1
        box = shown[0]
        assert box.parent() is main_window
        assert box.windowTitle() == "About PageDrop"
        assert "PageDrop version 1.2.3" in box.text()
        assert "AGPL-3.0-or-later" in box.text()
        assert "https://github.com/ParallaX07/PageDrop/tree/v1.2.3" in box.text()
        assert "Copyright (C) PageDrop contributors" in box.text()
        assert "This program comes with ABSOLUTELY NO WARRANTY." in box.text()
        assert 'href="https://github.com/ParallaX07/PageDrop/blob/v1.2.3/LICENSE">Read the licence<' in box.text()
        assert box.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        label = box.findChild(QLabel, "qt_msgbox_label")
        assert label.openExternalLinks()
        flags = label.textInteractionFlags()
        assert flags & Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        assert flags & Qt.TextInteractionFlag.LinksAccessibleByMouse
        # Tab must be able to land on the link label.
        box.show()
        box.activateWindow()
        reached = False
        for _ in range(6):
            if box.focusWidget() is label:
                reached = True
                break
            box.focusNextChild()
        box.close()
        assert reached
    finally:
        app.setApplicationVersion(previous)


def test_keyboard_shortcuts_dialog_lists_categories(main_window, qtbot):
    dialog = KeyboardShortcutsDialog(main_window._actions.values(), main_window)
    qtbot.addWidget(dialog)
    headings = [lab.text() for lab in dialog.findChildren(QLabel, "ShortcutCategory")]
    assert headings == ["Document", "Pages", "View", "Tools", "Mouse and keyboard"]


def test_keyboard_shortcuts_dialog_scrolls_in_a_small_parent(main_window, qtbot):
    main_window.resize(480, 320)
    dialog = KeyboardShortcutsDialog(main_window._actions.values(), main_window)
    qtbot.addWidget(dialog)
    dialog.resize(dialog.minimumSize())
    dialog.show()
    qtbot.waitExposed(dialog)
    scroll = dialog.findChild(QScrollArea)
    assert scroll is not None
    assert scroll.verticalScrollBar().maximum() > 0
    assert dialog.findChild(QPushButton).isVisible()


_TOOLBAR_HINT_LABELS = {
    "Open PDF",
    "Preview",
    "Select all",
    "Clear selection",
    "Move up",
    "Move down",
    "Move to…",
    "Delete selected pages",
    "Duplicate selected pages",
    "Rotate clockwise",
    "Rotate counterclockwise",
}


def test_toolbar_actions_have_status_tips(main_window):
    toolbar = main_window.findChild(QToolBar)
    assert toolbar is not None
    for action in toolbar.actions():
        label = action.text().replace("&", "")
        if action.isSeparator() or label not in _TOOLBAR_HINT_LABELS:
            continue
        assert action.statusTip(), f"missing status tip on {label!r}"
        assert action.toolTip() == action.statusTip()

    assert "Ctrl+scroll" in main_window._zoom_controls.statusTip()


def test_toolbar_hover_shows_status_tip(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    tip = main_window._select_all_action.statusTip()
    assert tip
    QApplication.sendEvent(main_window, QStatusTipEvent(tip))
    assert main_window.statusBar().currentMessage() == tip


def _tips_host(qtbot, *, size=(900, 600), light=False):
    """A shown host with a focusable control, a styled tips overlay on top."""
    from pagedrop.ui.onboarding import TipsOverlay
    from pagedrop.ui.theme import app_stylesheet

    host = QWidget()
    qtbot.addWidget(host)
    host.setStyleSheet(app_stylesheet(light=light))
    host.resize(*size)
    behind = QPushButton("Behind", host)
    behind.move(10, 10)
    other = QPushButton("Other", host)
    other.move(120, 10)
    host.show()
    qtbot.waitExposed(host)
    host.activateWindow()
    qtbot.waitUntil(host.isActiveWindow, timeout=2000)
    behind.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(behind.hasFocus, timeout=2000)
    return host, behind, other, TipsOverlay(host)


def test_tips_overlay_focuses_got_it_and_restores_focus(isolated_settings, qtbot):
    host, behind, _other, tips = _tips_host(qtbot)
    tips.show_tips()
    qtbot.waitUntil(tips._got_it.hasFocus, timeout=2000)

    qtbot.mouseClick(tips._got_it, Qt.MouseButton.LeftButton)
    assert not tips.isVisible()
    assert behind.hasFocus()


def test_tips_overlay_escape_and_enter_dismiss_from_got_it(isolated_settings, qtbot):
    for key in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
        set_has_seen_tips(False)
        host, behind, _other, tips = _tips_host(qtbot)
        tips.show_tips()
        qtbot.waitUntil(tips._got_it.hasFocus, timeout=2000)
        qtbot.keyClick(tips._got_it, key)
        assert not tips.isVisible(), key
        assert has_seen_tips() is True
        assert behind.hasFocus()


def test_tips_overlay_skips_restoring_a_hidden_focus_widget(isolated_settings, qtbot):
    host, behind, _other, tips = _tips_host(qtbot)
    tips.show_tips()
    behind.hide()
    qtbot.keyClick(tips._got_it, Qt.Key.Key_Escape)
    assert not tips.isVisible()
    assert not behind.hasFocus()


def test_tips_overlay_tab_stays_on_got_it(isolated_settings, qtbot):
    host, behind, other, tips = _tips_host(qtbot)
    tips.show_tips()
    qtbot.waitUntil(tips._got_it.hasFocus, timeout=2000)
    for key, mods in (
        (Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier),
        (Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier),
    ):
        qtbot.keyClick(tips._got_it, key, mods)
        assert tips._got_it.hasFocus()
        assert not behind.hasFocus() and not other.hasFocus()
        assert tips.isVisible()


@pytest.mark.parametrize("light", [False, True])
def test_tips_overlay_dim_paints(isolated_settings, qtbot, light):
    host, _behind, _other, tips = _tips_host(qtbot, light=light)
    corner = QPoint(host.width() - 6, host.height() - 6)

    def sample() -> int:
        return host.grab().toImage().pixel(corner)

    clear = sample()
    tips.show_tips()
    assert sample() != clear


@pytest.mark.parametrize("light", [False, True])
def test_tips_overlay_fits_the_smallest_window(isolated_settings, qtbot, light):
    host, _behind, _other, tips = _tips_host(qtbot, size=(480, 320), light=light)
    tips.show_tips()
    qtbot.waitUntil(tips._got_it.hasFocus, timeout=2000)
    bounds = host.rect()
    button = QRect(
        tips._got_it.mapTo(host, QPoint(0, 0)), tips._got_it.size()
    )
    assert bounds.contains(button)
    assert tips._got_it.isVisible()
