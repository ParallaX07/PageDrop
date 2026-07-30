"""Shared modeless tool window — drop zone → options → Run → results (Phase 22b)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

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
from pagedrop.ui.dialogs import (
    confirm_overwrite,
    prompt_pdf_password,
)
from pagedrop.ui.job_chrome import JobChromeMixin
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.tool_page import StatusFooter

_PRIVACY_LINE = "Files stay on this computer — nothing is uploaded."
_PDF_FILTER = "PDF files (*.pdf);;All files (*)"

# Canonical drop-zone prompts (O5). Prefer these over one-off wording.
EMPTY_PROMPT_PDF = "Drop PDF here, or click to browse"
EMPTY_PROMPT_PDFS = "Drop PDFs here, or click to browse"
EMPTY_PROMPT_DOCUMENTS = "Drop documents here, or click to browse"
EMPTY_PROMPT_OFFICE = "Drop Office document here, or click to browse"

# Dedicated pool (not thumbnail/render pools). Fitz jobs take FITZ_LOCK;
# Office / LibreOffice handlers register holds_fitz=False.
_TOOL_JOB_POOL: QThreadPool | None = None
# Keep Signals alive until queued finished slots run (autoDelete QRunnable).
_TOOL_JOB_SIGNAL_REFS: list[QObject] = []


def _tool_job_pool() -> QThreadPool:
    global _TOOL_JOB_POOL
    if _TOOL_JOB_POOL is None:
        _TOOL_JOB_POOL = QThreadPool()
        _TOOL_JOB_POOL.setMaxThreadCount(1)
        _TOOL_JOB_POOL.setObjectName("PageDropToolJobPool")
    return _TOOL_JOB_POOL


class _ToolJobWorker(QRunnable):
    """Run ``SerializedJobRunner.run`` off the UI thread (LibreOffice / long jobs)."""

    class Signals(QObject):
        progress = pyqtSignal(float, str)
        succeeded = pyqtSignal(str)
        cancelled = pyqtSignal()
        failed = pyqtSignal(str, str)  # error dialog text, toast

    def __init__(
        self,
        runner: SerializedJobRunner,
        spec: JobSpec,
        *,
        credentials: object,
        cancel: object,
        secrets: dict[str, str] | None,
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._runner = runner
        self._spec = spec
        self._credentials = credentials
        self._cancel = cancel
        self._secrets = secrets
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._runner.run(
                self._spec,
                credentials=self._credentials,  # type: ignore[arg-type]
                progress=lambda f, m: self.signals.progress.emit(f, m),
                cancel=self._cancel,  # type: ignore[arg-type]
                secrets=self._secrets,
            )
        except JobCancelledError:
            self.signals.cancelled.emit()
        except SourceOverwriteError as exc:
            self.signals.failed.emit(
                f"Output must not overwrite a source file:\n{exc}",
                "Cannot overwrite source",
            )
        except OutputExistsError as exc:
            self.signals.failed.emit(
                f"Output already exists:\n{exc}",
                "Output exists",
            )
        except (JobError, OSError, ValueError, FileNotFoundError, FileExistsError) as exc:
            self.signals.failed.emit(str(exc), "Job failed")
        except Exception as exc:
            self.signals.failed.emit(f"Unexpected error:\n{exc}", "Job failed")
        else:
            self.signals.succeeded.emit(str(result))


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
        empty_prompt: str | None = None,
    ) -> None:
        super().__init__(parent)
        if empty_prompt is None:
            empty_prompt = EMPTY_PROMPT_PDFS if multi else EMPTY_PROMPT_PDF
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
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        # Do not setAlignment(AlignCenter) on the layout — that shrinks Preferred
        # children to sizeHint width, wraps the prompt, then clips it.

        # Expanding so wrap width follows the zone; height synced in resizeEvent
        # (QLabel sizeHint is often one line until width is known).
        label_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self._prompt = QLabel(empty_prompt)
        self._prompt.setObjectName("ToolShellDropPrompt")
        self._prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prompt.setWordWrap(True)
        self._prompt.setSizePolicy(label_policy)
        layout.addWidget(self._prompt)

        self._files_label = QLabel()
        self._files_label.setObjectName("ToolShellDropFiles")
        self._files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._files_label.setWordWrap(True)
        self._files_label.setSizePolicy(label_policy)
        self._files_label.hide()
        layout.addWidget(self._files_label)

        self._privacy = QLabel(_PRIVACY_LINE)
        self._privacy.setObjectName("ToolShellDropPrivacy")
        self._privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._privacy.setWordWrap(True)
        self._privacy.setSizePolicy(label_policy)
        layout.addWidget(self._privacy)

        clear_row = QHBoxLayout()
        clear_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setObjectName("ToolbarSecondary")
        self._clear_btn.setVisible(False)
        self._clear_btn.clicked.connect(self.clear)
        clear_row.addWidget(self._clear_btn)
        layout.addLayout(clear_row)

        # Grow with wrapped copy — Fixed+maxHeight(160) clipped two-line prompts.
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

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
        else:
            names = ", ".join(Path(p).name for p in self._paths)
            self._prompt.setText("Click to replace, or drop another file")
            self._files_label.setText(names)
            self._files_label.show()
            self._clear_btn.setVisible(True)
        self._fit_wrapped_labels()

    def _fit_wrapped_labels(self) -> None:
        """Allocate height for word-wrapped labels once the zone width is known."""
        margins = self.layout().contentsMargins() if self.layout() else None
        side = (margins.left() + margins.right()) if margins else 32
        inner = max(1, self.width() - side)
        for label in (self._prompt, self._files_label, self._privacy):
            if label.isHidden():
                label.setMinimumHeight(0)
                continue
            label.setMinimumHeight(0)
            h = label.heightForWidth(inner)
            if h > 0:
                label.setMinimumHeight(h)
        # Parent layouts honor Minimum; keep the floor at the empty-state default.
        hint = self.layout().sizeHint().height() if self.layout() else 96
        self.setMinimumHeight(max(96, hint))
        self.updateGeometry()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_wrapped_labels()

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
    secrets: dict[str, str] | None = None,
) -> None:
    """Password preflight → overwrite confirm → job runner (shared with Tools hub).

    Dialogs run on the UI thread; ``runner.run`` runs on a dedicated pool so
    LibreOffice / long handlers do not freeze the event loop.

    *host* must provide ``begin_job``, ``end_job``, ``job_runner``, ``set_job_progress``,
    and ``WINDOW_TITLE`` (same shape as ``ToolsWindow`` / ``ToolShellWindow``).

    *secrets* are runtime-only (e.g. encrypt passwords) — never written to
    ``JobSpec``, settings, or logs.
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

    spec = JobSpec.create(
        job_type,
        inputs=inputs,
        output=output,
        options=options or {},
        overwrite=True,
    )
    worker = _ToolJobWorker(
        runner,
        spec,
        credentials=credentials,
        cancel=token,
        secrets=secrets,
    )
    signals = worker.signals
    _TOOL_JOB_SIGNAL_REFS.append(signals)

    def _still_running() -> bool:
        check = getattr(host, "is_job_running", None)
        return True if not callable(check) else bool(check())

    def _release_signals() -> None:
        try:
            _TOOL_JOB_SIGNAL_REFS.remove(signals)
        except ValueError:
            pass

    def on_progress(fraction: float, message: str) -> None:
        if _still_running():
            set_progress(fraction, message)

    def on_succeeded(result_path: str) -> None:
        _release_signals()
        if not _still_running():
            return
        name = Path(result_path).name
        message = success_toast or f"Saved {name}"
        end(
            status=message,
            toast=message,
            toast_kind="success",
            result_path=result_path,
        )

    def on_cancelled() -> None:
        _release_signals()
        if not _still_running():
            return
        end(status="Cancelled", toast="Job cancelled", toast_kind="info")

    def on_failed(error: str, toast: str) -> None:
        _release_signals()
        if not _still_running():
            return
        end(error=error, toast=toast, toast_kind="error")

    signals.progress.connect(on_progress)
    signals.succeeded.connect(on_succeeded)
    signals.cancelled.connect(on_cancelled)
    signals.failed.connect(on_failed)
    _tool_job_pool().start(worker)


