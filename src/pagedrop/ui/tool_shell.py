"""Shared modeless tool window — drop zone → options → Run → results (Phase 22b)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core import pdf_tools
from pagedrop.core.jobs import (
    JobCancelledError,
    JobError,
    JobSpec,
    OutputExistsError,
    SerializedJobRunner,
    SourceOverwriteError,
    preflight_pdf_inputs,
)
from pagedrop.core.supported_formats import is_pdf_path, local_paths_from_mime
from pagedrop.ui.busy_overlay import BusyOverlay, ToastOverlay
from pagedrop.ui.dialogs import (
    confirm_overwrite,
    prompt_cancel_running_job,
    prompt_pdf_password,
)
from pagedrop.ui.result_actions import (
    ResultActionsBar,
    open_in_editor,
    preview_pdf,
    show_in_folder,
)
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.utils.page_jump import parse_page_ranges
from pagedrop.utils.temp_manager import TempManager

if TYPE_CHECKING:
    from pagedrop.ui.organize_tools import EditorPdfContext
    from pagedrop.ui.tools_window import ToolsWindow
    from pagedrop.ui.window_manager import WindowManager

_PRIVACY_LINE = "Files stay on this computer — nothing is uploaded."
_PDF_FILTER = "PDF files (*.pdf);;All files (*)"

# Organize tools migrated onto this shell in Phase 22b (remaining finish in Phase 24).
SHELL_ORGANIZE_IDS: frozenset[str] = frozenset({"split", "reverse"})


class FileDropZone(QFrame):
    """Click opens a file picker; OS DnD accepts ``file://`` URLs filtered by *accept*."""

    files_changed = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        accept: Callable[[str], bool] | None = None,
        dialog_filter: str = _PDF_FILTER,
        multi: bool = False,
        browse_title: str = "Choose files",
        empty_prompt: str = "Drop PDF here, or click to browse",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ToolShellDropZone")
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("File drop zone")
        self.setAccessibleDescription(empty_prompt)

        self._accept = accept or is_pdf_path
        self._dialog_filter = dialog_filter
        self._multi = multi
        self._browse_title = browse_title
        self._empty_prompt = empty_prompt
        self._paths: list[str] = []
        self._press_pos: QPoint | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._prompt = QLabel(empty_prompt)
        self._prompt.setObjectName("ToolShellDropPrompt")
        self._prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prompt.setWordWrap(True)
        layout.addWidget(self._prompt)

        self._files_label = QLabel()
        self._files_label.setObjectName("ToolShellDropFiles")
        self._files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._files_label.setWordWrap(True)
        self._files_label.hide()
        layout.addWidget(self._files_label)

        self._privacy = QLabel(_PRIVACY_LINE)
        self._privacy.setObjectName("ToolShellDropPrivacy")
        self._privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._privacy.setWordWrap(True)
        layout.addWidget(self._privacy)

        clear_row = QHBoxLayout()
        clear_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setObjectName("ToolbarSecondary")
        self._clear_btn.setVisible(False)
        self._clear_btn.clicked.connect(self.clear)
        clear_row.addWidget(self._clear_btn)
        layout.addLayout(clear_row)

        self.setMinimumHeight(120)

    def paths(self) -> list[str]:
        return list(self._paths)

    def set_paths(self, paths: Sequence[str]) -> None:
        accepted = [str(p) for p in paths if self._accept(str(p))]
        if not self._multi:
            accepted = accepted[:1]
        self._paths = accepted
        self._refresh()
        self.files_changed.emit()

    def clear(self) -> None:
        if not self._paths:
            return
        self._paths = []
        self._refresh()
        self.files_changed.emit()

    def open_picker(self) -> None:
        start = last_directory()
        if self._paths:
            start = str(Path(self._paths[0]).parent)
        if self._multi:
            paths, _ = QFileDialog.getOpenFileNames(
                self, self._browse_title, start, self._dialog_filter
            )
            if paths:
                remember_directory(paths[0])
                self.set_paths(paths)
            return
        path, _ = QFileDialog.getOpenFileName(
            self, self._browse_title, start, self._dialog_filter
        )
        if path:
            remember_directory(path)
            self.set_paths([path])

    def _refresh(self) -> None:
        if not self._paths:
            self._prompt.setText(self._empty_prompt)
            self._files_label.hide()
            self._clear_btn.setVisible(False)
            return
        names = ", ".join(Path(p).name for p in self._paths)
        self._prompt.setText("Click to replace, or drop another file")
        self._files_label.setText(names)
        self._files_label.show()
        self._clear_btn.setVisible(True)

    def _paths_from_mime(self, mime) -> list[str]:
        return local_paths_from_mime(mime, accept=self._accept)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            self.setProperty("dropActive", True)
            self.style().unpolish(self)
            self.style().polish(self)
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("dropActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.setProperty("dropActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        paths = self._paths_from_mime(event.mimeData())
        if not paths:
            event.ignore()
            return
        if self._multi:
            merged = list(dict.fromkeys([*self._paths, *paths]))
            self.set_paths(merged)
        else:
            self.set_paths(paths[:1])
        event.acceptProposedAction()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            delta = (event.position().toPoint() - self._press_pos).manhattanLength()
            self._press_pos = None
            if delta < QApplication.startDragDistance():
                self.open_picker()
                event.accept()
                return
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.open_picker()
            event.accept()
            return
        super().keyPressEvent(event)


def run_tool_job(
    host: QWidget,
    *,
    job_type: str,
    inputs: list[str],
    output: str,
    options: dict | None = None,
    existing_paths: list[Path] | None = None,
    progress_message: str = "Working…",
    success_toast: str | None = None,
) -> None:
    """Password preflight → overwrite confirm → job runner (shared with Tools hub).

    *host* must provide ``begin_job``, ``end_job``, ``job_runner``, ``set_job_progress``,
    and ``WINDOW_TITLE`` (same shape as ``ToolsWindow`` / ``ToolShellWindow``).
    """
    begin = host.begin_job
    end = host.end_job
    runner: SerializedJobRunner = host.job_runner()
    set_progress = host.set_job_progress
    title = getattr(host, "WINDOW_TITLE", "Tools")

    out = Path(output)
    existing = existing_paths if existing_paths is not None else (
        [out] if out.exists() else []
    )

    token = begin(progress_message)
    try:
        credentials = preflight_pdf_inputs(
            inputs,
            prompt=lambda name, incorrect: prompt_pdf_password(
                host, name, incorrect=incorrect
            ),
            cancel=token,
        )
        if existing and not confirm_overwrite(host, existing, window_title=title):
            end(status="Cancelled", toast="Cancelled", toast_kind="info")
            return
        result = runner.run(
            JobSpec.create(
                job_type,
                inputs=inputs,
                output=output,
                options=options or {},
                overwrite=True,
            ),
            credentials=credentials,
            progress=set_progress,
            cancel=token,
        )
    except JobCancelledError:
        end(status="Cancelled", toast="Job cancelled", toast_kind="info")
        return
    except SourceOverwriteError as exc:
        end(
            error=f"Output must not overwrite a source file:\n{exc}",
            toast="Cannot overwrite source",
            toast_kind="error",
        )
        return
    except OutputExistsError as exc:
        end(
            error=f"Output already exists:\n{exc}",
            toast="Output exists",
            toast_kind="error",
        )
        return
    except (JobError, OSError, ValueError, FileNotFoundError, FileExistsError) as exc:
        end(error=str(exc), toast="Job failed", toast_kind="error")
        return
    except Exception as exc:
        end(
            error=f"Unexpected error:\n{exc}",
            toast="Job failed",
            toast_kind="error",
        )
        return

    name = Path(result).name
    end(
        status=f"Saved {name}",
        toast=success_toast or f"Saved {name}",
        toast_kind="success",
        result_path=str(result),
    )


class ToolShellWindow(QMainWindow):
    """Reusable modeless tool chrome: title → drop → options → Run → results."""

    def __init__(
        self,
        *,
        title: str,
        description: str,
        editor: QWidget | None = None,
        window_manager: WindowManager | None = None,
        multi: bool = False,
        browse_title: str = "Choose PDF",
        empty_prompt: str = "Drop PDF here, or click to browse",
        accept: Callable[[str], bool] | None = None,
        dialog_filter: str = _PDF_FILTER,
    ) -> None:
        super().__init__(None)
        self.WINDOW_TITLE = title
        self._editor = editor
        self._window_manager = window_manager
        self._job_running = False
        self._cancel_token = None
        self._job_runner: SerializedJobRunner | None = None
        self._run_handler: Callable[[], None] | None = None

        self.setWindowTitle(title)
        self.setObjectName("ToolShellWindow")
        self.setMinimumSize(480, 420)
        self.resize(560, 520)

        central = QWidget()
        central.setObjectName("ToolShellCentral")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 8)
        root.setSpacing(12)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("ToolShellTitle")
        root.addWidget(self._title_label)

        self._desc_label = QLabel(description)
        self._desc_label.setObjectName("ToolShellDescription")
        self._desc_label.setWordWrap(True)
        root.addWidget(self._desc_label)

        self._drop_zone = FileDropZone(
            self,
            accept=accept,
            dialog_filter=dialog_filter,
            multi=multi,
            browse_title=browse_title,
            empty_prompt=empty_prompt,
        )
        self._drop_zone.files_changed.connect(self._update_run_enabled)
        root.addWidget(self._drop_zone)

        self._options_host = QWidget()
        self._options_host.setObjectName("ToolShellOptions")
        self._options_layout = QVBoxLayout(self._options_host)
        self._options_layout.setContentsMargins(0, 0, 0, 0)
        self._options_layout.setSpacing(8)
        root.addWidget(self._options_host)

        run_row = QHBoxLayout()
        run_row.addStretch(1)
        self._run_btn = QPushButton("Run")
        self._run_btn.setObjectName("ToolbarPrimary")
        self._run_btn.setDefault(True)
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)
        run_row.addWidget(self._run_btn)
        root.addLayout(run_row)

        root.addStretch(1)

        self._result_bar = ResultActionsBar()
        self._result_bar.preview_requested.connect(self._on_preview_result)
        self._result_bar.open_in_editor_requested.connect(self._on_open_result)
        self._result_bar.show_in_folder_requested.connect(self._on_show_folder)
        root.addWidget(self._result_bar)

        self._busy_overlay = BusyOverlay(central)
        self._busy_overlay.set_cancellable(True)
        self._busy_overlay.cancelled.connect(self.cancel_active_job)
        self._toast = ToastOverlay(central)
        self.statusBar().showMessage("Add a file to begin")

    def set_editor(self, editor: QWidget | None) -> None:
        self._editor = editor

    @property
    def editor(self) -> QWidget | None:
        return self._editor

    @property
    def drop_zone(self) -> FileDropZone:
        return self._drop_zone

    def set_options_widget(self, widget: QWidget) -> None:
        while self._options_layout.count():
            item = self._options_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.deleteLater()
        self._options_layout.addWidget(widget)

    def set_run_handler(self, handler: Callable[[], None]) -> None:
        self._run_handler = handler

    def job_runner(self) -> SerializedJobRunner:
        if self._job_runner is None:
            from pagedrop.ui.organize_tools import ensure_organize_runner

            self._job_runner = ensure_organize_runner(TempManager())
        return self._job_runner

    def is_job_running(self) -> bool:
        return self._job_running

    def begin_job(self, message: str = "Working…"):
        from pagedrop.core.jobs import CancelToken

        if not message.endswith("…"):
            message = f"{message.rstrip('.')}…"
        self._job_running = True
        self._cancel_token = CancelToken()
        self._result_bar.clear()
        self._busy_overlay.show_message(message)
        self.statusBar().showMessage(message)
        self._run_btn.setEnabled(False)
        self._drop_zone.setEnabled(False)
        return self._cancel_token

    def set_job_progress(self, _fraction: float, message: str) -> None:
        if not self._job_running:
            return
        if message and not message.endswith("…") and message != "Done":
            message = f"{message.rstrip('.')}…"
        if message == "Done":
            return
        self._busy_overlay.show_message(message or "Working…")
        self.statusBar().showMessage(message or "Working…")

    def end_job(
        self,
        *,
        status: str | None = None,
        toast: str | None = None,
        toast_kind: str = "info",
        result_path: str | None = None,
        error: str | None = None,
    ) -> None:
        self._job_running = False
        self._cancel_token = None
        self._result_bar.clear()
        self._busy_overlay.hide_overlay()
        self._drop_zone.setEnabled(True)
        self._update_run_enabled()
        if error:
            self.statusBar().showMessage("Job failed")
            self._toast.show_toast(toast or "Job failed", kind="error")
            QMessageBox.critical(self, self.WINDOW_TITLE, error)
            return
        if status:
            self.statusBar().showMessage(status)
        if toast:
            self._toast.show_toast(toast, kind=toast_kind)
        if result_path:
            self._result_bar.show_for(result_path)

    def cancel_active_job(self) -> None:
        if self._cancel_token is not None:
            self._cancel_token.cancel()

    def show_toast(self, message: str, *, kind: str = "info") -> None:
        self._toast.show_toast(message, kind=kind)

    def _update_run_enabled(self) -> None:
        self._run_btn.setEnabled(bool(self._drop_zone.paths()) and not self._job_running)

    def _on_run(self) -> None:
        if self._job_running:
            return
        if self._run_handler is None:
            return
        self._run_handler()

    def _on_preview_result(self, path: str) -> None:
        preview_pdf(path, parent=self)

    def _on_open_result(self, path: str) -> None:
        editor = self._editor
        if editor is None:
            self._toast.show_toast("No editor window available", kind="error")
            return
        try:
            open_in_editor(path, editor)
        except Exception as exc:
            QMessageBox.critical(
                self,
                self.WINDOW_TITLE,
                f"Could not open in editor:\n{exc}",
            )
            return
        self._toast.show_toast(f"Opened {Path(path).name}", kind="success")

    def _on_show_folder(self, path: str) -> None:
        if not show_in_folder(path):
            QMessageBox.warning(
                self,
                self.WINDOW_TITLE,
                "Could not open the folder for this file.",
            )
            return
        self._toast.show_toast("Opened folder", kind="info")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        parent = self._busy_overlay.parentWidget()
        if parent is not None:
            self._busy_overlay.setGeometry(parent.rect())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._job_running:
            if not prompt_cancel_running_job(self, window_title=self.WINDOW_TITLE):
                event.ignore()
                return
            self.cancel_active_job()
            self.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
        super().closeEvent(event)
        if event.isAccepted() and self._window_manager is not None:
            self._window_manager.notify_utility_closed(self)


