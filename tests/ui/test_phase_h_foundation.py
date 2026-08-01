"""Phase H — action registry, toast kinds, shared confirm prompts."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QWidget

from pagedrop.ui.actions import ActionRegistry
from pagedrop.ui.busy_overlay import ToastOverlay
from pagedrop.ui.command_palette import collect_actions
from pagedrop.ui.dialogs import confirm_overwrite, prompt_unsaved_changes


def test_action_registry_rejects_duplicate_keys(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    registry = ActionRegistry(parent)
    registry.register("open", "Open")
    try:
        registry.register("open", "Open again")
        raise AssertionError("expected KeyError")
    except KeyError:
        pass


def test_main_window_registry_feeds_menu_toolbar_and_palette(main_window):
    open_action = main_window._actions["open"]
    assert open_action.shortcut() == QKeySequence.StandardKey.Open

    # Same QAction instance on File menu and toolbar.
    file_menu = None
    for action in main_window.menuBar().actions():
        if action.text().replace("&", "") == "File":
            file_menu = action.menu()
            break
    assert file_menu is not None
    assert open_action in file_menu.actions()
    assert open_action in main_window._toolbar.actions()

    labels = {a.text().replace("&", "") for a in collect_actions(main_window)}
    assert "Open PDF" in labels
    assert "Go to page" in labels
    assert main_window._actions["escape"] not in collect_actions(main_window)


def test_toast_kinds_and_undo(main_window, qtbot):
    main_window.showMinimized()
    qtbot.waitExposed(main_window)
    toast: ToastOverlay = main_window._toast

    main_window._show_toast("Saved", kind="success")
    assert toast.isVisible()
    assert toast._message.property("kind") == "success"
    assert toast._undo_button.isHidden()

    called: list[str] = []
    toast.show_toast("Moved", kind="undo", on_undo=lambda: called.append("undo"))
    assert toast._undo_button.isVisible()
    toast._undo_button.click()
    assert called == ["undo"]
    assert not toast.isVisible()


def test_toast_announces_message_to_assistive_tech(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    toast = ToastOverlay(parent)

    toast.show_toast("Job failed", kind="error")
    assert toast._message.accessibleName() == "Job failed"
    assert toast._message.accessibleDescription() == "Error notification"

    toast.show_toast("Saved demo.pdf", kind="success")
    assert toast._message.accessibleName() == "Saved demo.pdf"
    assert toast._message.accessibleDescription() == "Success notification"


def test_prompt_unsaved_and_overwrite_centralised(monkeypatch, qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)

    monkeypatch.setenv("PAGEDROP_TESTING", "1")
    assert prompt_unsaved_changes(parent, "Doc*") == "discard"
    assert confirm_overwrite(parent, [Path("/tmp/a.pdf")], window_title="T") is True