def _options_has_controls(widget: QWidget) -> bool:
    """True when *widget* has a layout with rows/controls (not a bare QWidget())."""
    lay = widget.layout()
    if lay is not None:
        return lay.count() > 0
    return any(isinstance(c, QWidget) for c in widget.children())


class ToolShellWindow(JobChromeMixin, QWidget):
    """Reusable tool chrome: title → drop → options → Run → results (editor tab)."""

    def __init__(
        self,
        *,
        title: str,
        description: str,
        editor: QWidget | None = None,
        window_manager: object | None = None,
        multi: bool = False,
        browse_title: str = "Choose PDF",
        empty_prompt: str | None = None,
        accept: Callable[[str], bool] | None = None,
        dialog_filter: str = _PDF_FILTER,
    ) -> None:
        super().__init__(None)
        if empty_prompt is None:
            empty_prompt = EMPTY_PROMPT_PDFS if multi else EMPTY_PROMPT_PDF
        self.WINDOW_TITLE = title
        self._editor = editor
        self._window_manager = window_manager
        self._init_job_chrome_state()
        self._run_handler: Callable[[], None] | None = None
        self._run_enabled_check: Callable[[], bool] | None = None
        self._status = StatusFooter()

        self.setWindowTitle(title)
        self.setObjectName("ToolShellWindow")
        self.setMinimumSize(520, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 8)
        root.setSpacing(12)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("ToolShellTitle")
        root.addWidget(self._title_label)

        self._desc_label = QLabel(description)
        self._desc_label.setObjectName("ToolShellDescription")
        self._desc_label.setWordWrap(True)
        root.addWidget(self._desc_label)

        # Optional chrome above the drop zone (e.g. Change File after pick).
        self._chrome_host = QWidget()
        self._chrome_host.setObjectName("ToolShellChrome")
        self._chrome_layout = QVBoxLayout(self._chrome_host)
        self._chrome_layout.setContentsMargins(0, 0, 0, 0)
        self._chrome_layout.setSpacing(0)
        self._chrome_host.hide()
        root.addWidget(self._chrome_host)

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

        self._options_scroll = QScrollArea()
        self._options_scroll.setObjectName("ToolShellOptionsScroll")
        self._options_scroll.setWidgetResizable(True)
        self._options_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._options_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._options_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._options_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._options_host = QWidget()
        self._options_host.setObjectName("ToolShellOptions")
        self._options_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._options_layout = QVBoxLayout(self._options_host)
        self._options_layout.setContentsMargins(0, 0, 0, 0)
        self._options_layout.setSpacing(8)
        self._options_layout.addStretch(1)
        self._options_scroll.setWidget(self._options_host)
        root.addWidget(self._options_scroll, stretch=1)

        # R11: compact actions row — never a one-button QToolBar.
        self._actions_host = QWidget()
        self._actions_host.setObjectName("ToolShellActions")
        self._actions_layout = QHBoxLayout(self._actions_host)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions_layout.setSpacing(8)
        self._actions_layout.addStretch(1)

        self._run_btn = QPushButton("Run")
        self._run_btn.setObjectName("ToolbarPrimary")
        self._run_btn.setDefault(True)
        self._run_btn.setEnabled(False)
        self._run_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Match Merge/Create primary-action tips: short sentence-case what Run does.
        self._run_btn.setToolTip(description)
        self._run_btn.setStatusTip(description)
        self._run_btn.clicked.connect(self._on_run)
        self._actions_layout.addWidget(self._run_btn)
        root.addWidget(self._actions_host)

        self._make_job_chrome_widgets()
        self._wire_result_actions()
        root.addWidget(self._result_bar)
        root.addWidget(self._status)

    @property
    def tab_title(self) -> str:
        return self.WINDOW_TITLE

    def statusBar(self) -> StatusFooter:  # noqa: N802
        return self._status

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

        root = self.layout()
        scroll_idx = root.indexOf(self._options_scroll) if root is not None else -1

        # R11: bare / empty host must not leave a dead expanding options band.
        if not _options_has_controls(widget):
            widget.deleteLater()
            self._options_scroll.hide()
            if scroll_idx >= 0:
                root.setStretch(scroll_idx, 0)
            return

        widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self._options_layout.addWidget(widget)
        self._options_layout.addStretch(1)
        self._options_scroll.show()
        if scroll_idx >= 0:
            root.setStretch(scroll_idx, 1)

    def set_chrome_widget(self, widget: QWidget | None) -> None:
        """Optional header above the drop zone (Change File, file meta, …)."""
        while self._chrome_layout.count():
            item = self._chrome_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.deleteLater()
        if widget is None:
            self._chrome_host.hide()
            return
        self._chrome_layout.addWidget(widget)
        self._chrome_host.show()

    def set_drop_zone_visible(self, visible: bool) -> None:
        self._drop_zone.setVisible(visible)

    def set_run_handler(self, handler: Callable[[], None]) -> None:
        self._run_handler = handler

    def set_run_enabled_check(self, check: Callable[[], bool] | None) -> None:
        """Optional extra gate for Run (e.g. backend present). Re-evaluates now."""
        self._run_enabled_check = check
        self._update_run_enabled()

    def adopt_run_button(self, parent_layout: QBoxLayout) -> None:
        """Reparent the single Run button into ``parent_layout``; hide shell actions.

        Preview/split shells dock Run as an options-column footer so the body
        reclaims the full-width actions strip. Enable/click wiring stays on
        ``_run_btn`` — one button object, one enable path.
        """
        self._actions_layout.removeWidget(self._run_btn)
        self._run_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        parent_layout.addWidget(self._run_btn)
        self._actions_host.hide()

    def _set_job_controls_enabled(self, enabled: bool) -> None:
        self._drop_zone.setEnabled(enabled)
        if enabled:
            self._update_run_enabled()
        else:
            self._run_btn.setEnabled(False)

    def _update_run_enabled(self) -> None:
        ok = bool(self._drop_zone.paths()) and not self._job_running
        if ok and self._run_enabled_check is not None:
            ok = bool(self._run_enabled_check())
        self._run_btn.setEnabled(ok)

    def _on_run(self) -> None:
        if self._job_running:
            return
        if self._run_handler is None:
            return
        self._run_handler()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        parent = self._busy_overlay.parentWidget()
        if parent is not None:
            self._busy_overlay.setGeometry(parent.rect())

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self.request_close():
            event.ignore()
            return
        super().closeEvent(event)
