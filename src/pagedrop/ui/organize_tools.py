"""Organize / layout Tools hub dialogs and job launch (Phase 24 UI)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core import pdf_tools
from pagedrop.core.jobs import SerializedJobRunner
from pagedrop.core.organize_jobs import register_organize_handlers
from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.tool_shell import SHELL_ORGANIZE_IDS, open_organize_shell, run_tool_job
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

# ToolShellWindow (Phase 22b) currently wires only split / reverse.
# Everything else is an explicit exception until the shared shell gets the
# richer parameter widgets needed for these tools.
ORGANIZE_MODAL_TOOL_EXCEPTIONS: dict[str, str] = {
    "alternate": "Modal form: requires two-input selection in one dialog.",
    "n_up": "Modal form: multiple numeric/layout fields.",
    "booklet": "Modal form: simple but still dedicated parameters UI.",
    "posterize": "Modal form: grid/layout fields.",
    "divide": "Modal form: direction + per-page transforms.",
    "combine": "Modal form: per-page transforms; keep single-action modal.",
    "normalize": "Modal form: paper presets + sizing options.",
    "attachments": "Modal form: action picker + file/folder browsing.",
    "metadata": "Modal form: typed metadata fields with optional load button.",
    "page_labels": "Modal form: label style + starting page controls.",
    "zip": "Modal form: multi-input semicolon list picker.",
}

# Dedicated modeless window exception (still uses job runner for heatmap export).
ORGANIZE_DEDICATED_WINDOW_EXCEPTIONS: dict[str, str] = {
    "compare": "Dedicated CompareWindow UI; heatmap export shows overall diff ratio.",
}


def _tool_description(tool_id: str) -> str | None:
    # Lazy import to avoid circular imports at module import time.
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    entry = next((e for e in TOOL_CATALOGUE if e.id == tool_id), None)
    return entry.description if entry is not None else None


_PAPER_SIZES_PT: dict[str, tuple[float, float]] = {
    "A4": (595.0, 842.0),
    "Letter": (612.0, 792.0),
    "Legal": (612.0, 1008.0),
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

    page_count = 0
    try:
        loader = PdfLoader(path)
        try:
            page_count = loader.page_count
        finally:
            loader.close()
    except Exception:
        page_count = model.logical_count()

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
        page_count=page_count,
        range_prefill=range_prefill,
    )


def _pick_open_pdf(parent: QWidget, title: str, start: str = "") -> str | None:
    path, _ = QFileDialog.getOpenFileName(
        parent,
        title,
        start or last_directory(),
        "PDF files (*.pdf);;All files (*)",
    )
    if not path:
        return None
    remember_directory(path)
    return path


def _pick_open_pdfs(parent: QWidget, title: str) -> list[str]:
    paths, _ = QFileDialog.getOpenFileNames(
        parent,
        title,
        last_directory(),
        "PDF files (*.pdf);;All files (*)",
    )
    if paths:
        remember_directory(paths[0])
    return list(paths)


def _pick_save_pdf(parent: QWidget, title: str, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(
        parent,
        title,
        suggested,
        "PDF files (*.pdf);;All files (*)",
    )
    if not path:
        return None
    if not path.lower().endswith(".pdf"):
        path = f"{path}.pdf"
    remember_directory(path)
    return path


def _pick_save_zip(parent: QWidget, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(
        parent,
        "Save ZIP archive",
        suggested,
        "ZIP archives (*.zip);;All files (*)",
    )
    if not path:
        return None
    if not path.lower().endswith(".zip"):
        path = f"{path}.zip"
    remember_directory(path)
    return path


def _pick_folder(parent: QWidget, title: str) -> str | None:
    folder = QFileDialog.getExistingDirectory(
        parent, title, last_directory()
    )
    if not folder:
        return None
    remember_directory(folder)
    return folder


def _default_out_path(source: str, suffix: str) -> str:
    src = Path(source)
    return str(src.with_name(f"{src.stem}_{suffix}.pdf"))


class _PathRow(QWidget):
    """Sentence-case browse row for a single file path."""

    def __init__(
        self,
        parent: QWidget,
        *,
        browse_title: str,
        initial: str = "",
        multi: bool = False,
    ) -> None:
        super().__init__(parent)
        self._browse_title = browse_title
        self._multi = multi
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit(initial)
        browse = QPushButton("Browse…")
        browse.setObjectName("ToolbarSecondary")
        browse.clicked.connect(self._browse)
        layout.addWidget(self._edit, stretch=1)
        layout.addWidget(browse)

    def text(self) -> str:
        return self._edit.text().strip()

    def set_text(self, value: str) -> None:
        self._edit.setText(value)

    def _browse(self) -> None:
        if self._multi:
            paths = _pick_open_pdfs(self, self._browse_title)
            if paths:
                self._edit.setText(";".join(paths))
            return
        path = _pick_open_pdf(self, self._browse_title, self.text())
        if path:
            self._edit.setText(path)


def _form_dialog(
    parent: QWidget,
    *,
    title: str,
    description: str | None = None,
    build,
    collect=None,
) -> dict | None:
    """Build a simple OK/Cancel form; *build(form, widgets)* fills fields.

    If *collect* is given, it runs while the dialog is still alive and its
    return value is what callers get (avoids reading deleted Qt children).
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    root = QVBoxLayout(dialog)
    if description:
        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setObjectName("OrganizeModalDescription")
        root.addWidget(desc)
    form = QFormLayout()
    widgets: dict = {}
    build(form, widgets)
    root.addLayout(form)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    root.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    if collect is not None:
        return collect(widgets)
    # Keep the QDialog referenced so child QWidgets stay alive for the caller.
    widgets["_dialog"] = dialog
    return widgets