def _pick_save_pdf(parent: QWidget, title: str, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(
        parent, title, suggested, _PDF_FILTER
    )
    if not path:
        return None
    if not path.lower().endswith(".pdf"):
        path = f"{path}.pdf"
    remember_directory(path)
    return path


def _default_out_path(source: str, suffix: str) -> str:
    src = Path(source)
    return str(src.with_name(f"{src.stem}_{suffix}.pdf"))


def _build_reverse_options() -> tuple[QWidget, QCheckBox]:
    host = QWidget()
    form = QFormLayout(host)
    form.setContentsMargins(0, 0, 0, 0)
    blank = QCheckBox("Add blank page at end")
    form.addRow("", blank)
    return host, blank


def _build_split_options() -> tuple[QWidget, QLineEdit, QLineEdit]:
    host = QWidget()
    form = QFormLayout(host)
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
            host, "Choose output folder", last_directory()
        )
        if chosen:
            remember_directory(chosen)
            folder.setText(chosen)

    browse.clicked.connect(pick)
    folder_row.addWidget(browse)
    form.addRow("Output folder", folder_row)
    return host, ranges, folder


def _configure_reverse(shell: ToolShellWindow) -> None:
    options, blank = _build_reverse_options()
    shell.set_options_widget(options)
    shell._blank_cb = blank  # type: ignore[attr-defined]

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths or not Path(paths[0]).is_file():
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "Choose a valid source PDF.")
            return
        source = paths[0]
        suggested = _default_out_path(source, "reversed")
        output = _pick_save_pdf(shell, "Save reversed PDF", suggested)
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
    options, ranges, folder = _build_split_options()
    shell.set_options_widget(options)
    shell._ranges_edit = ranges  # type: ignore[attr-defined]
    shell._folder_edit = folder  # type: ignore[attr-defined]
    if ctx is not None and ctx.range_prefill:
        ranges.setText(ctx.range_prefill)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths or not Path(paths[0]).is_file():
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "Choose a valid source PDF.")
            return
        source = paths[0]
        out_folder = folder.text().strip()
        ranges_text = ranges.text().strip()
        if not out_folder:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "Choose an output folder.")
            return
        try:
            from pagedrop.core.pdf_loader import PdfLoader

            loader = PdfLoader(source)
            try:
                page_count = loader.page_count
            finally:
                loader.close()
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
            success_toast=f"Wrote {len(predicted)} file(s)",
        )

    shell.set_run_handler(on_run)


def open_organize_shell(tools: ToolsWindow, tool_id: str) -> ToolShellWindow | None:
    """Lazy-create / raise a modeless shell for a migrated organize tool."""
    from pagedrop.ui.organize_tools import editor_pdf_context
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    entry = next((e for e in TOOL_CATALOGUE if e.id == tool_id), None)
    if entry is None or tool_id not in SHELL_ORGANIZE_IDS:
        return None

    store: dict[str, ToolShellWindow] = getattr(tools, "_tool_shells", None) or {}
    tools._tool_shells = store  # type: ignore[attr-defined]

    shell = store.get(tool_id)
    ctx = editor_pdf_context(tools.editor)
    if shell is None:
        shell = ToolShellWindow(
            title=entry.title,
            description=entry.description,
            editor=tools.editor,
            window_manager=getattr(tools, "_window_manager", None),
            browse_title=f"Choose PDF — {entry.title}",
        )
        if tool_id == "reverse":
            _configure_reverse(shell)
        elif tool_id == "split":
            _configure_split(shell, ctx)
        store[tool_id] = shell
    else:
        shell.set_editor(tools.editor)
        if tool_id == "split" and ctx is not None and ctx.range_prefill:
            ranges_edit = getattr(shell, "_ranges_edit", None)
            if ranges_edit is not None:
                ranges_edit.setText(ctx.range_prefill)

    if ctx is not None and Path(ctx.path).is_file():
        shell.drop_zone.set_paths([ctx.path])

    shell.show()
    shell.raise_()
    shell.activateWindow()
    return shell
