"""Phase H — action registry, toast kinds, shared confirm prompts."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QMessageBox, QWidget

from pagedrop.ui.actions import ActionRegistry
from pagedrop.ui.busy_overlay import ToastOverlay
from pagedrop.ui.command_palette import collect_actions
from pagedrop.ui import dialogs


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


def test_prompt_unsaved_centralised(monkeypatch, qtbot, unsaved_answer):
    parent = QWidget()
    qtbot.addWidget(parent)

    assert dialogs.prompt_unsaved_changes is unsaved_answer
    assert unsaved_answer.answer == "discard"
    assert unsaved_answer.real is not unsaved_answer
    # The real prompt follows the dialog, never an environment short-circuit.
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    assert unsaved_answer.real(parent, "Doc*") == "cancel"


@pytest.mark.parametrize(
    ("button", "expected"),
    [(QMessageBox.StandardButton.Yes, True), (QMessageBox.StandardButton.No, False)],
)
def test_confirm_overwrite_follows_dialog_answer(
    monkeypatch, qtbot, overwrite_answer, button, expected
):
    parent = QWidget()
    qtbot.addWidget(parent)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: button)
    assert (
        overwrite_answer.real(parent, [Path("/tmp/a.pdf")], window_title="T")
        is expected
    )


def _capture_confirm(monkeypatch, answer):
    """Patch exec to record the message box and answer; no modal loop runs."""
    boxes: list[QMessageBox] = []
    state = {"labels": None, "destructive": None, "default": None}

    def fake_exec(box):
        boxes.append(box)
        yes = box.button(QMessageBox.StandardButton.Yes)
        no = box.button(QMessageBox.StandardButton.No)
        state["labels"] = (yes.text(), no.text())
        state["destructive"] = bool(yes.property("destructive"))
        state["default"] = (
            "yes" if box.defaultButton() is yes else "no"
        )
        return answer

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return state


_YES = QMessageBox.StandardButton.Yes
_NO = QMessageBox.StandardButton.No


@pytest.mark.parametrize(
    ("make_call", "action", "decline", "destructive", "safe_default"),
    [
        (
            lambda p, real: real(p, [Path("/tmp/a.pdf")], window_title="T"),
            "Overwrite",
            "Cancel",
            True,
            True,
        ),
        (
            lambda p, real: dialogs.confirm_delete_pages(p, 12),
            "Delete 12 pages",
            "Cancel",
            True,
            True,
        ),
        (
            lambda p, real: dialogs.confirm_remove_blank_pages(
                p, blank_count=3, page_count=9, heuristic_hint="hint"
            ),
            "Remove 3 pages",
            "Cancel",
            True,
            True,
        ),
        (
            lambda p, real: dialogs.confirm_remove_blank_pages(
                p, blank_count=1, page_count=9, heuristic_hint="hint"
            ),
            "Remove 1 page",
            "Cancel",
            True,
            True,
        ),
        (
            lambda p, real: dialogs.ask_named_confirmation(
                p,
                title="Recover",
                text="Recover?",
                action="Recover",
                decline="Discard",
                default_action=True,
            ),
            "Recover",
            "Discard",
            False,
            False,
        ),
        (
            lambda p, real: dialogs.ask_named_confirmation(
                p, title="Flatten forms", text="Flatten?", action="Flatten"
            ),
            "Flatten",
            "Cancel",
            False,
            True,
        ),
    ],
    ids=["overwrite", "delete", "blank-many", "blank-one", "recover", "flatten"],
)
@pytest.mark.parametrize("answer", [_YES, _NO])
def test_named_confirmations_label_buttons_and_follow_answer(
    monkeypatch,
    qtbot,
    isolated_settings,
    overwrite_answer,
    make_call,
    action,
    decline,
    destructive,
    safe_default,
    answer,
):
    monkeypatch.delenv("PAGEDROP_TESTING", raising=False)
    parent = QWidget()
    qtbot.addWidget(parent)
    state = _capture_confirm(monkeypatch, answer)

    # confirm_overwrite is replaced by an autouse stand-in; use the real one.
    result = make_call(parent, overwrite_answer.real)

    assert result is (answer == _YES)
    assert state["labels"] == (action, decline)
    assert state["destructive"] is destructive
    assert state["default"] == ("no" if safe_default else "yes")
