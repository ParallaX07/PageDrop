"""Organize / layout Tools hub launch + shared editor context (Phase 24 / O7)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QWidget

from pagedrop.core.jobs import SerializedJobRunner
from pagedrop.core.organize_jobs import register_organize_handlers
from pagedrop.core.pdf_service import page_count as pdf_page_count
from pagedrop.utils.page_jump import format_indices_as_ranges
from pagedrop.utils.temp_manager import TempManager

if TYPE_CHECKING:
    from pagedrop.ui.tools_window import ToolsWindow

ORGANIZE_TOOL_IDS: frozenset[str] = frozenset(
    {
        "split",
        "alternate",
        "reverse",
        "n_up",
        "booklet",
        "posterize",
        "divide",
        "combine",
        "normalize",
        "attachments",
        "metadata",
        "page_labels",
        "zip",
        "compare",
    }
)

# Dedicated modeless window exception (still uses job runner for heatmap export).
ORGANIZE_DEDICATED_WINDOW_EXCEPTIONS: dict[str, str] = {
    "compare": "Dedicated CompareWindow UI; heatmap export shows overall diff ratio.",
}


@dataclass(frozen=True)
class EditorPdfContext:
    path: str
    page_count: int
    range_prefill: str = ""


def editor_pdf_context(editor: QWidget | None) -> EditorPdfContext | None:
    """Active tab path + optional split/extract range prefill from selection."""
    if editor is None:
        return None
    active = getattr(editor, "_active_tab", None)
    tab = active() if callable(active) else None
    if tab is None or getattr(tab, "edit_model", None) is None:
        return None
    model = tab.edit_model
    path = model.save_path or model.original_path
    if not path or not Path(path).is_file():
        path = model.original_path
    if not path or not Path(path).is_file():
        return None

    try:
        count = pdf_page_count(path)
    except Exception:
        count = model.logical_count()

    range_prefill = ""
    grid = getattr(tab, "thumbnail_grid", None)
    selection = set()
    if grid is not None:
        selection = set(grid.selection_manager.selection)
    if selection:
        source_indices: list[int] = []
        source_paths: set[str] = set()
        for logical in sorted(selection):
            if logical < 0 or logical >= model.logical_count():
                continue
            ref = model.page_at(logical)
            source_paths.add(ref.source_path)
            source_indices.append(ref.source_index)
        # Prefill only when selection maps to one on-disk source file.
        if len(source_paths) == 1 and Path(next(iter(source_paths))).resolve() == Path(
            path
        ).resolve():
            range_prefill = format_indices_as_ranges(source_indices)

    return EditorPdfContext(
        path=str(path),
        page_count=count,
        range_prefill=range_prefill,
    )


def _launch_compare(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    from pagedrop.ui.compare_window import CompareWindow
    from pagedrop.ui.tool_page import present_tool_page

    initial = ctx.path if ctx else ""
    editor = tools.editor
    page_id = CompareWindow.PAGE_ID
    window = None
    if editor is not None:
        pages = getattr(editor, "_tool_pages", None)
        if isinstance(pages, dict):
            candidate = pages.get(page_id)
            try:
                if candidate is not None and editor._tab_manager.indexOf(candidate) >= 0:  # type: ignore[attr-defined]
                    window = candidate
            except RuntimeError:
                window = None
    if window is None:
        window = getattr(tools, "_compare_window", None)
    if window is None:
        window = CompareWindow(editor=editor)
    else:
        window.set_editor(editor)
    tools._compare_window = window  # type: ignore[attr-defined]
    if initial:
        window.prefill_a(initial)
    present_tool_page(editor, window, page_id=page_id)


# Process-wide shared runner — Compare + JobChromeMixin must not mkdtemp per call.
_organize_runner: SerializedJobRunner | None = None


def ensure_organize_runner(temp_manager: TempManager | None = None) -> SerializedJobRunner:
    """Return the process-wide organize/tool job runner (create once).

    Optional *temp_manager* is used only on the first call; later callers reuse
    the cached runner (and its ``TempManager``).
    """
    global _organize_runner
    if _organize_runner is not None:
        return _organize_runner

    from pagedrop.core.modify_jobs import register_modify_handlers
    from pagedrop.core.native_conversion_jobs import register_native_conversion_handlers
    from pagedrop.core.ocr_jobs import register_ocr_handlers
    from pagedrop.core.office_conversion_jobs import register_office_conversion_handlers
    from pagedrop.core.optimize_secure_jobs import register_optimize_secure_handlers
    from pagedrop.core.pdf_to_docx_jobs import register_pdf_to_docx_handlers

    runner = SerializedJobRunner(temp_manager)
    register_organize_handlers(runner)
    register_native_conversion_handlers(runner)
    register_office_conversion_handlers(runner)
    register_optimize_secure_handlers(runner)
    register_modify_handlers(runner)
    register_ocr_handlers(runner)
    register_pdf_to_docx_handlers(runner)
    _organize_runner = runner
    return runner


def launch_organize_tool(tools: ToolsWindow, tool_id: str) -> None:
    """Open the modeless shell (or Compare page) for an organize tool."""
    from pagedrop.ui.organize_shell import SHELL_ORGANIZE_IDS, open_organize_shell

    if tool_id in SHELL_ORGANIZE_IDS:
        open_organize_shell(tools, tool_id)
        return
    if tool_id in ORGANIZE_DEDICATED_WINDOW_EXCEPTIONS:
        ctx = editor_pdf_context(tools.editor)
        _launch_compare(tools, ctx)
        return
    tools.statusBar().showMessage(f"Unknown organize tool: {tool_id}")