def _run_organize_job(
    tools: ToolsWindow,
    *,
    job_type: str,
    inputs: list[str],
    output: str,
    options: dict | None = None,
    existing_paths: list[Path] | None = None,
    progress_message: str = "Working…",
    success_toast: str | None = None,
) -> None:
    run_tool_job(
        tools,
        job_type=job_type,
        inputs=inputs,
        output=output,
        options=options,
        existing_paths=existing_paths,
        progress_message=progress_message,
        success_toast=success_toast,
    )


# --- Per-tool dialogs -------------------------------------------------------


def _launch_single_transform(
    tools: ToolsWindow,
    *,
    title: str,
    job_type: str,
    suffix: str,
    ctx: EditorPdfContext | None,
    extra_build=None,
    collect_options=None,
    progress_message: str = "Working…",
) -> None:
    initial = ctx.path if ctx else ""

    def build(form: QFormLayout, w: dict) -> None:
        w["source"] = _PathRow(tools, browse_title=f"Choose PDF — {title}", initial=initial)
        form.addRow("Source PDF", w["source"])
        if extra_build is not None:
            extra_build(form, w)

    widgets = _form_dialog(
        tools, title=title, description=_tool_description(job_type), build=build
    )
    if widgets is None:
        return
    source = widgets["source"].text()
    if not source or not Path(source).is_file():
        QMessageBox.warning(tools, title, "Choose a valid source PDF.")
        return
    options = collect_options(widgets) if collect_options else {}
    if options is None:
        return
    suggested = _default_out_path(source, suffix)
    output = _pick_save_pdf(tools, f"Save {title.lower()} PDF", suggested)
    if not output:
        return
    _run_organize_job(
        tools,
        job_type=job_type,
        inputs=[source],
        output=output,
        options=options,
        progress_message=progress_message,
    )


