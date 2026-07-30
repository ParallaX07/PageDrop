"""Organize / layout — modeless shells (Phase 22b pattern; O7 finished modal migration)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from pagedrop.core import pdf_tools
from pagedrop.core.jobs import JobCancelledError, preflight_pdf_inputs
from pagedrop.core.pdf_service import page_count as pdf_page_count
from pagedrop.ui.dialogs import prompt_pdf_password
from pagedrop.ui.organize_tools import editor_pdf_context
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.tool_page import present_tool_page, tool_shell_store
from pagedrop.ui.tool_shell import ToolShellWindow, run_tool_job
from pagedrop.utils.page_jump import parse_page_ranges

if TYPE_CHECKING:
    from pagedrop.ui.organize_tools import EditorPdfContext
    from pagedrop.ui.tools_window import ToolsWindow

# All Organize tiles except Compare (dedicated CompareWindow).
SHELL_ORGANIZE_IDS: frozenset[str] = frozenset(
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
    }
)

_PDF_FILTER = "PDF files (*.pdf);;All files (*)"
_ZIP_FILTER = "ZIP archives (*.zip);;All files (*)"

_PAPER_SIZES_PT: dict[str, tuple[float, float]] = {
    "A4": (595.0, 842.0),
    "Letter": (612.0, 792.0),
    "Legal": (612.0, 1008.0),
}

_MULTI_DROP_IDS: frozenset[str] = frozenset({"zip", "alternate"})


def _pick_save_pdf(parent: QWidget, title: str, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(parent, title, suggested, _PDF_FILTER)
    if not path:
        return None
    if not path.lower().endswith(".pdf"):
        path = f"{path}.pdf"
    remember_directory(path)
    return path


def _pick_save_zip(parent: QWidget, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(
        parent, "Save ZIP archive", suggested, _ZIP_FILTER
    )
    if not path:
        return None
    if not path.lower().endswith(".zip"):
        path = f"{path}.zip"
    remember_directory(path)
    return path


def _pick_folder(parent: QWidget, title: str) -> str | None:
    folder = QFileDialog.getExistingDirectory(parent, title, last_directory())
    if not folder:
        return None
    remember_directory(folder)
    return folder


def _default_out_path(source: str, suffix: str) -> str:
    src = Path(source)
    return str(src.with_name(f"{src.stem}_{suffix}.pdf"))


def _require_source(shell: ToolShellWindow) -> str | None:
    paths = shell.drop_zone.paths()
    if not paths or not Path(paths[0]).is_file():
        QMessageBox.warning(shell, shell.WINDOW_TITLE, "Choose a valid source PDF.")
        return None
    return paths[0]


def _configure_reverse(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    blank = QCheckBox("Add blank page at end")
    form.addRow("", blank)
    shell.set_options_widget(options)

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        output = _pick_save_pdf(
            shell, "Save reversed PDF", _default_out_path(source, "reversed")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="reverse",
            inputs=[source],
            output=output,
            options={"add_blank_page": blank.isChecked()},
            progress_message="Reversing pages…",
        )

    shell.set_run_handler(on_run)


def _configure_split(shell: ToolShellWindow, ctx: EditorPdfContext | None) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    ranges = QLineEdit()
    ranges.setPlaceholderText("e.g. 1-3,5,7-9")
    form.addRow("Page ranges", ranges)
    hint = QLabel("1-based ranges; selection from the editor is used when possible.")
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow("", hint)
    folder = QLineEdit()
    folder_row = QHBoxLayout()
    folder_row.addWidget(folder, stretch=1)
    browse = QPushButton("Browse…")
    browse.setObjectName("ToolbarSecondary")

    def pick() -> None:
        chosen = QFileDialog.getExistingDirectory(
            shell, "Choose output folder", last_directory()
        )
        if chosen:
            remember_directory(chosen)
            folder.setText(chosen)

    browse.clicked.connect(pick)
    folder_row.addWidget(browse)
    form.addRow("Output folder", folder_row)
    shell.set_options_widget(options)
    shell._ranges_edit = ranges  # type: ignore[attr-defined]
    shell._folder_edit = folder  # type: ignore[attr-defined]
    if ctx is not None and ctx.range_prefill:
        ranges.setText(ctx.range_prefill)

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        out_folder = folder.text().strip()
        ranges_text = ranges.text().strip()
        if not out_folder:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "Choose an output folder.")
            return
        try:
            page_count = pdf_page_count(source)
        except Exception as exc:
            QMessageBox.warning(
                shell, shell.WINDOW_TITLE, f"Could not open PDF:\n{exc}"
            )
            return
        parsed = parse_page_ranges(ranges_text, page_count)
        if not parsed:
            QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                "Enter page ranges like 1-3,5,7-9.",
            )
            return
        base_name = Path(source).stem
        predicted = pdf_tools.predicted_range_output_paths(
            parsed, out_folder, base_name=base_name
        )
        n = len(predicted)
        # ResultActionsBar binds to predicted[0]; say so when N>1 (O12).
        success = (
            f"Saved {n} files — showing first" if n > 1 else None
        )
        run_tool_job(
            shell,
            job_type="split",
            inputs=[source],
            output=str(predicted[0]),
            options={
                "ranges": parsed,
                "output_dir": out_folder,
                "base_name": base_name,
            },
            existing_paths=[p for p in predicted if p.exists()],
            progress_message="Splitting PDF…",
            success_toast=success,
        )

    shell.set_run_handler(on_run)


def _configure_n_up(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    # ponytail: UI caps N-up at 8×8 (common impose); core n_up_pdf has no hard
    # cap — raise the spin range only with a measured need for denser sheets.
    rows = QSpinBox()
    rows.setRange(1, 8)
    rows.setValue(2)
    cols = QSpinBox()
    cols.setRange(1, 8)
    cols.setValue(2)
    form.addRow("Rows", rows)
    form.addRow("Columns", cols)
    shell.set_options_widget(options)

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        output = _pick_save_pdf(
            shell, "Save n-up PDF", _default_out_path(source, "nup")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="n_up",
            inputs=[source],
            output=output,
            options={"rows": rows.value(), "cols": cols.value()},
            progress_message="Building N-up…",
        )

    shell.set_run_handler(on_run)


def _configure_booklet(shell: ToolShellWindow) -> None:
    shell.set_options_widget(QWidget())  # no options; drop + Run only

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        output = _pick_save_pdf(
            shell, "Save booklet PDF", _default_out_path(source, "booklet")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="booklet",
            inputs=[source],
            output=output,
            progress_message="Building booklet…",
        )

    shell.set_run_handler(on_run)


def _configure_posterize(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    rows = QSpinBox()
    rows.setRange(1, 8)
    rows.setValue(2)
    cols = QSpinBox()
    cols.setRange(1, 8)
    cols.setValue(2)
    form.addRow("Rows", rows)
    form.addRow("Columns", cols)
    shell.set_options_widget(options)

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        output = _pick_save_pdf(
            shell, "Save posterize PDF", _default_out_path(source, "poster")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="posterize",
            inputs=[source],
            output=output,
            options={"rows": rows.value(), "cols": cols.value()},
            progress_message="Posterizing…",
        )

    shell.set_run_handler(on_run)


def _configure_divide(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    direction = QComboBox()
    direction.addItem("Vertical (left / right)", "vertical")
    direction.addItem("Horizontal (top / bottom)", "horizontal")
    form.addRow("Direction", direction)
    shell.set_options_widget(options)

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        output = _pick_save_pdf(
            shell, "Save divide pages PDF", _default_out_path(source, "divided")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="divide",
            inputs=[source],
            output=output,
            options={"direction": direction.currentData()},
            progress_message="Dividing pages…",
        )

    shell.set_run_handler(on_run)


def _configure_combine(shell: ToolShellWindow) -> None:
    shell.set_options_widget(QWidget())

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        output = _pick_save_pdf(
            shell,
            "Save combine to long page PDF",
            _default_out_path(source, "long"),
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="combine",
            inputs=[source],
            output=output,
            progress_message="Combining pages…",
        )

    shell.set_run_handler(on_run)


def _configure_normalize(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    size = QComboBox()
    for name in _PAPER_SIZES_PT:
        size.addItem(name, name)
    form.addRow("Target size", size)
    strategy = QComboBox()
    strategy.addItem("Fit (keep aspect ratio)", "fit")
    strategy.addItem("Fill (may distort)", "fill")
    form.addRow("Strategy", strategy)
    margins = QSpinBox()
    margins.setRange(0, 144)
    margins.setSuffix(" pt")
    form.addRow("Margins", margins)
    shell.set_options_widget(options)

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        output = _pick_save_pdf(
            shell,
            "Save normalize page size PDF",
            _default_out_path(source, "normalized"),
        )
        if not output:
            return
        key = size.currentData()
        width, height = _PAPER_SIZES_PT[key]
        run_tool_job(
            shell,
            job_type="normalize",
            inputs=[source],
            output=output,
            options={
                "width_pt": width,
                "height_pt": height,
                "strategy": strategy.currentData(),
                "margins_pt": float(margins.value()),
            },
            progress_message="Normalizing page size…",
        )

    shell.set_run_handler(on_run)


def _configure_page_labels(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    style = QComboBox()
    for label, value in (
        ("Decimal (1, 2, 3)", "D"),
        ("Roman upper (I, II)", "R"),
        ("Roman lower (i, ii)", "r"),
        ("Letters upper (A, B)", "A"),
        ("Letters lower (a, b)", "a"),
    ):
        style.addItem(label, value)
    form.addRow("Style", style)
    start = QSpinBox()
    start.setRange(1, 9999)
    start.setValue(1)
    form.addRow("First page number", start)
    prefix = QLineEdit()
    form.addRow("Prefix", prefix)
    shell.set_options_widget(options)

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        output = _pick_save_pdf(
            shell, "Save page labels PDF", _default_out_path(source, "labels")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="page_labels",
            inputs=[source],
            output=output,
            options={
                "labels": [
                    {
                        "startpage": 0,
                        "prefix": prefix.text(),
                        "style": style.currentData(),
                        "firstpagenum": start.value(),
                    }
                ]
            },
            progress_message="Setting page labels…",
        )

    shell.set_run_handler(on_run)


def _configure_alternate(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    start_a = QCheckBox("Start with PDF A (first file)")
    start_a.setChecked(True)
    form.addRow("", start_a)
    hint = QLabel("Add exactly two PDFs. Order in the drop zone is A then B.")
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow("", hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if len(paths) != 2 or any(not Path(p).is_file() for p in paths):
            QMessageBox.warning(
                shell, shell.WINDOW_TITLE, "Choose exactly two valid PDFs."
            )
            return
        a, b = paths
        output = _pick_save_pdf(
            shell, "Save alternated PDF", _default_out_path(a, "alternated")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="alternate",
            inputs=[a, b],
            output=output,
            options={"start_with_a": start_a.isChecked()},
            progress_message="Alternating pages…",
        )

    shell.set_run_handler(on_run)


def _configure_zip(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    hint = QLabel("Drop or browse one or more PDFs to pack into a ZIP archive.")
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow("", hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths or any(not Path(p).is_file() for p in paths):
            QMessageBox.warning(
                shell, shell.WINDOW_TITLE, "Choose one or more valid PDF files."
            )
            return
        suggested = str(Path(paths[0]).with_suffix(".zip"))
        if len(paths) > 1:
            suggested = str(Path(paths[0]).with_name("pdfs.zip"))
        output = _pick_save_zip(shell, suggested)
        if not output:
            return
        run_tool_job(
            shell,
            job_type="zip",
            inputs=paths,
            output=output,
            progress_message="Creating ZIP…",
        )

    shell.set_run_handler(on_run)


def _configure_metadata(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    fields: dict[str, QLineEdit] = {}
    for key, label in (
        ("title", "Title"),
        ("author", "Author"),
        ("subject", "Subject"),
        ("keywords", "Keywords"),
    ):
        fields[key] = QLineEdit()
        form.addRow(label, fields[key])
    strip = QCheckBox("Strip all metadata instead (including XMP)")
    form.addRow("", strip)

    def load_meta() -> None:
        paths = shell.drop_zone.paths()
        if not paths or not Path(paths[0]).is_file():
            return
        try:
            meta = pdf_tools.metadata_get(paths[0])
        except Exception as exc:
            QMessageBox.warning(
                shell, shell.WINDOW_TITLE, f"Could not read metadata:\n{exc}"
            )
            return
        for key, edit in fields.items():
            edit.setText(str(meta.get(key) or ""))

    load_row = QHBoxLayout()
    load_btn = QPushButton("Load from file")
    load_btn.setObjectName("ToolbarSecondary")
    load_btn.clicked.connect(load_meta)
    load_row.addWidget(load_btn)
    load_row.addStretch(1)
    form.addRow(load_row)
    shell.set_options_widget(options)

    def on_files_changed() -> None:
        if shell.drop_zone.paths():
            load_meta()

    shell.drop_zone.files_changed.connect(on_files_changed)
    if shell.drop_zone.paths():
        load_meta()

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        output = _pick_save_pdf(
            shell, "Save metadata PDF", _default_out_path(source, "metadata")
        )
        if not output:
            return
        if strip.isChecked():
            run_tool_job(
                shell,
                job_type="metadata_strip",
                inputs=[source],
                output=output,
                progress_message="Stripping metadata…",
            )
            return
        updates = {key: edit.text() for key, edit in fields.items()}
        run_tool_job(
            shell,
            job_type="metadata_set",
            inputs=[source],
            output=output,
            options={"updates": updates},
            progress_message="Updating metadata…",
        )

    shell.set_run_handler(on_run)


def _configure_attachments(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    action = QComboBox()
    action.addItem("Add file", "add")
    action.addItem("Remove by name", "remove")
    action.addItem("Extract to folder", "extract")
    form.addRow("Action", action)
    name = QLineEdit()
    form.addRow("Attachment name", name)
    file_edit = QLineEdit()
    file_row = QHBoxLayout()
    file_row.addWidget(file_edit, stretch=1)
    browse = QPushButton("Browse…")
    browse.setObjectName("ToolbarSecondary")

    def pick_file() -> None:
        path, _ = QFileDialog.getOpenFileName(
            shell, "Choose file to attach", last_directory()
        )
        if path:
            remember_directory(path)
            file_edit.setText(path)
            if not name.text().strip():
                name.setText(Path(path).name)

    browse.clicked.connect(pick_file)
    file_row.addWidget(browse)
    form.addRow("File to add", file_row)
    replace = QCheckBox("Replace if name already exists")
    form.addRow("", replace)

    def sync_fields(_index: int = 0) -> None:
        current = action.currentData()
        extract = current == "extract"
        add = current == "add"
        name.setEnabled(not extract)
        file_edit.setEnabled(add)
        browse.setEnabled(add)
        replace.setEnabled(add)

    action.currentIndexChanged.connect(sync_fields)
    sync_fields()
    shell.set_options_widget(options)

    def on_run() -> None:
        source = _require_source(shell)
        if source is None:
            return
        current = action.currentData()
        att_name = name.text().strip()

        if current == "extract":
            try:
                creds = preflight_pdf_inputs(
                    [source],
                    prompt=lambda name, incorrect: prompt_pdf_password(
                        shell, name, incorrect=incorrect
                    ),
                )
            except JobCancelledError:
                return
            except Exception as exc:
                QMessageBox.warning(shell, shell.WINDOW_TITLE, str(exc))
                return
            try:
                attachments = pdf_tools.attachments_list(
                    source, password=creds.get(source)
                )
            except Exception as exc:
                QMessageBox.warning(shell, shell.WINDOW_TITLE, str(exc))
                return
            if not attachments:
                QMessageBox.warning(
                    shell, shell.WINDOW_TITLE, "This PDF has no attachments."
                )
                return
            folder = _pick_folder(shell, "Extract attachments to folder")
            if not folder:
                return
            out = Path(folder) / f"{Path(source).stem}_attachments.zip"
            if out.exists():
                stem, suffix = out.stem, out.suffix
                n = 1
                while True:
                    candidate = Path(folder) / f"{stem}_{n}{suffix}"
                    if not candidate.exists():
                        out = candidate
                        break
                    n += 1
            count = len(attachments)
            run_tool_job(
                shell,
                job_type="attachment_extract",
                inputs=[source],
                output=str(out),
                options={},
                progress_message="Extracting attachments…",
                success_toast=f"Extracted {count} attachments to {out.name}",
            )
            return

        if not att_name:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "Enter the attachment name.")
            return
        output = _pick_save_pdf(
            shell,
            "Save PDF with attachments",
            _default_out_path(source, "attachments"),
        )
        if not output:
            return
        if current == "add":
            file_path = file_edit.text().strip()
            if not file_path or not Path(file_path).is_file():
                QMessageBox.warning(
                    shell, shell.WINDOW_TITLE, "Choose a file to attach."
                )
                return
            run_tool_job(
                shell,
                job_type="attachment_add",
                inputs=[source],
                output=output,
                options={
                    "name": att_name,
                    "file_path": file_path,
                    "replace": replace.isChecked(),
                },
                progress_message="Adding attachment…",
            )
            return

        run_tool_job(
            shell,
            job_type="attachment_remove",
            inputs=[source],
            output=output,
            options={"name": att_name},
            progress_message="Removing attachment…",
        )

    shell.set_run_handler(on_run)


_CONFIGURERS: dict[str, object] = {
    "reverse": _configure_reverse,
    "split": _configure_split,
    "n_up": _configure_n_up,
    "booklet": _configure_booklet,
    "posterize": _configure_posterize,
    "divide": _configure_divide,
    "combine": _configure_combine,
    "normalize": _configure_normalize,
    "page_labels": _configure_page_labels,
    "alternate": _configure_alternate,
    "zip": _configure_zip,
    "metadata": _configure_metadata,
    "attachments": _configure_attachments,
}


def open_organize_shell(tools: ToolsWindow, tool_id: str) -> ToolShellWindow | None:
    """Lazy-create / raise a modeless shell for a migrated organize tool."""
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    entry = next((e for e in TOOL_CATALOGUE if e.id == tool_id), None)
    if entry is None or tool_id not in SHELL_ORGANIZE_IDS:
        return None

    store = tool_shell_store(tools)  # type: ignore[assignment]
    shell = store.get(tool_id)
    ctx = editor_pdf_context(tools.editor)
    if shell is None:
        multi = tool_id in _MULTI_DROP_IDS
        shell = ToolShellWindow(
            title=entry.title,
            description=entry.description,
            help_text=entry.help_text,
            editor=tools.editor,
            window_manager=getattr(tools, "_window_manager", None),
            multi=multi,
            browse_title=(
                "Choose PDFs" if multi else f"Choose PDF — {entry.title}"
            ),
        )
        configurer = _CONFIGURERS[tool_id]
        if tool_id == "split":
            configurer(shell, ctx)  # type: ignore[operator]
        else:
            configurer(shell)  # type: ignore[operator]
        store[tool_id] = shell
    else:
        shell.set_editor(tools.editor)
        if tool_id == "split" and ctx is not None and ctx.range_prefill:
            ranges_edit = getattr(shell, "_ranges_edit", None)
            if ranges_edit is not None:
                ranges_edit.setText(ctx.range_prefill)

    if ctx is not None and Path(ctx.path).is_file():
        if tool_id in _MULTI_DROP_IDS:
            # Prefill first slot only; user adds the rest.
            existing = shell.drop_zone.paths()
            if not existing:
                shell.drop_zone.set_paths([ctx.path])
        else:
            shell.drop_zone.set_paths([ctx.path])

    present_tool_page(tools.editor, shell, page_id=f"tool:{tool_id}")
    return shell
