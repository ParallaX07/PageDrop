"""Office → PDF — Phase 22b modeless shell (Phase 26 UX)."""

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

from pagedrop.core.backends.office import (
    BACKEND_LABELS,
    OfficeBackend,
    OfficeComFailedNeedsRetry,
    capability_report,
    is_office_path,
    office_dialog_filter,
    resolve_backend,
)
from pagedrop.core.capabilities import LIBREOFFICE, OFFICE_COM, clear_cache
from pagedrop.core.jobs import (
    JobCancelledError,
    JobError,
    JobSpec,
    OutputExistsError,
    SourceOverwriteError,
)
from pagedrop.core.jobs.errors import BackendUnavailableError
from pagedrop.ui.dialogs import (
    confirm_overwrite,
    prompt_missing_capability,
    prompt_missing_libreoffice,
)
from pagedrop.ui.preferences_dialog import open_preferences
from pagedrop.ui.settings import (
    apply_office_settings_to_capabilities,
    last_directory,
    office_preferred_backend,
    remember_directory,
)
from pagedrop.ui.tool_page import present_tool_page, tool_shell_store
from pagedrop.ui.tool_shell import EMPTY_PROMPT_OFFICE, ToolShellWindow

if TYPE_CHECKING:
    from pagedrop.ui.tools_window import ToolsWindow

SHELL_OFFICE_ID = "office_to_pdf"


def _pick_save_path(parent: QWidget, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(
        parent,
        "Save PDF",
        suggested,
        "PDF files (*.pdf);;All files (*)",
    )
    if not path:
        return None
    remember_directory(path)
    if not path.lower().endswith(".pdf"):
        path = f"{path}.pdf"
    return path


def _ask_retry_with_libreoffice(parent: QWidget, message: str) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Retry with LibreOffice?")
    box.setText("Microsoft Office conversion failed.")
    box.setInformativeText(
        f"{message}\n\n"
        "Retry with LibreOffice? Layouts may differ from Microsoft Office."
    )
    retry = box.addButton("Retry with LibreOffice", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(retry)
    box.exec()
    return box.clickedButton() is retry


def _configure_office_convert(shell: ToolShellWindow) -> None:
    apply_office_settings_to_capabilities()

    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)

    hint = QLabel(
        "Drop a Word, Excel, or PowerPoint file (or OpenDocument). "
        "PageDrop converts locally — nothing is uploaded."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)

    status = QLabel()
    status.setObjectName("ToolsHint")
    status.setWordWrap(True)
    status.setAccessibleName("Office backend status")
    form.addRow(status)

    btn_row = QHBoxLayout()
    configure_btn = QPushButton("Configure…")
    configure_btn.setObjectName("ToolbarSecondary")
    configure_btn.setToolTip("Preferred backend, LibreOffice path, and recheck")
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
        report = capability_report()
        status.setText(report.status_line())
        shell._update_run_enabled()
        if report.any_available:
            pref = BACKEND_LABELS.get(report.preferred, report.preferred)
            shell.statusBar().showMessage(
                f"Ready — preferred backend: {pref}"
            )
        else:
            shell.statusBar().showMessage(
                "No Office backend — Configure or install LibreOffice"
            )

    def on_configure() -> None:
        open_preferences(shell)
        refresh_status()

    def on_recheck() -> None:
        clear_cache()
        report = capability_report(refresh=True)
        refresh_status()
        if not report.any_available:
            prompt_missing_libreoffice(
                shell, report.libreoffice, tool_title=shell.WINDOW_TITLE
            )
            refresh_status()

    configure_btn.clicked.connect(on_configure)
    recheck_btn.clicked.connect(on_recheck)
    shell.set_run_enabled_check(lambda: capability_report().any_available)
    refresh_status()

    def on_run() -> None:
        apply_office_settings_to_capabilities()
        report = capability_report()
        if not report.any_available:
            result = prompt_missing_capability(
                shell,
                report.libreoffice if not report.com.available else report.com,
                tool_title=shell.WINDOW_TITLE,
            )
            refresh_status()
            if result == "configure":
                open_preferences(shell)
                refresh_status()
            return

        paths = [p for p in shell.drop_zone.paths() if Path(p).is_file()]
        if not paths:
            QMessageBox.warning(
                shell, shell.WINDOW_TITLE, "Choose a valid Office document."
            )
            return
        source = paths[0]
        if not is_office_path(source):
            QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                f"Unsupported format:\n{Path(source).name}",
            )
            return

        preferred: OfficeBackend = office_preferred_backend()  # type: ignore[assignment]
        try:
            resolved = resolve_backend(source, preference=preferred, report=report)
        except BackendUnavailableError as exc:
            status_cap = (
                report.com if exc.capability_id == OFFICE_COM else report.libreoffice
            )
            prompt_missing_capability(
                shell, status_cap, tool_title=shell.WINDOW_TITLE
            )
            refresh_status()
            return
        except JobError as exc:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, str(exc))
            return

        suggested = str(Path(source).with_suffix(".pdf"))
        if not Path(suggested).parent.is_dir():
            suggested = str(Path(last_directory() or ".") / Path(source).with_suffix(".pdf").name)
        output = _pick_save_path(shell, suggested)
        if not output:
            return

        backend_label = BACKEND_LABELS.get(resolved, resolved)
        _run_office_conversion(
            shell,
            source=source,
            output=output,
            backend=resolved,
            backend_label=backend_label,
            refresh_status=refresh_status,
        )

    shell.set_run_handler(on_run)


