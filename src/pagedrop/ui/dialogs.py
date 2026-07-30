from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from pagedrop.core.redact import RedactionScope

from pagedrop.core.backends.libreoffice import (
    DOWNLOAD_URL,
    WINGET_INSTALL_COMMAND,
)
from pagedrop.core.capabilities import (
    LIBREOFFICE,
    TESSDATA,
    AbsenceReason,
    CapabilityStatus,
    clear_cache,
    probe,
)
from pagedrop.core.tessdata_pack import ENG_FAST_URL, download_eng_fast, user_tessdata_dir
from pagedrop.ui.settings import (
    DELETE_CONFIRM_THRESHOLD,
    confirm_before_deleting_multiple_pages,
    set_tessdata_path,
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
        "Password required",
        label,
        QLineEdit.EchoMode.Password,
    )
    if not ok:
        return None
    return text


def prompt_redaction_scope(parent: QWidget | None) -> RedactionScope | None:
    """Scope checkboxes before verified Save As redaction. None on cancel."""
    if os.environ.get("PAGEDROP_TESTING") == "1":
        return RedactionScope()

    dialog = QDialog(parent)
    dialog.setWindowTitle("Redaction options")
    form = QFormLayout(dialog)
    strip_meta = QCheckBox("Strip document metadata")
    strip_meta.setChecked(True)
    strip_xmp = QCheckBox("Strip XMP metadata")
    strip_xmp.setChecked(True)
    remove_att = QCheckBox("Remove embedded attachments")
    remove_att.setChecked(False)
    form.addRow(strip_meta)
    form.addRow(strip_xmp)
    form.addRow(remove_att)
    note = QLabel(
        "Writes a new PDF with marked content permanently removed, then "
        "verifies extraction in a fresh process. The original file is never "
        "modified. Failed verification deletes the output."
    )
    note.setWordWrap(True)
    form.addRow(note)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return RedactionScope(
        strip_metadata=strip_meta.isChecked(),
        strip_xmp=strip_xmp.isChecked(),
        remove_attachments=remove_att.isChecked(),
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
    message.setWindowTitle("Unsaved changes")
    message.setText(f'"{title}" has unsaved changes.')
    message.setInformativeText("Save your changes before closing?")
    save_button = message.addButton(
        "Save as",
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
    message.setWindowTitle("Delete pages")
    message.setText(f"Delete {count} pages?")
    message.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    message.setDefaultButton(QMessageBox.StandardButton.No)
    fit_message_box_buttons(message)
    return message.exec() == QMessageBox.StandardButton.Yes


def confirm_remove_blank_pages(
    parent: QWidget,
    *,
    blank_count: int,
    page_count: int,
    heuristic_hint: str,
) -> bool:
    """Confirm heuristic blank-page removal. Never silent mass-delete."""
    if blank_count <= 0:
        return False
    if os.environ.get("PAGEDROP_TESTING") == "1":
        return True

    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Question)
    message.setWindowTitle("Remove blank pages")
    message.setText(
        f"Remove {blank_count} of {page_count} pages that look blank?"
    )
    message.setInformativeText(heuristic_hint)
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
    ``download`` / ``copy_winget`` for LibreOffice install actions, or ``cancel``.
    """
    if status.available:
        return "recheck"
    if status.id == LIBREOFFICE:
        return prompt_missing_libreoffice(parent, status, tool_title=tool_title)
    if status.id == TESSDATA:
        return prompt_missing_tessdata(parent, status, tool_title=tool_title)

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


def prompt_missing_tessdata(
    parent: QWidget | None,
    status: CapabilityStatus | None = None,
    *,
    tool_title: str | None = None,
) -> str:
    """Contextual setup when OCR language data is missing (not a first-launch nag).

    Returns ``recheck``, ``download``, ``configure``, or ``cancel``.
    """
    if status is not None and status.available:
        return "recheck"

    subject = tool_title or "OCR"
    detail = ""
    if status is not None and status.detail.strip():
        detail = status.detail.strip()

    if os.environ.get("PAGEDROP_TESTING") == "1":
        return "cancel"

    message = build_missing_tessdata_dialog(parent, subject=subject, detail=detail)
    message.exec()
    clicked = message.clickedButton()
    name = clicked.objectName() if clicked is not None else ""
    if name == "tess_recheck":
        clear_cache()
        refreshed = probe(TESSDATA, refresh=True)
        if refreshed.available:
            QMessageBox.information(
                parent,
                "OCR data",
                "tessdata is now available.",
            )
            return "recheck"
        return prompt_missing_tessdata(parent, refreshed, tool_title=tool_title)
    if name == "tess_download":
        return _download_eng_tessdata(parent)
    if name == "tess_configure":
        QMessageBox.information(
            parent,
            "Configure tessdata",
            "Point Preferences at a folder that contains language files "
            "(for example eng.traineddata), or download the optional English pack.\n\n"
            "PageDrop uses PyMuPDF’s built-in OCR. You do not need a separate "
            "Tesseract executable as the primary path.\n\n"
            f"Optional download URL:\n{ENG_FAST_URL}",
        )
        return "configure"
    return "cancel"


def build_missing_tessdata_dialog(
    parent: QWidget | None,
    *,
    subject: str = "OCR",
    detail: str = "",
) -> QMessageBox:
    """Build (do not exec) the missing-tessdata prompt — testable without UI loop."""
    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Information)
    message.setWindowTitle("OCR data required")
    message.setText(f"{subject}: Language data missing")
    informative = (
        "OCR needs tessdata language files (for example eng.traineddata).\n"
        "Configure a folder, or download the optional English pack. "
        "PageDrop never downloads this on first launch."
    )
    if detail:
        informative = f"{informative}\n\nDetail: {detail}"
    message.setInformativeText(informative)

    recheck_btn = message.addButton("Recheck", QMessageBox.ButtonRole.AcceptRole)
    recheck_btn.setObjectName("tess_recheck")
    download_btn = message.addButton(
        "Download eng…",
        QMessageBox.ButtonRole.ActionRole,
    )
    download_btn.setObjectName("tess_download")
    configure_btn = message.addButton(
        "Configure…",
        QMessageBox.ButtonRole.ActionRole,
    )
    configure_btn.setObjectName("tess_configure")
    message.addButton(QMessageBox.StandardButton.Cancel)
    message.setDefaultButton(recheck_btn)
    fit_message_box_buttons(message)
    return message


def _download_eng_tessdata(parent: QWidget | None) -> str:
    """Download eng.traineddata after an explicit confirm; wire into Settings."""
    dest = user_tessdata_dir()
    confirm = QMessageBox(parent)
    confirm.setIcon(QMessageBox.Icon.Question)
    confirm.setWindowTitle("Download eng tessdata")
    confirm.setText("Download English (tessdata_fast) language data?")
    confirm.setInformativeText(
        f"Saves eng.traineddata to:\n{dest}\n\n"
        "Only continues if you click Download."
    )
    download_btn = confirm.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
    confirm.addButton(QMessageBox.StandardButton.Cancel)
    confirm.setDefaultButton(download_btn)
    fit_message_box_buttons(confirm)
    confirm.exec()
    if confirm.clickedButton() is not download_btn:
        return "cancel"
    try:
        path = download_eng_fast(dest_dir=dest)
    except RuntimeError as exc:
        QMessageBox.warning(parent, "Download eng tessdata", str(exc))
        return "cancel"
    set_tessdata_path(path.parent)
    clear_cache()
    refreshed = probe(TESSDATA, refresh=True)
    if refreshed.available:
        QMessageBox.information(
            parent,
            "OCR data",
            f"Saved:\n{path}\n\ntessdata is now available.",
        )
        return "recheck"
    QMessageBox.warning(
        parent,
        "OCR data",
        f"Downloaded to:\n{path}\n\nbut tessdata still reports unavailable.",
    )
    return "download"


def prompt_missing_libreoffice(
    parent: QWidget | None,
    status: CapabilityStatus | None = None,
    *,
    tool_title: str | None = None,
) -> str:
    """Contextual prompt when LibreOffice is needed but not installed.

    Only shown when conversion is requested. Offers download (opens
    libreoffice.org) and, on Windows, copying the winget command — never runs
    winget. Returns ``recheck``, ``download``, ``copy_winget``, or ``cancel``.
    """
    if status is not None and status.available:
        return "recheck"

    subject = tool_title or "Office to PDF"
    detail = ""
    if status is not None and status.detail.strip():
        detail = status.detail.strip()

    if os.environ.get("PAGEDROP_TESTING") == "1":
        return "cancel"

    message = build_missing_libreoffice_dialog(parent, subject=subject, detail=detail)
    message.exec()
    clicked = message.clickedButton()

    # Identify by objectName set in builder (roles alone are ambiguous).
    name = clicked.objectName() if clicked is not None else ""
    if name == "lo_recheck":
        clear_cache()
        refreshed = probe(LIBREOFFICE, refresh=True)
        if refreshed.available:
            QMessageBox.information(
                parent,
                "LibreOffice",
                "LibreOffice is now available.",
            )
            return "recheck"
        return prompt_missing_libreoffice(parent, refreshed, tool_title=tool_title)
    if name == "lo_download":
        QDesktopServices.openUrl(QUrl(DOWNLOAD_URL))
        return "download"
    if name == "lo_copy_winget":
        _copy_libreoffice_winget_command(parent)
        return "copy_winget"
    return "cancel"


def build_missing_libreoffice_dialog(
    parent: QWidget | None,
    *,
    subject: str = "Office to PDF",
    detail: str = "",
) -> QMessageBox:
    """Build (do not exec) the missing-LibreOffice prompt — testable without UI loop."""
    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Information)
    message.setWindowTitle("LibreOffice required")
    message.setText(f"{subject}: LibreOffice not found")
    informative = (
        "Install LibreOffice to convert Word, Excel, and PowerPoint files locally.\n"
        "PageDrop never installs it. Open the download page, or copy the winget "
        "command and run it yourself."
    )
    if detail:
        informative = f"{informative}\n\nDetail: {detail}"
    if sys.platform == "win32":
        informative = (
            f"{informative}\n\n"
            f"Winget command:\n{WINGET_INSTALL_COMMAND}"
        )
    message.setInformativeText(informative)

    recheck_btn = message.addButton("Recheck", QMessageBox.ButtonRole.AcceptRole)
    recheck_btn.setObjectName("lo_recheck")
    download_btn = message.addButton(
        "Download LibreOffice…",
        QMessageBox.ButtonRole.ActionRole,
    )
    download_btn.setObjectName("lo_download")
    if sys.platform == "win32":
        copy_btn = message.addButton(
            "Copy winget command",
            QMessageBox.ButtonRole.ActionRole,
        )
        copy_btn.setObjectName("lo_copy_winget")
    message.addButton(QMessageBox.StandardButton.Cancel)
    message.setDefaultButton(recheck_btn)
    fit_message_box_buttons(message)
    return message


def _copy_libreoffice_winget_command(parent: QWidget | None) -> None:
    """Copy the winget install command to the clipboard — never run winget."""
    clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(WINGET_INSTALL_COMMAND)
    QMessageBox.information(
        parent,
        "Winget command copied",
        f"Copied to clipboard:\n{WINGET_INSTALL_COMMAND}\n\n"
        "Paste it into Terminal or PowerShell to install LibreOffice yourself.",
    )
