"""PDF to Word (DOCX) — Phase 22b modeless shell (Phase 32)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from pagedrop.core.capabilities import LIBREOFFICE, clear_cache, probe
from pagedrop.core.supported_formats import is_pdf_path
from pagedrop.ui.dialogs import prompt_missing_capability, prompt_missing_libreoffice
from pagedrop.ui.preferences_dialog import open_preferences
from pagedrop.ui.settings import (
    apply_office_settings_to_capabilities,
    last_directory,
    remember_directory,
)
from pagedrop.ui.tool_page import present_tool_page, tool_shell_store
from pagedrop.ui.tool_shell import ToolShellWindow, run_tool_job

if TYPE_CHECKING:
    from pagedrop.ui.tools_window import ToolsWindow

SHELL_PDF_TO_WORD_ID = "pdf_to_word"

_PDF_FILTER = "PDF files (*.pdf);;All files (*)"


def _pick_save_path(parent: QWidget, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(
        parent,
        "Save Word document",
        suggested,
        "Word documents (*.docx);;All files (*)",
    )
    if not path:
        return None
    remember_directory(path)
    if not path.lower().endswith(".docx"):
        path = f"{path}.docx"
    return path


def _configure_pdf_to_word(shell: ToolShellWindow) -> None:
    apply_office_settings_to_capabilities()

    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)

    hint = QLabel(
        "Converts locally with LibreOffice. Layout is best-effort and often "
        "lossy — complex pages may not match the PDF exactly. Source PDF is "
        "never overwritten."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)

    status = QLabel()
    status.setObjectName("ToolsHint")
    status.setWordWrap(True)
    status.setAccessibleName("LibreOffice backend status")
    form.addRow(status)

    btn_row = QHBoxLayout()
    configure_btn = QPushButton("Configure…")
    configure_btn.setObjectName("ToolbarSecondary")
    configure_btn.setToolTip("LibreOffice path and Recheck")
    recheck_btn = QPushButton("Recheck")
    recheck_btn.setObjectName("ToolbarSecondary")
    btn_row.addWidget(configure_btn)
    btn_row.addWidget(recheck_btn)
    btn_row.addStretch(1)
    form.addRow(btn_row)

    shell.set_options_widget(options)
    shell._backend_status_label = status  # type: ignore[attr-defined]

    def refresh_status() -> None:
        apply_office_settings_to_capabilities()
        cap = probe(LIBREOFFICE)
        if cap.available:
            path = (cap.extras or {}).get("path") or "detected"
            status.setText(f"LibreOffice ready — {path}")
            shell.statusBar().showMessage("Ready — LibreOffice")
        else:
            detail = cap.detail or "LibreOffice (soffice) not found"
            status.setText(f"LibreOffice missing — {detail}")
            shell.statusBar().showMessage(
                "No LibreOffice — Configure or install LibreOffice"
            )
        shell._update_run_enabled()

    def on_configure() -> None:
        open_preferences(shell)
        refresh_status()

    def on_recheck() -> None:
        clear_cache()
        cap = probe(LIBREOFFICE, refresh=True)
        refresh_status()
        if not cap.available:
            prompt_missing_libreoffice(
                shell, cap, tool_title=shell.WINDOW_TITLE
            )
            refresh_status()

    configure_btn.clicked.connect(on_configure)
    recheck_btn.clicked.connect(on_recheck)
    shell.set_run_enabled_check(lambda: probe(LIBREOFFICE).available)
    refresh_status()

    def on_run() -> None:
        apply_office_settings_to_capabilities()
        cap = probe(LIBREOFFICE)
        if not cap.available:
            result = prompt_missing_capability(
                shell, cap, tool_title=shell.WINDOW_TITLE
            )
            refresh_status()
            if result == "configure":
                open_preferences(shell)
                refresh_status()
            return

        paths = [p for p in shell.drop_zone.paths() if Path(p).is_file()]
        if not paths:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "Choose a valid PDF.")
            return
        source = paths[0]
        if not is_pdf_path(source):
            QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                f"Unsupported format:\n{Path(source).name}",
            )
            return

        suggested = str(Path(source).with_suffix(".docx"))
        if not Path(suggested).parent.is_dir():
            suggested = str(
                Path(last_directory() or ".") / Path(source).with_suffix(".docx").name
            )
        output = _pick_save_path(shell, suggested)
        if not output:
            return

        run_tool_job(
            shell,
            job_type="pdf_to_docx",
            inputs=[source],
            output=output,
            progress_message="Converting PDF to Word…",
            success_toast="Word document ready",
        )

    shell.set_run_handler(on_run)


def open_pdf_to_word_shell(tools: ToolsWindow) -> ToolShellWindow | None:
    """Lazy-create / raise the PDF to Word modeless shell."""
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    entry = next((e for e in TOOL_CATALOGUE if e.id == SHELL_PDF_TO_WORD_ID), None)
    if entry is None:
        return None

    store = tool_shell_store(tools)  # type: ignore[assignment]
    shell = store.get(SHELL_PDF_TO_WORD_ID)
    if shell is None:
        shell = ToolShellWindow(
            title=entry.title,
            description=entry.description,
            editor=tools.editor,
            window_manager=getattr(tools, "_window_manager", None),
            multi=False,
            accept=is_pdf_path,
            dialog_filter=_PDF_FILTER,
            browse_title=f"Choose PDF — {entry.title}",
            empty_prompt="Drop a PDF here, or click to browse",
        )
        _configure_pdf_to_word(shell)
        store[SHELL_PDF_TO_WORD_ID] = shell
    else:
        shell.set_editor(tools.editor)
        apply_office_settings_to_capabilities()
        cap = probe(LIBREOFFICE)
        label = getattr(shell, "_backend_status_label", None)
        if label is not None:
            if cap.available:
                path = (cap.extras or {}).get("path") or "detected"
                label.setText(f"LibreOffice ready — {path}")
            else:
                detail = cap.detail or "LibreOffice (soffice) not found"
                label.setText(f"LibreOffice missing — {detail}")
            shell._update_run_enabled()

    present_tool_page(tools.editor, shell, page_id=f"tool:{SHELL_PDF_TO_WORD_ID}")
    return shell
