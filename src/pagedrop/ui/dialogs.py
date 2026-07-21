from __future__ import annotations

import os

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


def confirm_delete_pages(parent: QWidget, count: int) -> bool:
    """Return True if deleting *count* pages should proceed."""
    if count <= DELETE_CONFIRM_THRESHOLD:
        return True
    if not confirm_before_deleting_multiple_pages():
        return True
    if os.environ.get("PAGEDROP_TESTING") == "1":
        return True

    reply = QMessageBox.question(
        parent,
        "Delete Pages",
        f"Delete {count} pages?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes
