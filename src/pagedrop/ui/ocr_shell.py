"""OCR & table extract — Phase 22b modeless shells (Phase 29 UI)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from pagedrop.core.capabilities import (
    OPENPYXL,
    TESSDATA,
    clear_cache,
    probe,
)
from pagedrop.core.pdf_service import page_count as pdf_page_count
from pagedrop.core.supported_formats import is_pdf_path
from pagedrop.ui.dialogs import prompt_missing_capability
from pagedrop.ui.organize_tools import editor_pdf_context
from pagedrop.ui.preferences_dialog import open_preferences
from pagedrop.ui.settings import (
    apply_tessdata_settings_to_capabilities,
    remember_directory,
)
from pagedrop.ui.tool_page import present_tool_page, tool_shell_store
from pagedrop.ui.tool_shell import ToolShellWindow, run_tool_job
from pagedrop.utils.page_jump import parse_page_ranges

if TYPE_CHECKING:
    from pagedrop.ui.tools_window import ToolsWindow

SHELL_OCR_IDS: frozenset[str] = frozenset(
    {"ocr_pdf", "extract_tables", "pdf_to_csv", "pdf_to_excel"}
)

_PDF_FILTER = "PDF files (*.pdf);;All files (*)"

_TABLE_FORMATS: tuple[tuple[str, str, str], ...] = (
    ("CSV", "csv", ".csv"),
    ("JSON", "tables_json", ".json"),
    ("Excel (XLSX)", "xlsx", ".xlsx"),
)

_INITIAL_TABLE_FORMAT: dict[str, str] = {
    "pdf_to_csv": "csv",
    "pdf_to_excel": "xlsx",
}


def _pick_save_path(
    parent: QWidget,
    title: str,
    suggested: str,
    file_filter: str,
) -> str | None:
    path, _ = QFileDialog.getSaveFileName(parent, title, suggested, file_filter)
    if not path:
        return None
    remember_directory(path)
    return path


def _page_indices_from_text(text: str, page_count: int) -> list[int] | None:
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


def _tessdata_status_line() -> str:
    status = probe(TESSDATA)
    if status.available:
        langs = status.extras.get("languages") or []
        path = status.extras.get("path") or ""
        lang_s = ", ".join(langs[:8])
        if len(langs) > 8:
            lang_s = f"{lang_s}, …"
        return f"tessdata ready — {lang_s}\n{path}"
    return status.detail or "No tessdata languages found"


def _configure_ocr(shell: ToolShellWindow, *, range_prefill: str = "") -> None:
    apply_tessdata_settings_to_capabilities()

    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)

    hint = QLabel(
        "Creates a new searchable PDF (pages are rasterized with an OCR text "
        "layer). Source file is never overwritten. Requires tessdata language "
        "files — not a separate Tesseract install."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)

    status = QLabel()
    status.setObjectName("ToolsHint")
    status.setWordWrap(True)
    status.setAccessibleName("OCR tessdata status")
    form.addRow(status)

    btn_row = QHBoxLayout()
    configure_btn = QPushButton("Configure…")
    configure_btn.setObjectName("ToolbarSecondary")
    configure_btn.setToolTip("Tessdata path, download eng, and recheck")
    recheck_btn = QPushButton("Recheck")
    recheck_btn.setObjectName("ToolbarSecondary")
    btn_row.addWidget(configure_btn)
    btn_row.addWidget(recheck_btn)
    btn_row.addStretch(1)
    form.addRow(btn_row)

    lang = QComboBox()
    lang.setAccessibleName("OCR language")
    form.addRow("Language", lang)

    ranges = QLineEdit(range_prefill)
    ranges.setPlaceholderText("All pages")
    ranges.setClearButtonEnabled(True)
    form.addRow("Page range", ranges)
    range_hint = QLabel("Leave blank for all pages, or use 1-3,5 (selection prefills).")
    range_hint.setObjectName("ToolsHint")
    range_hint.setWordWrap(True)
    form.addRow(range_hint)

    dpi = QDoubleSpinBox()
    dpi.setRange(72, 600)
    dpi.setDecimals(0)
    dpi.setValue(300)
    dpi.setSuffix(" dpi")
    form.addRow("OCR resolution", dpi)

    shell.set_options_widget(options)
    shell._ocr_lang = lang  # type: ignore[attr-defined]
    shell._ocr_ranges = ranges  # type: ignore[attr-defined]
    shell._ocr_status = status  # type: ignore[attr-defined]

    def refresh_languages() -> None:
        apply_tessdata_settings_to_capabilities()
        status.setText(_tessdata_status_line())
        cap = probe(TESSDATA)
        current = lang.currentData()
        lang.blockSignals(True)
        lang.clear()
        if cap.available:
            for code in cap.extras.get("languages") or ["eng"]:
                lang.addItem(code, code)
            idx = lang.findData(current) if current else lang.findData("eng")
            lang.setCurrentIndex(max(0, idx))
        else:
            lang.addItem("eng (unavailable)", "eng")
        lang.blockSignals(False)
        shell._update_run_enabled()
        if cap.available:
            shell.statusBar().showMessage("Ready")
        else:
            shell.statusBar().showMessage("tessdata missing — Configure or Recheck")

    def on_configure() -> None:
        open_preferences(shell)
        refresh_languages()

    def on_recheck() -> None:
        clear_cache()
        apply_tessdata_settings_to_capabilities()
        cap = probe(TESSDATA, refresh=True)
        refresh_languages()
        if not cap.available:
            result = prompt_missing_capability(
                shell, cap, tool_title=shell.WINDOW_TITLE
            )
            if result == "configure":
                open_preferences(shell)
            refresh_languages()

    configure_btn.clicked.connect(on_configure)
    recheck_btn.clicked.connect(on_recheck)
    shell.set_run_enabled_check(lambda: probe(TESSDATA).available)
    refresh_languages()

    def on_run() -> None:
        apply_tessdata_settings_to_capabilities()
        cap = probe(TESSDATA)
        if not cap.available:
            result = prompt_missing_capability(
                shell, cap, tool_title=shell.WINDOW_TITLE
            )
            refresh_languages()
            if result == "configure":
                open_preferences(shell)
                refresh_languages()
            return

        paths = [p for p in shell.drop_zone.paths() if Path(p).is_file()]
        if not paths:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "Choose a valid PDF.")
            return
        source = paths[0]
        if not is_pdf_path(source):
            QMessageBox.warning(
                shell, shell.WINDOW_TITLE, f"Unsupported format:\n{Path(source).name}"
            )
            return

        try:
            page_count = pdf_page_count(source)
        except Exception as exc:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, f"Could not open PDF:\n{exc}")
            return

        page_indices = _page_indices_from_text(ranges.text(), page_count)
        if page_indices is not None and len(page_indices) == 0:
            QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                "Enter page ranges like 1-3,5,7-9, or leave blank for all pages.",
            )
            return

        suggested = str(Path(source).with_name(f"{Path(source).stem}_ocr.pdf"))
        output = _pick_save_path(
            shell, "Save searchable PDF", suggested, _PDF_FILTER
        )
        if not output:
            return
        if not output.lower().endswith(".pdf"):
            output = f"{output}.pdf"

        language = str(lang.currentData() or "eng")
        run_tool_job(
            shell,
            job_type="ocr_pdf",
            inputs=[source],
            output=output,
            options={
                "language": language,
                "pages": page_indices,
                "dpi": int(dpi.value()),
                "tessdata": cap.extras.get("path"),
            },
            progress_message="Running OCR…",
            success_toast="Searchable PDF ready",
        )

    shell.set_run_handler(on_run)


def _configure_extract_tables(
    shell: ToolShellWindow,
    *,
    range_prefill: str = "",
    initial_format_id: str | None = None,
) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)

    hint = QLabel(
        "Uses PyMuPDF table detection (find_tables). Writes a new CSV, JSON, "
        "or Excel file — source PDF unchanged. XLSX needs openpyxl."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)

    fmt = QComboBox()
    selected_index = 0
    for index, (label, format_id, _suffix) in enumerate(_TABLE_FORMATS):
        if format_id == "xlsx" and not probe(OPENPYXL).available:
            fmt.addItem(f"{label} (openpyxl missing)", format_id)
        else:
            fmt.addItem(label, format_id)
        if initial_format_id and format_id == initial_format_id:
            selected_index = index
    fmt.setCurrentIndex(selected_index)
    form.addRow("Format", fmt)
    shell._table_format_combo = fmt  # type: ignore[attr-defined]

    ranges = QLineEdit(range_prefill)
    ranges.setPlaceholderText("All pages")
    ranges.setClearButtonEnabled(True)
    form.addRow("Page range", ranges)
    range_hint = QLabel("Leave blank for all pages, or use 1-3,5 (selection prefills).")
    range_hint.setObjectName("ToolsHint")
    range_hint.setWordWrap(True)
    form.addRow(range_hint)

    shell.set_options_widget(options)

    def on_run() -> None:
        paths = [p for p in shell.drop_zone.paths() if Path(p).is_file()]
        if not paths:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "Choose a valid PDF.")
            return
        source = paths[0]
        format_id = str(fmt.currentData())
        if format_id == "xlsx" and not probe(OPENPYXL).available:
            result = prompt_missing_capability(
                shell, probe(OPENPYXL), tool_title=shell.WINDOW_TITLE
            )
            if result != "recheck" or not probe(OPENPYXL).available:
                return

        try:
            page_count = pdf_page_count(source)
        except Exception as exc:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, f"Could not open PDF:\n{exc}")
            return

        page_indices = _page_indices_from_text(ranges.text(), page_count)
        if page_indices is not None and len(page_indices) == 0:
            QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                "Enter page ranges like 1-3,5,7-9, or leave blank for all pages.",
            )
            return

        suffix = next(s for _l, fid, s in _TABLE_FORMATS if fid == format_id)
        filters = {
            "csv": "CSV (*.csv);;All files (*)",
            "tables_json": "JSON (*.json);;All files (*)",
            "xlsx": "Excel (*.xlsx);;All files (*)",
        }
        suggested = str(Path(source).with_name(f"{Path(source).stem}_tables{suffix}"))
        output = _pick_save_path(
            shell, "Save tables", suggested, filters[format_id]
        )
        if not output:
            return
        if not output.lower().endswith(suffix):
            output = f"{output}{suffix}"

        run_tool_job(
            shell,
            job_type="extract_tables",
            inputs=[source],
            output=output,
            options={"format_id": format_id, "pages": page_indices},
            progress_message="Extracting tables…",
            success_toast="Tables exported",
        )

    shell.set_run_handler(on_run)


_CONFIGURERS = {
    "ocr_pdf": _configure_ocr,
    "extract_tables": _configure_extract_tables,
    "pdf_to_csv": _configure_extract_tables,
    "pdf_to_excel": _configure_extract_tables,
}


def open_ocr_shell(tools: ToolsWindow, tool_id: str) -> ToolShellWindow | None:
    """Lazy-create / raise a Phase 29 OCR or extract-tables shell."""
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    if tool_id not in SHELL_OCR_IDS:
        return None
    entry = next((e for e in TOOL_CATALOGUE if e.id == tool_id), None)
    if entry is None:
        return None

    store = tool_shell_store(tools)  # type: ignore[assignment]
    shell = store.get(tool_id)
    ctx = editor_pdf_context(tools.editor)
    range_prefill = ctx.range_prefill if ctx is not None else ""
    initial_format = _INITIAL_TABLE_FORMAT.get(tool_id)

    if shell is None:
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
        if tool_id == "ocr_pdf":
            _CONFIGURERS[tool_id](shell, range_prefill=range_prefill)
        else:
            _CONFIGURERS[tool_id](
                shell,
                range_prefill=range_prefill,
                initial_format_id=initial_format,
            )
        store[tool_id] = shell
    else:
        shell.set_editor(tools.editor)
        ranges = getattr(shell, "_ocr_ranges", None)
        if ranges is not None and range_prefill and not ranges.text().strip():
            ranges.setText(range_prefill)
        combo = getattr(shell, "_table_format_combo", None)
        if combo is not None and initial_format:
            for i in range(combo.count()):
                if combo.itemData(i) == initial_format:
                    combo.setCurrentIndex(i)
                    break

    if ctx is not None and Path(ctx.path).is_file():
        shell.drop_zone.set_paths([ctx.path])

    present_tool_page(tools.editor, shell, page_id=f"tool:{tool_id}")
    return shell
