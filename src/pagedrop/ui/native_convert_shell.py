"""Convert to PDF / Export from PDF — Phase 22b modeless shells (Phase 25 UI)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from pagedrop.core.native_conversions import (
    MULTI_PAGE_EXPORT_IDS,
    predicted_export_paths,
)
from pagedrop.core.pdf_service import page_count as pdf_page_count
from pagedrop.core.supported_formats import (
    export_formats,
    import_to_pdf_dialog_filter,
    is_native_import_path,
    is_pdf_path,
)
from pagedrop.ui.organize_tools import editor_pdf_context
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.tool_page import present_tool_page, tool_shell_store
from pagedrop.ui.tool_shell import EMPTY_PROMPT_DOCUMENTS, ToolShellWindow, run_tool_job
from pagedrop.utils.page_jump import parse_page_ranges

if TYPE_CHECKING:
    from pagedrop.ui.tools_window import ToolsWindow

SHELL_CONVERT_IDS: frozenset[str] = frozenset({"convert_to_pdf", "export_from_pdf"})

_PDF_FILTER = "PDF files (*.pdf);;All files (*)"


def _pick_save_path(
    parent: QWidget,
    title: str,
    suggested: str,
    file_filter: str,
) -> str | None:
    path, _ = QFileDialog.getSaveFileName(
        parent, title, suggested, file_filter
    )
    if not path:
        return None
    remember_directory(path)
    return path


def _pick_folder(parent: QWidget, title: str) -> str | None:
    chosen = QFileDialog.getExistingDirectory(parent, title, last_directory())
    if not chosen:
        return None
    remember_directory(chosen)
    return chosen


def _page_indices_from_text(text: str, page_count: int) -> list[int] | None:
    """Empty → all pages (``None``); invalid → empty list; else flat 0-based indices."""
    raw = text.strip()
    if not raw:
        return None
    parsed = parse_page_ranges(raw, page_count)
    if not parsed:
        return []
    indices: list[int] = []
    for start, end in parsed:
        indices.extend(range(start, end + 1))
    return sorted(set(indices))


def _configure_convert_to_pdf(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    hint = QLabel(
        "Drop one or more documents. A single file asks where to save; "
        "multiple files write PDFs into a folder you choose."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = [p for p in shell.drop_zone.paths() if Path(p).is_file()]
        if not paths:
            QMessageBox.warning(
                shell, shell.WINDOW_TITLE, "Choose at least one valid file."
            )
            return
        unsupported = [p for p in paths if not is_native_import_path(p)]
        if unsupported:
            names = ", ".join(Path(p).name for p in unsupported[:3])
            QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                f"Unsupported format for Convert to PDF:\n{names}",
            )
            return

        if len(paths) == 1:
            source = paths[0]
            suggested = str(Path(source).with_suffix(".pdf"))
            output = _pick_save_path(
                shell,
                "Save PDF",
                suggested,
                "PDF files (*.pdf);;All files (*)",
            )
            if not output:
                return
            if not output.lower().endswith(".pdf"):
                output = f"{output}.pdf"
            run_tool_job(
                shell,
                job_type="import_to_pdf",
                inputs=[source],
                output=output,
                progress_message="Converting to PDF…",
            )
            return

        folder = _pick_folder(shell, "Choose output folder")
        if not folder:
            return
        predicted = [Path(folder) / f"{Path(p).stem}.pdf" for p in paths]
        run_tool_job(
            shell,
            job_type="import_to_pdf",
            inputs=paths,
            output=str(predicted[0]),
            options={"output_dir": folder},
            existing_paths=[p for p in predicted if p.exists()],
            progress_message="Converting files…",
            success_toast=f"Wrote {len(paths)} PDF(s)",
        )

    shell.set_run_handler(on_run)


def _build_export_options() -> tuple[QWidget, QComboBox, QLineEdit, QDoubleSpinBox]:
    host = QWidget()
    form = QFormLayout(host)
    form.setContentsMargins(0, 0, 0, 0)

    fmt = QComboBox()
    for spec in export_formats(available_only=True):
        fmt.addItem(spec.label, spec.id)
    form.addRow("Format", fmt)

    ranges = QLineEdit()
    ranges.setPlaceholderText("e.g. 1-3,5 — leave blank for all pages")
    form.addRow("Pages", ranges)
    hint = QLabel("1-based ranges; selection from the editor is used when possible.")
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow("", hint)

    dpi = QDoubleSpinBox()
    dpi.setRange(36.0, 600.0)
    dpi.setValue(144.0)
    dpi.setDecimals(0)
    dpi.setSuffix(" dpi")
    form.addRow("DPI", dpi)

    return host, fmt, ranges, dpi


def _configure_export_from_pdf(
    shell: ToolShellWindow,
    *,
    range_prefill: str = "",
) -> None:
    options, fmt, ranges, dpi = _build_export_options()
    shell.set_options_widget(options)
    shell._format_combo = fmt  # type: ignore[attr-defined]
    shell._ranges_edit = ranges  # type: ignore[attr-defined]
    shell._dpi_spin = dpi  # type: ignore[attr-defined]
    if range_prefill:
        ranges.setText(range_prefill)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths or not Path(paths[0]).is_file():
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "Choose a valid source PDF.")
            return
        source = paths[0]
        format_id = fmt.currentData()
        if not format_id:
            QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                "No export formats are available. Install optional codecs if needed.",
            )
            return

        try:
            page_count = pdf_page_count(source)
        except Exception as exc:
            QMessageBox.warning(
                shell, shell.WINDOW_TITLE, f"Could not open PDF:\n{exc}"
            )
            return

        page_indices = _page_indices_from_text(ranges.text(), page_count)
        if page_indices is not None and len(page_indices) == 0:
            QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                "Enter page ranges like 1-3,5,7-9, or leave blank for all pages.",
            )
            return
        resolved_pages = (
            page_indices if page_indices is not None else list(range(page_count))
        )
        if not resolved_pages:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "This PDF has no pages.")
            return

        stem = Path(source).stem
        suffix_map = {
            "png": ".png",
            "jpeg": ".jpg",
            "webp": ".webp",
            "svg": ".svg",
            "text": ".txt",
            "json": ".json",
            "xml": ".xml",
            "cbz": ".cbz",
            "csv": ".csv",
            "tables_json": ".json",
            "xlsx": ".xlsx",
        }
        suffix = suffix_map[format_id]

        if format_id in MULTI_PAGE_EXPORT_IDS:
            folder = _pick_folder(shell, "Choose output folder")
            if not folder:
                return
            template = Path(folder) / f"{stem}{suffix}"
            predicted = predicted_export_paths(
                template,
                format_id=format_id,
                pages=resolved_pages,
            )
            pages_opt = page_indices  # None = all pages in handler
            run_tool_job(
                shell,
                job_type="export_from_pdf",
                inputs=[source],
                output=str(predicted[0]),
                options={
                    "format_id": format_id,
                    "pages": pages_opt,
                    "dpi": dpi.value(),
                    "output_dir": folder,
                    "base_name": stem,
                },
                existing_paths=[p for p in predicted if p.exists()],
                progress_message="Exporting…",
                success_toast=f"Wrote {len(predicted)} file(s)",
            )
            return

        suggested = str(Path(source).with_name(f"{stem}{suffix}"))
        label = fmt.currentText()
        output = _pick_save_path(
            shell,
            f"Save {label}",
            suggested,
            f"{label} (*{suffix});;All files (*)",
        )
        if not output:
            return
        if not output.lower().endswith(suffix):
            output = f"{output}{suffix}"
        run_tool_job(
            shell,
            job_type="export_from_pdf",
            inputs=[source],
            output=output,
            options={
                "format_id": format_id,
                "pages": page_indices,
                "dpi": dpi.value(),
            },
            progress_message="Exporting…",
        )

    shell.set_run_handler(on_run)


def open_conversion_shell(tools: ToolsWindow, tool_id: str) -> ToolShellWindow | None:
    """Lazy-create / raise Convert to PDF or Export from PDF shell."""
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    if tool_id not in SHELL_CONVERT_IDS:
        return None
    entry = next((e for e in TOOL_CATALOGUE if e.id == tool_id), None)
    if entry is None:
        return None

    store = tool_shell_store(tools)  # type: ignore[assignment]

    shell = store.get(tool_id)
    ctx = editor_pdf_context(tools.editor)

    if shell is None:
        if tool_id == "convert_to_pdf":
            shell = ToolShellWindow(
                title=entry.title,
                description=entry.description,
                help_text=entry.help_text,
                editor=tools.editor,
                window_manager=getattr(tools, "_window_manager", None),
                multi=True,
                accept=lambda p: is_native_import_path(p),
                dialog_filter=import_to_pdf_dialog_filter(available_only=True),
                browse_title=f"Choose files — {entry.title}",
                empty_prompt=EMPTY_PROMPT_DOCUMENTS,
            )
            _configure_convert_to_pdf(shell)
        else:
            shell = ToolShellWindow(
                title=entry.title,
                description=entry.description,
                help_text=entry.help_text,
                editor=tools.editor,
                window_manager=getattr(tools, "_window_manager", None),
                multi=False,
                accept=is_pdf_path,
                dialog_filter=_PDF_FILTER,
                browse_title=f"Choose PDF — {entry.title}",
            )
            _configure_export_from_pdf(
                shell,
                range_prefill=ctx.range_prefill if ctx is not None else "",
            )
        store[tool_id] = shell
    else:
        shell.set_editor(tools.editor)
        if tool_id == "export_from_pdf" and ctx is not None and ctx.range_prefill:
            ranges_edit = getattr(shell, "_ranges_edit", None)
            if ranges_edit is not None:
                ranges_edit.setText(ctx.range_prefill)

    if tool_id == "export_from_pdf" and ctx is not None and Path(ctx.path).is_file():
        shell.drop_zone.set_paths([ctx.path])

    present_tool_page(tools.editor, shell, page_id=f"tool:{tool_id}")
    return shell
