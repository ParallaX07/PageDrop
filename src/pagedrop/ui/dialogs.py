from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox, QWidget

from pagedrop.core.capabilities import AbsenceReason, CapabilityStatus, clear_cache, probe
from pagedrop.ui.settings import (
    DELETE_CONFIRM_THRESHOLD,
    confirm_before_deleting_multiple_pages,
)

_REASON_COPY: dict[AbsenceReason, tuple[str, str]] = {
    AbsenceReason.ENGINE_MISSING: (
        "Processing engine missing",
        "Install or locate the required converter / processing engine, then recheck.",
    ),
    AbsenceReason.DATA_MISSING: (
        "Language or model data missing",
        "Download or configure the required data files (for example tessdata), then recheck.",
    ),
    AbsenceReason.CODEC_MISSING: (
        "Format codec pack missing",
        "Install the optional codec pack for this format, then recheck.",
    ),
    AbsenceReason.LICENCE_BLOCKED: (
        "Licence restriction",
        "This component is present but blocked by redistribution or licence policy.",
    ),
}


def prompt_pdf_password(
    parent: QWidget | None,
    filename: str,
    *,
    incorrect: bool = False,
) -> str | None:
    """Ask for a PDF password (editor + Tools jobs). Returns None on cancel."""
    if incorrect:
        label = f'Incorrect password for "{filename}". Try again:'
    else:
        label = f'"{filename}" is password-protected.\nEnter password:'
    text, ok = QInputDialog.getText(
        parent,
        "Password Required",
        label,
        QLineEdit.EchoMode.Password,
    )
    if not ok:
        return None
    return text


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


def prompt_cancel_running_job(
    parent: QWidget,
    *,
    window_title: str = "Tools",
) -> bool:
    """Return True if the user confirms cancelling an in-progress job."""
    if os.environ.get("PAGEDROP_TESTING") == "1":
        return True

    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Question)
    message.setWindowTitle(window_title)
    message.setText("A job is still running.")
    message.setInformativeText("Cancel the job and close this window?")
    cancel_job = message.addButton(
        "Cancel job",
        QMessageBox.ButtonRole.DestructiveRole,
    )
    keep_open = message.addButton(
        "Keep open",
        QMessageBox.ButtonRole.RejectRole,
    )
    message.setDefaultButton(keep_open)
    fit_message_box_buttons(message)
    message.exec()
    return message.clickedButton() is cancel_job


def prompt_missing_capability(
    parent: QWidget | None,
    status: CapabilityStatus,
    *,
    tool_title: str | None = None,
) -> str:
    """Shared configure / recheck flow for absent optional backends.

    Returns ``recheck`` if the capability became available after recheck,
    ``configure`` when the user asked for setup guidance (already shown),
    or ``cancel``.
    """
    if status.available:
        return "recheck"

    reason = status.reason or AbsenceReason.ENGINE_MISSING
    headline, guidance = _REASON_COPY.get(
        reason,
        _REASON_COPY[AbsenceReason.ENGINE_MISSING],
    )
    subject = tool_title or status.id.replace("_", " ")
    detail = status.detail.strip() or "No additional detail."

    if os.environ.get("PAGEDROP_TESTING") == "1":
        return "cancel"

    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Information)
    message.setWindowTitle("Missing capability")
    message.setText(f"{subject}: {headline}")
    message.setInformativeText(
        f"{guidance}\n\n"
        f"Kind: {reason.value}\n"
        f"Detail: {detail}"
    )
    recheck_btn = message.addButton(
        "Recheck",
        QMessageBox.ButtonRole.AcceptRole,
    )
    configure_btn = message.addButton(
        "Configure…",
        QMessageBox.ButtonRole.ActionRole,
    )
    message.addButton(QMessageBox.StandardButton.Cancel)
    message.setDefaultButton(recheck_btn)
    fit_message_box_buttons(message)
    message.exec()
    clicked = message.clickedButton()
    if clicked is recheck_btn:
        clear_cache()
        refreshed = probe(status.id, refresh=True)
        if refreshed.available:
            QMessageBox.information(
                parent,
                "Missing capability",
                f"{subject} is now available.",
            )
            return "recheck"
        return prompt_missing_capability(parent, refreshed, tool_title=tool_title)
    if clicked is configure_btn:
        QMessageBox.information(
            parent,
            "Configure capability",
            f"{guidance}\n\n"
            f"Capability id: {status.id}\n"
            f"Kind: {reason.value}\n"
            f"{detail}",
        )
        return "configure"
    return "cancel"
