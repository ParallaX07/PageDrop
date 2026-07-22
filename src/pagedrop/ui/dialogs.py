from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox, QWidget

from pagedrop.ui.settings import (
    DELETE_CONFIRM_THRESHOLD,
    confirm_before_deleting_multiple_pages,
)


def fit_message_box_buttons(message: QMessageBox) -> None:
    """Size multi-action message boxes so button labels are not clipped."""
    buttons = message.buttons()
    if len(buttons) < 2:
        return
    widest = max(button.sizeHint().width() for button in buttons)
    for button in buttons:
        button.setMinimumWidth(widest)
    message.setMinimumWidth(message.sizeHint().width())


def prompt_discard_file_list(
    parent: QWidget,
    *,
    window_title: str,
    informative_text: str,
) -> str:
    """Return ``discard`` or ``cancel`` for an unsaved file-list close prompt."""
    if os.environ.get("PAGEDROP_TESTING") == "1":
        return "discard"

    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Question)
    message.setWindowTitle(window_title)
    message.setText("Discard file list?")
    message.setInformativeText(informative_text)
    discard_button = message.addButton(
        "Discard",
        QMessageBox.ButtonRole.DestructiveRole,
    )
    message.addButton(QMessageBox.StandardButton.Cancel)
    fit_message_box_buttons(message)
    message.exec()
    if message.clickedButton() is discard_button:
        return "discard"
    return "cancel"


def prompt_unsaved_changes(parent: QWidget, display_title: str) -> str:
    """Return ``save``, ``discard``, or ``cancel`` for a dirty-document close."""
    if os.environ.get("PAGEDROP_TESTING") == "1":
        return "discard"

    title = display_title.rstrip("*") or "document"
    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Warning)
    message.setWindowTitle("Unsaved Changes")
    message.setText(f'"{title}" has unsaved changes.')
    message.setInformativeText("Save your changes before closing?")
    save_button = message.addButton(
        "Save As",
        QMessageBox.ButtonRole.AcceptRole,
    )
    discard_button = message.addButton(
        "Discard",
        QMessageBox.ButtonRole.DestructiveRole,
    )
    message.addButton(QMessageBox.StandardButton.Cancel)
    fit_message_box_buttons(message)
    message.exec()
    clicked = message.clickedButton()
    if clicked is save_button:
        return "save"
    if clicked is discard_button:
        return "discard"
    return "cancel"


def confirm_overwrite(
    parent: QWidget,
    paths: list[Path],
    *,
    window_title: str,
) -> bool:
    """Return True if overwriting existing *paths* should proceed."""
    if os.environ.get("PAGEDROP_TESTING") == "1":
        return True

    names = ", ".join(path.name for path in paths[:5])
    extra = ""
    if len(paths) > 5:
        extra = f"\n…and {len(paths) - 5} more"
    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Question)
    message.setWindowTitle(window_title)
    message.setText(
        f"The following file(s) already exist and will be overwritten:\n\n"
        f"{names}{extra}\n\nContinue?"
    )
    message.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    message.setDefaultButton(QMessageBox.StandardButton.No)
    fit_message_box_buttons(message)
    return message.exec() == QMessageBox.StandardButton.Yes


def confirm_delete_pages(parent: QWidget, count: int) -> bool:
    """Return True if deleting *count* pages should proceed."""
    if count <= DELETE_CONFIRM_THRESHOLD:
        return True
    if not confirm_before_deleting_multiple_pages():
        return True
    if os.environ.get("PAGEDROP_TESTING") == "1":
        return True

    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Question)
    message.setWindowTitle("Delete Pages")
    message.setText(f"Delete {count} pages?")
    message.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    message.setDefaultButton(QMessageBox.StandardButton.No)
    fit_message_box_buttons(message)
    return message.exec() == QMessageBox.StandardButton.Yes