def _launch_n_up(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    def extra(form: QFormLayout, w: dict) -> None:
        w["rows"] = QSpinBox()
        w["rows"].setRange(1, 8)
        w["rows"].setValue(2)
        w["cols"] = QSpinBox()
        w["cols"].setRange(1, 8)
        w["cols"].setValue(2)
        form.addRow("Rows", w["rows"])
        form.addRow("Columns", w["cols"])

    def opts(w: dict) -> dict:
        return {"rows": w["rows"].value(), "cols": w["cols"].value()}

    _launch_single_transform(
        tools,
        title="N-up",
        job_type="n_up",
        suffix="nup",
        ctx=ctx,
        extra_build=extra,
        collect_options=opts,
        progress_message="Building N-up…",
    )


def _launch_booklet(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    _launch_single_transform(
        tools,
        title="Booklet",
        job_type="booklet",
        suffix="booklet",
        ctx=ctx,
        progress_message="Building booklet…",
    )


def _launch_posterize(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    def extra(form: QFormLayout, w: dict) -> None:
        w["rows"] = QSpinBox()
        w["rows"].setRange(1, 8)
        w["rows"].setValue(2)
        w["cols"] = QSpinBox()
        w["cols"].setRange(1, 8)
        w["cols"].setValue(2)
        form.addRow("Rows", w["rows"])
        form.addRow("Columns", w["cols"])

    def opts(w: dict) -> dict:
        return {"rows": w["rows"].value(), "cols": w["cols"].value()}

    _launch_single_transform(
        tools,
        title="Posterize",
        job_type="posterize",
        suffix="poster",
        ctx=ctx,
        extra_build=extra,
        collect_options=opts,
        progress_message="Posterizing…",
    )


def _launch_divide(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    def extra(form: QFormLayout, w: dict) -> None:
        w["direction"] = QComboBox()
        w["direction"].addItem("Vertical (left / right)", "vertical")
        w["direction"].addItem("Horizontal (top / bottom)", "horizontal")
        form.addRow("Direction", w["direction"])

    def opts(w: dict) -> dict:
        return {"direction": w["direction"].currentData()}

    _launch_single_transform(
        tools,
        title="Divide pages",
        job_type="divide",
        suffix="divided",
        ctx=ctx,
        extra_build=extra,
        collect_options=opts,
        progress_message="Dividing pages…",
    )


def _launch_combine(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    _launch_single_transform(
        tools,
        title="Combine to long page",
        job_type="combine",
        suffix="long",
        ctx=ctx,
        progress_message="Combining pages…",
    )


def _launch_normalize(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    def extra(form: QFormLayout, w: dict) -> None:
        w["size"] = QComboBox()
        for name in _PAPER_SIZES_PT:
            w["size"].addItem(name, name)
        form.addRow("Target size", w["size"])
        w["strategy"] = QComboBox()
        w["strategy"].addItem("Fit (keep aspect ratio)", "fit")
        w["strategy"].addItem("Fill (may distort)", "fill")
        form.addRow("Strategy", w["strategy"])
        w["margins"] = QSpinBox()
        w["margins"].setRange(0, 144)
        w["margins"].setSuffix(" pt")
        form.addRow("Margins", w["margins"])

    def opts(w: dict) -> dict | None:
        key = w["size"].currentData()
        width, height = _PAPER_SIZES_PT[key]
        return {
            "width_pt": width,
            "height_pt": height,
            "strategy": w["strategy"].currentData(),
            "margins_pt": float(w["margins"].value()),
        }

    _launch_single_transform(
        tools,
        title="Normalize page size",
        job_type="normalize",
        suffix="normalized",
        ctx=ctx,
        extra_build=extra,
        collect_options=opts,
        progress_message="Normalizing page size…",
    )


def _launch_alternate(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    initial = ctx.path if ctx else ""

    def build(form: QFormLayout, w: dict) -> None:
        w["a"] = _PathRow(tools, browse_title="Choose first PDF", initial=initial)
        w["b"] = _PathRow(tools, browse_title="Choose second PDF")
        form.addRow("PDF A", w["a"])
        form.addRow("PDF B", w["b"])
        w["start_a"] = QCheckBox("Start with PDF A")
        w["start_a"].setChecked(True)
        form.addRow("", w["start_a"])

    widgets = _form_dialog(
        tools,
        title="Alternate pages",
        description=_tool_description("alternate"),
        build=build,
    )
    if widgets is None:
        return
    a = widgets["a"].text()
    b = widgets["b"].text()
    if not a or not Path(a).is_file() or not b or not Path(b).is_file():
        QMessageBox.warning(tools, "Alternate pages", "Choose two valid PDFs.")
        return
    output = _pick_save_pdf(
        tools, "Save alternated PDF", _default_out_path(a, "alternated")
    )
    if not output:
        return
    _run_organize_job(
        tools,
        job_type="alternate",
        inputs=[a, b],
        output=output,
        options={"start_with_a": widgets["start_a"].isChecked()},
        progress_message="Alternating pages…",
    )


def _launch_zip(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    initial = ctx.path if ctx else ""

    def build(form: QFormLayout, w: dict) -> None:
        w["files"] = _PathRow(
            tools,
            browse_title="Choose PDFs to zip",
            initial=initial,
            multi=True,
        )
        form.addRow("PDF files", w["files"])
        hint = QLabel("Separate multiple paths with semicolons, or use Browse…")
        hint.setWordWrap(True)
        form.addRow("", hint)

    widgets = _form_dialog(
        tools, title="ZIP PDFs", description=_tool_description("zip"), build=build
    )
    if widgets is None:
        return
    paths = [p.strip() for p in widgets["files"].text().split(";") if p.strip()]
    if not paths or any(not Path(p).is_file() for p in paths):
        QMessageBox.warning(tools, "ZIP PDFs", "Choose one or more valid PDF files.")
        return
    suggested = str(Path(paths[0]).with_suffix(".zip"))
    if len(paths) > 1:
        suggested = str(Path(paths[0]).with_name("pdfs.zip"))
    output = _pick_save_zip(tools, suggested)
    if not output:
        return
    _run_organize_job(
        tools,
        job_type="zip",
        inputs=paths,
        output=output,
        progress_message="Creating ZIP…",
    )


def _launch_compare(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    from pagedrop.ui.compare_window import CompareWindow

    initial = ctx.path if ctx else ""
    window = getattr(tools, "_compare_window", None)
    if window is None:
        window = CompareWindow()
        tools._compare_window = window  # type: ignore[attr-defined]
    if initial:
        window.prefill_a(initial)
    window.show()
    window.raise_()
    window.activateWindow()


def _launch_metadata(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    initial = ctx.path if ctx else ""

    def build(form: QFormLayout, w: dict) -> None:
        w["source"] = _PathRow(tools, browse_title="Choose PDF", initial=initial)
        form.addRow("Source PDF", w["source"])
        for key, label in (
            ("title", "Title"),
            ("author", "Author"),
            ("subject", "Subject"),
            ("keywords", "Keywords"),
        ):
            w[key] = QLineEdit()
            form.addRow(label, w[key])
        w["strip"] = QCheckBox("Strip all metadata instead (including XMP)")
        form.addRow("", w["strip"])

        def load_meta() -> None:
            path = w["source"].text()
            if not path or not Path(path).is_file():
                return
            try:
                meta = pdf_tools.metadata_get(path)
            except Exception as exc:
                QMessageBox.warning(tools, "Metadata", f"Could not read metadata:\n{exc}")
                return
            for key in ("title", "author", "subject", "keywords"):
                w[key].setText(str(meta.get(key) or ""))

        load_btn = QPushButton("Load from file")
        load_btn.setObjectName("ToolbarSecondary")
        load_btn.clicked.connect(load_meta)
        form.addRow("", load_btn)
        if initial:
            load_meta()

    widgets = _form_dialog(
        tools, title="Metadata", description=_tool_description("metadata"), build=build
    )
    if widgets is None:
        return
    source = widgets["source"].text()
    if not source or not Path(source).is_file():
        QMessageBox.warning(tools, "Metadata", "Choose a valid source PDF.")
        return
    output = _pick_save_pdf(
        tools, "Save metadata PDF", _default_out_path(source, "metadata")
    )
    if not output:
        return
    if widgets["strip"].isChecked():
        _run_organize_job(
            tools,
            job_type="metadata_strip",
            inputs=[source],
            output=output,
            progress_message="Stripping metadata…",
        )
        return
    updates = {
        key: widgets[key].text()
        for key in ("title", "author", "subject", "keywords")
    }
    _run_organize_job(
        tools,
        job_type="metadata_set",
        inputs=[source],
        output=output,
        options={"updates": updates},
        progress_message="Updating metadata…",
    )


def _launch_page_labels(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    def extra(form: QFormLayout, w: dict) -> None:
        w["style"] = QComboBox()
        for label, style in (
            ("Decimal (1, 2, 3)", "D"),
            ("Roman upper (I, II)", "R"),
            ("Roman lower (i, ii)", "r"),
            ("Letters upper (A, B)", "A"),
            ("Letters lower (a, b)", "a"),
        ):
            w["style"].addItem(label, style)
        form.addRow("Style", w["style"])
        w["start"] = QSpinBox()
        w["start"].setRange(1, 9999)
        w["start"].setValue(1)
        form.addRow("First page number", w["start"])
        w["prefix"] = QLineEdit()
        form.addRow("Prefix", w["prefix"])

    def opts(w: dict) -> dict:
        return {
            "labels": [
                {
                    "startpage": 0,
                    "prefix": w["prefix"].text(),
                    "style": w["style"].currentData(),
                    "firstpagenum": w["start"].value(),
                }
            ]
        }

    _launch_single_transform(
        tools,
        title="Page labels",
        job_type="page_labels",
        suffix="labels",
        ctx=ctx,
        extra_build=extra,
        collect_options=opts,
        progress_message="Setting page labels…",
    )


def _launch_attachments(tools: ToolsWindow, ctx: EditorPdfContext | None) -> None:
    initial = ctx.path if ctx else ""

    def build(form: QFormLayout, w: dict) -> None:
        w["source"] = _PathRow(tools, browse_title="Choose PDF", initial=initial)
        form.addRow("Source PDF", w["source"])
        w["action"] = QComboBox()
        w["action"].addItem("Add file", "add")
        w["action"].addItem("Remove by name", "remove")
        w["action"].addItem("Extract to folder", "extract")
        form.addRow("Action", w["action"])
        w["name"] = QLineEdit()
        form.addRow("Attachment name", w["name"])
        w["file"] = QLineEdit()
        file_row = QHBoxLayout()
        file_row.addWidget(w["file"], stretch=1)
        browse = QPushButton("Browse…")
        browse.setObjectName("ToolbarSecondary")

        def pick_file() -> None:
            path, _ = QFileDialog.getOpenFileName(
                tools, "Choose file to attach", last_directory()
            )
            if path:
                remember_directory(path)
                w["file"].setText(path)
                if not w["name"].text().strip():
                    w["name"].setText(Path(path).name)

        browse.clicked.connect(pick_file)
        file_row.addWidget(browse)
        form.addRow("File to add", file_row)
        w["replace"] = QCheckBox("Replace if name already exists")
        form.addRow("", w["replace"])

    widgets = _form_dialog(
        tools,
        title="Attachments",
        description=_tool_description("attachments"),
        build=build,
    )
    if widgets is None:
        return
    source = widgets["source"].text()
    if not source or not Path(source).is_file():
        QMessageBox.warning(tools, "Attachments", "Choose a valid source PDF.")
        return
    action = widgets["action"].currentData()
    name = widgets["name"].text().strip()

    if action == "extract":
        if not name:
            QMessageBox.warning(tools, "Attachments", "Enter the attachment name.")
            return
        folder = _pick_folder(tools, "Extract attachment to folder")
        if not folder:
            return
        safe_name = Path(name).name or "attachment.bin"
        out = Path(folder) / safe_name
        if out.exists():
            stem, suffix = out.stem, out.suffix
            n = 1
            while True:
                candidate = Path(folder) / f"{stem}_{n}{suffix}"
                if not candidate.exists():
                    out = candidate
                    break
                n += 1
        _run_organize_job(
            tools,
            job_type="attachment_extract",
            inputs=[source],
            output=str(out),
            options={"name": name},
            progress_message="Extracting attachment…",
            success_toast=f"Extracted {out.name}",
        )
        return

    if not name:
        QMessageBox.warning(tools, "Attachments", "Enter the attachment name.")
        return
    output = _pick_save_pdf(
        tools, "Save PDF with attachments", _default_out_path(source, "attachments")
    )
    if not output:
        return
    if action == "add":
        file_path = widgets["file"].text().strip()
        if not file_path or not Path(file_path).is_file():
            QMessageBox.warning(tools, "Attachments", "Choose a file to attach.")
            return
        _run_organize_job(
            tools,
            job_type="attachment_add",
            inputs=[source],
            output=output,
            options={
                "name": name,
                "file_path": file_path,
                "replace": widgets["replace"].isChecked(),
            },
            progress_message="Adding attachment…",
        )
        return

    _run_organize_job(
        tools,
        job_type="attachment_remove",
        inputs=[source],
        output=output,
        options={"name": name},
        progress_message="Removing attachment…",
    )


_LAUNCHERS = {
    "alternate": _launch_alternate,
    "n_up": _launch_n_up,
    "booklet": _launch_booklet,
    "posterize": _launch_posterize,
    "divide": _launch_divide,
    "combine": _launch_combine,
    "normalize": _launch_normalize,
    "attachments": _launch_attachments,
    "metadata": _launch_metadata,
    "page_labels": _launch_page_labels,
    "zip": _launch_zip,
    "compare": _launch_compare,
}


def ensure_organize_runner(temp_manager: TempManager | None = None) -> SerializedJobRunner:
    from pagedrop.core.native_conversion_jobs import register_native_conversion_handlers

    runner = SerializedJobRunner(temp_manager)
    register_organize_handlers(runner)
    register_native_conversion_handlers(runner)
    return runner


def launch_organize_tool(tools: ToolsWindow, tool_id: str) -> None:
    """Open the parameter dialog or modeless shell for an organize tool."""
    if tool_id in SHELL_ORGANIZE_IDS:
        open_organize_shell(tools, tool_id)
        return
    launcher = _LAUNCHERS.get(tool_id)
    if launcher is None:
        tools.statusBar().showMessage(f"Unknown organize tool: {tool_id}")
        return
    if tools.is_job_running():
        QMessageBox.information(
            tools,
            tools.WINDOW_TITLE,
            "A job is already running. Wait for it to finish or cancel it.",
        )
        return
    ctx = editor_pdf_context(tools.editor)
    launcher(tools, ctx)