def _run_office_conversion(
    shell: ToolShellWindow,
    *,
    source: str,
    output: str,
    backend: str,
    backend_label: str,
    refresh_status,
) -> None:
    """Job runner with explicit LibreOffice retry after COM failure."""
    out = Path(output)
    existing = [out] if out.exists() else []
    token = shell.begin_job(f"Converting with {backend_label}…")
    runner = shell.job_runner()

    def attempt(engine: str, label: str) -> Path:
        shell.set_job_progress(0.1, f"Converting with {label}…")
        return runner.run(
            JobSpec.create(
                "office_to_pdf",
                inputs=[source],
                output=output,
                options={"backend": engine},
                overwrite=True,
            ),
            progress=shell.set_job_progress,
            cancel=token,
        )

    try:
        if existing and not confirm_overwrite(
            shell, existing, window_title=shell.WINDOW_TITLE
        ):
            shell.end_job(status="Cancelled", toast="Cancelled", toast_kind="info")
            return
        result = attempt(backend, backend_label)
        used_label = backend_label
    except OfficeComFailedNeedsRetry as exc:
        if not _ask_retry_with_libreoffice(shell, str(exc)):
            shell.end_job(
                error=str(exc),
                toast="Conversion failed",
                toast_kind="error",
            )
            refresh_status()
            return
        lo_label = BACKEND_LABELS["libreoffice"]
        try:
            result = attempt("libreoffice", lo_label)
            used_label = lo_label
        except JobCancelledError:
            shell.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
            return
        except (JobError, OSError, ValueError) as retry_exc:
            shell.end_job(
                error=str(retry_exc),
                toast="Job failed",
                toast_kind="error",
            )
            refresh_status()
            return
    except JobCancelledError:
        shell.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
        return
    except BackendUnavailableError as exc:
        cap = LIBREOFFICE if exc.capability_id == LIBREOFFICE else OFFICE_COM
        from pagedrop.core.capabilities import probe

        shell.end_job(status="Backend missing", toast="Backend missing", toast_kind="error")
        prompt_missing_capability(
            shell, probe(cap), tool_title=shell.WINDOW_TITLE
        )
        refresh_status()
        return
    except SourceOverwriteError as exc:
        shell.end_job(
            error=f"Output must not overwrite a source file:\n{exc}",
            toast="Cannot overwrite source",
            toast_kind="error",
        )
        return
    except OutputExistsError as exc:
        shell.end_job(
            error=f"Output already exists:\n{exc}",
            toast="Output exists",
            toast_kind="error",
        )
        return
    except (JobError, OSError, ValueError, FileNotFoundError) as exc:
        shell.end_job(error=str(exc), toast="Job failed", toast_kind="error")
        refresh_status()
        return
    except Exception as exc:
        shell.end_job(
            error=f"Unexpected error:\n{exc}",
            toast="Job failed",
            toast_kind="error",
        )
        refresh_status()
        return

    name = Path(result).name
    shell.end_job(
        status=f"Saved {name} via {used_label}",
        toast=f"Saved {name} via {used_label}",
        toast_kind="success",
        result_path=str(result),
    )
    refresh_status()


def open_office_convert_shell(tools: ToolsWindow) -> ToolShellWindow | None:
    """Lazy-create / raise the Office to PDF modeless shell."""
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    entry = next((e for e in TOOL_CATALOGUE if e.id == SHELL_OFFICE_ID), None)
    if entry is None:
        return None

    store = tool_shell_store(tools)  # type: ignore[assignment]

    shell = store.get(SHELL_OFFICE_ID)
    if shell is None:
        shell = ToolShellWindow(
            title=entry.title,
            description=entry.description,
            editor=tools.editor,
            window_manager=getattr(tools, "_window_manager", None),
            multi=False,
            accept=is_office_path,
            dialog_filter=office_dialog_filter(),
            browse_title=f"Choose document — {entry.title}",
            empty_prompt=EMPTY_PROMPT_OFFICE,
        )
        _configure_office_convert(shell)
        store[SHELL_OFFICE_ID] = shell
    else:
        shell.set_editor(tools.editor)
        refresh = getattr(shell, "_backend_status_label", None)
        if refresh is not None:
            apply_office_settings_to_capabilities()
            report = capability_report()
            refresh.setText(report.status_line())
            shell._update_run_enabled()

    present_tool_page(tools.editor, shell, page_id=f"tool:{SHELL_OFFICE_ID}")
    return shell
