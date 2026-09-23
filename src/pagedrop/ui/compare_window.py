"""Side-by-side PDF compare window (Phase 24)."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import fitz
from PyQt6.QtCore import QObject, QSize, Qt, QRectF, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core import pdf_tools
from pagedrop.core.jobs import (
    CancelToken,
    JobCancelledError,
    RuntimeCredentials,
    preflight_pdf_inputs,
)
from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX, PdfLoadError
from pagedrop.core.pdf_service import page_geometry, render_ref_png
from pagedrop.core.pdf_tools import (
    COMPARE_MAX_RENDER_WIDTH_PX,
    CompareChange,
    CompareReport,
)
from pagedrop.ui.dialogs import prompt_pdf_password
from pagedrop.ui.job_chrome import JobChromeMixin, explain_busy_running
from pagedrop.ui.keyboard_nav import enable_toolbar_keyboard_navigation
from pagedrop.ui.tool_shell import run_tool_job
from pagedrop.ui.tool_page import StatusFooter
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.theme import (
    CLOSE_TAB,
    ICON_SIZE,
    STATUS_SUCCESS,
    chrome_card_qcolor,
    chrome_text_muted_qcolor,
    close_tab_hex,
    status_success_hex,
    status_warning_hex,
    token_qcolor,
)

# Diff highlight washes on page paper (content plane — not chrome ink).
_DELETED = token_qcolor(CLOSE_TAB, 90)
_ADDED = token_qcolor(STATUS_SUCCESS, 90)

# Keep worker signal objects alive until the slot runs (QRunnable auto-deletes).
_COMPARE_TEXT_SIGNAL_REFS: list[QObject] = []
_COMPARE_TEXT_POOL: QThreadPool | None = None


def _compare_text_pool() -> QThreadPool:
    global _COMPARE_TEXT_POOL
    if _COMPARE_TEXT_POOL is None:
        _COMPARE_TEXT_POOL = QThreadPool()
        _COMPARE_TEXT_POOL.setMaxThreadCount(1)
        _COMPARE_TEXT_POOL.setObjectName("PageDropCompareTextPool")
    return _COMPARE_TEXT_POOL


class _CompareTextWorker(QRunnable):
    """Run ``compare_pdf_text_diff`` off the UI thread with cooperative cancel."""

    class Signals(QObject):
        succeeded = pyqtSignal(object)
        cancelled = pyqtSignal()
        failed = pyqtSignal(str)

    def __init__(
        self,
        path_a: str,
        path_b: str,
        cancel: CancelToken,
        passwords: dict[str, str],
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._path_a = path_a
        self._path_b = path_b
        self._cancel = cancel
        self._passwords = passwords
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            report = pdf_tools.compare_pdf_text_diff(
                self._path_a,
                self._path_b,
                password_a=self._passwords.get(str(Path(self._path_a).resolve())),
                password_b=self._passwords.get(str(Path(self._path_b).resolve())),
                cancel=self._cancel,
            )
        except JobCancelledError:
            self.signals.cancelled.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(report)


def _pick_pdf(parent: QWidget, title: str, initial: str = "") -> str | None:
    start = str(Path(initial).parent) if initial else last_directory()
    path, _ = QFileDialog.getOpenFileName(
        parent, title, start, "PDF files (*.pdf);;All files (*)"
    )
    if not path:
        return None
    remember_directory(path)
    return path


def prompt_compare_export_options(
    parent: QWidget,
) -> tuple[str, bool, bool] | None:
    """Ask for the PDF report layout and optional appendix sections."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Export comparison")
    dialog.setModal(True)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(8)

    split = QRadioButton("Split view")
    split.setToolTip("Place Original and Revised pages side by side.")
    split.setAccessibleDescription("Place Original and Revised pages side by side.")
    split.setChecked(True)
    alternate = QRadioButton("Alternating")
    alternate.setToolTip("Place Original then Revised pages in reading order.")
    alternate.setAccessibleDescription(
        "Place Original then Revised pages in reading order."
    )
    layout.addWidget(split)
    layout.addWidget(QLabel("Original and Revised pages share each comparison position."))
    layout.addWidget(alternate)
    layout.addWidget(QLabel("Each comparison position is emitted as two labeled pages."))

    summary = QCheckBox("Summary")
    summary.setChecked(True)
    revisions = QCheckBox("Revisions")
    revisions.setChecked(True)
    layout.addWidget(summary)
    layout.addWidget(revisions)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return ("split" if split.isChecked() else "alternating", summary.isChecked(), revisions.isChecked())


def _render_page_pixmap(
    path: str,
    page_index: int,
    width_px: int,
    *,
    passwords: dict[str, str] | None = None,
) -> tuple[QPixmap, fitz.Rect]:
    """Render one compare pane via ``pdf_service`` (holds ``FITZ_LOCK``)."""
    target = max(1, min(int(width_px), COMPARE_MAX_RENDER_WIDTH_PX, MAX_RENDER_WIDTH_PX))
    password = RuntimeCredentials.lookup(passwords, path)
    geom = page_geometry(path, page_index, password=password)
    png = render_ref_png(PageRef(path, page_index), target, passwords=passwords)
    qpix = QPixmap()
    if not qpix.loadFromData(png):
        raise PdfLoadError(f"Could not decode page render for {Path(path).name}")
    return qpix, fitz.Rect(0, 0, geom.width, geom.height)


class _PathBrowseRow(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: QWidget, *, label: str, browse_title: str) -> None:
        super().__init__(parent)
        self._browse_title = browse_title
        self.setAccessibleName(f"{label} PDF input")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._label = QLabel(label)
        self._label.setMinimumWidth(48)
        self._edit = QLineEdit()
        self._edit.setAccessibleName(f"{label} PDF path")
        self._edit.setAccessibleDescription(f"Path to the {label.lower()} PDF")
        self._edit.setPlaceholderText("Choose a PDF…")
        self._edit.textChanged.connect(lambda _t: self.changed.emit())
        browse = QPushButton("Browse…")
        browse.setObjectName("ToolbarSecondary")
        browse.clicked.connect(self._browse)
        layout.addWidget(self._label)
        layout.addWidget(self._edit, stretch=1)
        layout.addWidget(browse)

    def text(self) -> str:
        return self._edit.text().strip()

    def set_text(self, value: str) -> None:
        self._edit.setText(value)

    def _browse(self) -> None:
        path = _pick_pdf(self, self._browse_title, self.text())
        if path:
            self.set_text(path)


class _ComparePageCanvas(QWidget):
    """Page pixmap with translucent highlight rectangles in PDF space."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._page_rect = fitz.Rect(0, 0, 1, 1)
        self._highlights: list[tuple[tuple[float, float, float, float], QColor]] = []
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_content(
        self,
        pixmap: QPixmap,
        page_rect: fitz.Rect,
        highlights: list[tuple[tuple[float, float, float, float], QColor]],
    ) -> None:
        self._pixmap = pixmap
        self._page_rect = page_rect
        self._highlights = highlights
        if not pixmap.isNull():
            self.setFixedSize(pixmap.size())
        else:
            self.setFixedSize(200, 260)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), chrome_card_qcolor())
        if self._pixmap.isNull():
            painter.setPen(chrome_text_muted_qcolor())
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No page")
            return
        painter.drawPixmap(0, 0, self._pixmap)
        sx = self._pixmap.width() / max(1.0, float(self._page_rect.width))
        sy = self._pixmap.height() / max(1.0, float(self._page_rect.height))
        for (x0, y0, x1, y1), color in self._highlights:
            painter.fillRect(
                QRectF(x0 * sx, y0 * sy, (x1 - x0) * sx, (y1 - y0) * sy),
                color,
            )


class _ComparePane(QWidget):
    """Labeled scrollable page view."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._title = QLabel(title)
        self._title.setObjectName("ComparePaneTitle")
        layout.addWidget(self._title)
        self._notice = QLabel()
        self._notice.setObjectName("CompareTextlessNotice")
        self._notice.setWordWrap(True)
        self._notice.hide()
        layout.addWidget(self._notice)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self._canvas = _ComparePageCanvas()
        self._scroll.setWidget(self._canvas)
        layout.addWidget(self._scroll, stretch=1)

    @property
    def scroll(self) -> QScrollArea:
        return self._scroll

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_notice(self, text: str | None) -> None:
        self._notice.setText(text or "")
        self._notice.setVisible(bool(text))

    def set_content(
        self,
        pixmap: QPixmap,
        page_rect: fitz.Rect,
        highlights: list[tuple[tuple[float, float, float, float], QColor]],
    ) -> None:
        self._canvas.set_content(pixmap, page_rect, highlights)


class CompareWindow(JobChromeMixin, QWidget):
    WINDOW_TITLE = "Compare PDFs"
    PAGE_ID = "compare"

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        editor: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.tool_page_id = self.PAGE_ID
        self._editor = editor
        self._status = StatusFooter()
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setObjectName("CompareWindow")
        self.setMinimumSize(960, 640)

        self._report: CompareReport | None = None
        self._path_a = ""
        self._path_b = ""
        self._page_index = 0
        self._zoom = 1.0  # relative to fit-width baseline
        self._syncing_scroll = False
        self._selected_change: CompareChange | None = None
        self._comparing = False
        self._cancel_token: CancelToken | None = None
        self._credentials = RuntimeCredentials()
        self._input_revision = 0
        self._render_suppressed = False

        self._init_job_chrome_state()
        self._build_ui()
        self._connect()

    @property
    def tab_title(self) -> str:
        return self.WINDOW_TITLE

    def statusBar(self) -> StatusFooter:  # noqa: N802
        return self._status

    def set_editor(self, editor: QWidget | None) -> None:
        self._editor = editor

    def request_close(self) -> bool:
        if self._comparing or self._job_running:
            self._explain_busy()
            return False
        return True

    def _explain_busy(self) -> None:
        explain_busy_running(
            status_bar=self.statusBar(),
            toast=self._toast,
            label="Compare",
        )

    def prefill_a(self, path: str) -> None:
        if path:
            self._row_a.set_text(path)

    def _set_job_controls_enabled(self, enabled: bool) -> None:
        self._row_a.setEnabled(enabled)
        self._row_b.setEnabled(enabled)
        self._compare_btn.setEnabled(enabled)
        self._toolbar.setEnabled(enabled)
        if enabled:
            has_report = self._report is not None
            self._export_act.setEnabled(has_report)
            self._heatmap_act.setEnabled(has_report)

    def begin_job(self, message: str = "Working…") -> CancelToken:
        self._render_suppressed = True
        return super().begin_job(message)

    def end_job(self, **kwargs) -> None:
        error = kwargs.get("error")
        if error and "compare again" in str(error).lower():
            self._invalidate_compare(cancel=False)
        super().end_job(**kwargs)
        self._render_suppressed = False
        if self._report is not None:
            self._render_pages()

    def _invalidate_compare(self, *, cancel: bool = True) -> None:
        self._input_revision += 1
        if cancel and self._comparing and self._cancel_token is not None:
            self._cancel_token.cancel()
        self._report = None
        self._path_a = ""
        self._path_b = ""
        self._page_index = 0
        self._selected_change = None
        self._toolbar.setVisible(False)
        self._export_act.setEnabled(False)
        self._heatmap_act.setEnabled(False)
        self._change_list.clear()
        self._summary.setText("Removed 0 · Added 0 · Replaced 0")
        self._result_bar.clear()
        self._pane_a.set_title("Original")
        self._pane_b.set_title("Revised")
        self._pane_a.set_notice(None)
        self._pane_b.set_notice(None)
        empty = QPixmap()
        empty_rect = fitz.Rect(0, 0, 200, 260)
        self._pane_a.set_content(empty, empty_rect, [])
        self._pane_b.set_content(empty, empty_rect, [])

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        paths = QVBoxLayout()
        paths.setContentsMargins(0, 0, 0, 0)
        paths.setSpacing(6)
        self._row_a = _PathBrowseRow(self, label="Original", browse_title="Choose Original PDF")
        self._row_b = _PathBrowseRow(self, label="Revised", browse_title="Choose Revised PDF")
        self._compare_btn = QPushButton("Compare")
        self._compare_btn.setObjectName("ToolbarPrimary")
        self._compare_btn.setDefault(True)
        # R13: primary trails the last browse row — not a solo stretch row.
        row_b_layout = self._row_b.layout()
        assert isinstance(row_b_layout, QHBoxLayout)
        row_b_layout.addWidget(self._compare_btn)
        paths.addWidget(self._row_a)
        paths.addWidget(self._row_b)
        root.addLayout(paths)

        toolbar = QToolBar("Compare", self)
        toolbar.setObjectName("CompareToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        # R13: mode/nav/zoom/sync/export stay hidden until a report exists.
        toolbar.setVisible(False)
        root.addWidget(toolbar)
        self._toolbar = toolbar
        self._mode_label = QLabel("  Original / Revised  ")
        self._mode_label.setObjectName("CompareModeLabel")
        toolbar.addWidget(self._mode_label)
        toolbar.addSeparator()

        self._prev_act = toolbar.addAction("Previous page")
        self._next_act = toolbar.addAction("Next page")
        self._page_label = QLabel("Page:")
        toolbar.addWidget(self._page_label)
        toolbar.addSeparator()

        self._zoom_out = toolbar.addAction("Zoom out")
        self._zoom_in = toolbar.addAction("Zoom in")
        self._zoom_fit = toolbar.addAction("Fit width")
        toolbar.addSeparator()

        self._sync_scroll = QCheckBox("Sync scroll")
        self._sync_scroll.setChecked(True)
        toolbar.addWidget(self._sync_scroll)
        toolbar.addSeparator()
        self._export_act = toolbar.addAction("Export comparison…")
        self._export_act.setEnabled(False)
        self._heatmap_act = toolbar.addAction("Export visual heatmap…")
        self._heatmap_act.setEnabled(False)
        enable_toolbar_keyboard_navigation(toolbar)

        body = QSplitter(Qt.Orientation.Horizontal)
        pages = QSplitter(Qt.Orientation.Horizontal)
        self._pane_a = _ComparePane("Original")
        self._pane_b = _ComparePane("Revised")
        pages.addWidget(self._pane_a)
        pages.addWidget(self._pane_b)
        pages.setStretchFactor(0, 1)
        pages.setStretchFactor(1, 1)
        body.addWidget(pages)

        side = QWidget()
        side.setMinimumWidth(240)
        side.setMaximumWidth(360)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(8, 0, 0, 0)
        side_layout.setSpacing(8)
        side_layout.addWidget(QLabel("Changes"))
        self._summary = QLabel("Removed 0 · Added 0 · Replaced 0")
        self._summary.setObjectName("CompareSummary")
        self._summary.setWordWrap(True)
        side_layout.addWidget(self._summary)
        self._limitation = QLabel(
            "Text comparison, matched by page number. Image, formatting, and "
            "moved-content differences are not classified."
        )
        self._limitation.setWordWrap(True)
        self._limitation.setObjectName("CompareLimitation")
        side_layout.addWidget(self._limitation)
        self._change_list = QListWidget()
        self._change_list.setObjectName("CompareChangeList")
        side_layout.addWidget(self._change_list, stretch=1)
        body.addWidget(side)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        root.addWidget(body, stretch=1)

        self._make_job_chrome_widgets()
        self._busy = self._busy_overlay
        root.addWidget(self._result_bar)
        root.addWidget(self._status)

    def _connect(self) -> None:
        self._compare_btn.clicked.connect(self._run_compare)
        self._prev_act.triggered.connect(lambda: self._nudge_page(-1))
        self._next_act.triggered.connect(lambda: self._nudge_page(1))
        self._zoom_in.triggered.connect(lambda: self._nudge_zoom(1.15))
        self._zoom_out.triggered.connect(lambda: self._nudge_zoom(1 / 1.15))
        self._zoom_fit.triggered.connect(self._fit_width)
        self._export_act.triggered.connect(self._export_comparison)
        self._heatmap_act.triggered.connect(self._export_heatmap)
        self._row_a.changed.connect(self._invalidate_compare)
        self._row_b.changed.connect(self._invalidate_compare)
        self._change_list.currentRowChanged.connect(self._on_change_selected)
        self._pane_a.scroll.verticalScrollBar().valueChanged.connect(
            lambda v: self._mirror_scroll(self._pane_a, self._pane_b, v)
        )
        self._pane_b.scroll.verticalScrollBar().valueChanged.connect(
            lambda v: self._mirror_scroll(self._pane_b, self._pane_a, v)
        )
        self._pane_a.scroll.horizontalScrollBar().valueChanged.connect(
            lambda v: self._mirror_hscroll(self._pane_a, self._pane_b, v)
        )
        self._pane_b.scroll.horizontalScrollBar().valueChanged.connect(
            lambda v: self._mirror_hscroll(self._pane_b, self._pane_a, v)
        )
        self._wire_result_actions()
        self._busy.escape_blocked.connect(self._explain_busy)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._busy_overlay.setGeometry(self.rect())
        if self._report is not None and not self._render_suppressed:
            self._render_pages()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._nudge_zoom(1.1)
            elif delta < 0:
                self._nudge_zoom(1 / 1.1)
            event.accept()
            return
        super().wheelEvent(event)

    def _mirror_scroll(self, source: _ComparePane, target: _ComparePane, value: int) -> None:
        if not self._sync_scroll.isChecked() or self._syncing_scroll:
            return
        self._syncing_scroll = True
        try:
            src = source.scroll.verticalScrollBar()
            dst = target.scroll.verticalScrollBar()
            if src.maximum() <= 0 or dst.maximum() <= 0:
                dst.setValue(value)
            else:
                ratio = value / float(src.maximum())
                dst.setValue(int(round(ratio * dst.maximum())))
        finally:
            self._syncing_scroll = False

    def _mirror_hscroll(self, source: _ComparePane, target: _ComparePane, value: int) -> None:
        if not self._sync_scroll.isChecked() or self._syncing_scroll:
            return
        self._syncing_scroll = True
        try:
            target.scroll.horizontalScrollBar().setValue(value)
        finally:
            self._syncing_scroll = False

    def _cancel_compare(self) -> None:
        self.cancel_active_job()

    def _run_compare(self) -> None:
        path_a = self._row_a.text()
        path_b = self._row_b.text()
        if not path_a or not Path(path_a).is_file():
            QMessageBox.warning(self, self.WINDOW_TITLE, "Choose a valid Original PDF.")
            return
        if not path_b or not Path(path_b).is_file():
            QMessageBox.warning(self, self.WINDOW_TITLE, "Choose a valid Revised PDF.")
            return
        if Path(path_a).resolve() == Path(path_b).resolve():
            QMessageBox.warning(self, self.WINDOW_TITLE, "Choose two different PDF files.")
            return
        if self._job_running:
            self._explain_busy()
            return

        revision = self._input_revision
        self._comparing = True
        token = self.begin_job("Comparing…")
        try:
            self._credentials = preflight_pdf_inputs(
                [path_a, path_b],
                prompt=lambda name, incorrect: prompt_pdf_password(
                    self, name, incorrect=incorrect
                ),
                credentials=self._credentials,
                cancel=token,
            )
        except JobCancelledError:
            self._comparing = False
            self.end_job(status="Cancelled", toast="Compare cancelled", toast_kind="info")
            return
        except PdfLoadError as exc:
            self._comparing = False
            self.end_job(error=str(exc), toast="Compare failed", toast_kind="error")
            return

        worker = _CompareTextWorker(
            path_a, path_b, token, self._credentials.snapshot()
        )
        signals = worker.signals
        _COMPARE_TEXT_SIGNAL_REFS.append(signals)

        def _drop_ref() -> None:
            try:
                _COMPARE_TEXT_SIGNAL_REFS.remove(signals)
            except ValueError:
                pass

        def _on_ok(report: object) -> None:
            _drop_ref()
            self._comparing = False
            if not isinstance(report, CompareReport):
                self.end_job(error="Compare failed", toast="Compare failed", toast_kind="error")
                return
            if (
                revision != self._input_revision
                or path_a != self._row_a.text()
                or path_b != self._row_b.text()
            ):
                self.end_job(
                    status="Files changed; compare again",
                    toast="Compare result discarded",
                    toast_kind="info",
                )
                return
            self.end_job()
            self._apply_compare_report(path_a, path_b, report)

        def _on_cancelled() -> None:
            _drop_ref()
            self._comparing = False
            self.end_job(status="Cancelled", toast="Compare cancelled", toast_kind="info")

        def _on_failed(message: str) -> None:
            _drop_ref()
            self._comparing = False
            self.end_job(error=message, toast="Compare failed", toast_kind="error")

        signals.succeeded.connect(_on_ok)
        signals.cancelled.connect(_on_cancelled)
        signals.failed.connect(_on_failed)
        _compare_text_pool().start(worker)

    def _apply_compare_report(
        self, path_a: str, path_b: str, report: CompareReport
    ) -> None:
        self._path_a = path_a
        self._path_b = path_b
        self._report = report
        self._page_index = 0
        self._selected_change = None
        self._toolbar.setVisible(True)
        self._export_act.setEnabled(True)
        self._heatmap_act.setEnabled(True)
        self._result_bar.clear()
        self._populate_changes()
        self._pane_a.set_title(f"Original: {Path(path_a).name}")
        self._pane_b.set_title(f"Revised: {Path(path_b).name}")
        self._fit_width()
        total = max(report.page_count_a, report.page_count_b, 1)
        n = len(report.changes)
        self.statusBar().showMessage(
            f"Compared · {n} change{'s' if n != 1 else ''} · {total} page pair(s)"
        )
        self._toast.show_toast(
            f"{report.deleted_count} removed · {report.added_count} added · "
            f"{report.modified_count} replaced",
            kind="success" if n else "info",
        )

    def _populate_changes(self) -> None:
        assert self._report is not None
        r = self._report
        counts = (
            f"Removed {r.deleted_count} · Added {r.added_count} · "
            f"Replaced {r.modified_count}"
        )
        self._summary.setText(
            f"No text changes detected · {counts}" if not r.changes else counts
        )
        self._change_list.clear()
        self._change_list.setWordWrap(True)
        self._change_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        for number, change in enumerate(r.changes, start=1):
            if change.kind == "deleted":
                prefix = "Removed"
                color = close_tab_hex()
            elif change.kind == "added":
                prefix = "Added"
                color = status_success_hex()
            else:
                prefix = "Replaced"
                color = close_tab_hex()
            refs = []
            if change.page_a is not None:
                refs.append(f"Original p.{change.page_a + 1}")
            if change.page_b is not None:
                refs.append(f"Revised p.{change.page_b + 1}")
            label = (
                f"{number}. {prefix} “{change.text}” · {' / '.join(refs)}\n"
                f"Before: {_change_value(change.before_text)}\n"
                f"After: {_change_value(change.after_text)}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, change)
            item.setForeground(token_qcolor(color))
            item.setSizeHint(QSize(0, max(72, self._change_list.fontMetrics().lineSpacing() * 3 + 12)))
            self._change_list.addItem(item)

    def _on_change_selected(self, row: int) -> None:
        if row < 0:
            self._selected_change = None
            self._render_pages()
            return
        item = self._change_list.item(row)
        change = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(change, CompareChange):
            return
        self._selected_change = change
        page = change.page_a if change.page_a is not None else change.page_b
        if page is not None:
            self._page_index = int(page)
        self._render_pages()
        self._scroll_to_change(change)

    def _scroll_to_change(self, change: CompareChange) -> None:
        rects = change.rects_a or change.rects_b
        if not rects:
            return
        x0, y0, _x1, _y1 = rects[0]
        # Approximate scroll using current canvas scale from pane A width.
        pane = self._pane_a if change.rects_a else self._pane_b
        canvas = pane.scroll.widget()
        if not isinstance(canvas, _ComparePageCanvas) or canvas._pixmap.isNull():
            return
        sy = canvas._pixmap.height() / max(1.0, float(canvas._page_rect.height))
        pane.scroll.ensureVisible(int(x0), int(y0 * sy), 40, 80)

    def _nudge_page(self, delta: int) -> None:
        if self._report is None or self._render_suppressed:
            return
        total = max(self._report.page_count_a, self._report.page_count_b, 1)
        self._page_index = max(0, min(total - 1, self._page_index + delta))
        self._selected_change = None
        self._change_list.clearSelection()
        self._render_pages()

    def _nudge_zoom(self, factor: float) -> None:
        self._zoom = max(0.4, min(3.0, self._zoom * factor))
        if not self._render_suppressed:
            self._render_pages()

    def _fit_width(self) -> None:
        self._zoom = 1.0
        if not self._render_suppressed:
            self._render_pages()

    def _target_width(self) -> int:
        # Fit one pane's viewport width.
        avail = max(200, self._pane_a.scroll.viewport().width() - 16)
        return max(120, int(avail * self._zoom))

    def _highlights_for_page(
        self, side: str, page_index: int
    ) -> list[tuple[tuple[float, float, float, float], QColor]]:
        if self._report is None:
            return []
        out: list[tuple[tuple[float, float, float, float], QColor]] = []
        for change in self._report.changes:
            if side == "a":
                if change.page_a != page_index or not change.rects_a:
                    continue
                color = _DELETED
                for rect in change.rects_a:
                    out.append((rect, color))
            else:
                if change.page_b != page_index or not change.rects_b:
                    continue
                color = _ADDED
                for rect in change.rects_b:
                    out.append((rect, color))
        return out

    def _render_pages(self) -> None:
        if (
            self._report is None
            or not self._path_a
            or not self._path_b
            or self._render_suppressed
        ):
            return
        width = self._target_width()
        total = max(self._report.page_count_a, self._report.page_count_b, 1)
        self._page_label.setText(f"Page {self._page_index + 1} / {total}")
        self._prev_act.setEnabled(self._page_index > 0)
        self._next_act.setEnabled(self._page_index < total - 1)

        empty = QPixmap()
        empty_rect = fitz.Rect(0, 0, 200, 260)
        errors: list[str] = []
        passwords = self._credentials.snapshot()

        if self._page_index < self._report.page_count_a:
            try:
                pix_a, rect_a = _render_page_pixmap(
                    self._path_a,
                    self._page_index,
                    width,
                    passwords=passwords,
                )
            except Exception as exc:
                pix_a, rect_a = empty, empty_rect
                errors.append(f"Original: {exc}")
            hl_a = self._highlights_for_page("a", self._page_index)
            self._pane_a.set_content(pix_a, rect_a, hl_a)
            self._pane_a.set_notice(
                "No extractable text on this page"
                if self._page_index in self._report.textless_pages_a
                else None
            )
        else:
            self._pane_a.set_content(empty, empty_rect, [])
            self._pane_a.set_notice("No corresponding page")

        if self._page_index < self._report.page_count_b:
            try:
                pix_b, rect_b = _render_page_pixmap(
                    self._path_b,
                    self._page_index,
                    width,
                    passwords=passwords,
                )
            except Exception as exc:
                pix_b, rect_b = empty, empty_rect
                errors.append(f"Revised: {exc}")
            hl_b = self._highlights_for_page("b", self._page_index)
            self._pane_b.set_content(pix_b, rect_b, hl_b)
            self._pane_b.set_notice(
                "No extractable text on this page"
                if self._page_index in self._report.textless_pages_b
                else None
            )
        else:
            self._pane_b.set_content(empty, empty_rect, [])
            self._pane_b.set_notice("No corresponding page")

        if errors:
            detail = "; ".join(errors)
            self.statusBar().showMessage(f"Could not render page: {detail}")
            self._toast.show_toast("Could not render compare page", kind="error")

    def _save_export_path(self, title: str, suggested: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(
            self, title, suggested, "PDF files (*.pdf);;All files (*)"
        )
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"
        remember_directory(path)
        return path

    def _export_comparison(self) -> None:
        if self._job_running or self._report is None or not self._path_a or not self._path_b:
            return
        selected = prompt_compare_export_options(self)
        if selected is None:
            return
        layout, include_summary, include_revisions = selected
        suggested = str(
            Path(self._path_a).with_name(
                f"{Path(self._path_a).stem}_compare_{layout}.pdf"
            )
        )
        path = self._save_export_path("Export comparison PDF", suggested)
        if path is None:
            return
        report = self._report
        if report.source_fingerprint_a is None or report.source_fingerprint_b is None:
            self.end_job(
                error="Comparison has no source fingerprints; compare again.",
                toast="Compare again",
                toast_kind="error",
            )
            return
        run_tool_job(
            self,
            job_type="compare_report",
            inputs=[self._path_a, self._path_b],
            output=path,
            options={
                "layout": layout,
                "include_summary": include_summary,
                "include_revisions": include_revisions,
                "source_fingerprint_a": asdict(report.source_fingerprint_a),
                "source_fingerprint_b": asdict(report.source_fingerprint_b),
            },
            progress_message="Exporting comparison…",
            credentials=self._credentials,
        )

    def _export_heatmap(self) -> None:
        if (
            self._job_running
            or self._report is None
            or not self._path_a
            or not self._path_b
        ):
            return
        suggested = str(
            Path(self._path_a).with_name(f"{Path(self._path_a).stem}_compare.pdf")
        )
        path = self._save_export_path("Export visual heatmap PDF", suggested)
        if path is None:
            return
        report = self._report
        if report.source_fingerprint_a is None or report.source_fingerprint_b is None:
            self.end_job(
                error="Comparison has no source fingerprints; compare again.",
                toast="Compare again",
                toast_kind="error",
            )
            return
        run_tool_job(
            self,
            job_type="compare",
            inputs=[self._path_a, self._path_b],
            output=path,
            options={
                "source_fingerprint_a": asdict(report.source_fingerprint_a),
                "source_fingerprint_b": asdict(report.source_fingerprint_b),
            },
            progress_message="Exporting visual heatmap…",
            success_toast=self._heatmap_success_message,
            credentials=self._credentials,
        )

    def _heatmap_success_message(self, result: str) -> str:
        heatmap_name = Path(result).name
        ratio_path = Path(result).with_suffix(".compare_ratio.txt")
        ratio: float | None = None
        try:
            if ratio_path.exists():
                ratio = float(ratio_path.read_text(encoding="utf-8").strip())
        except Exception:
            ratio = None

        if ratio is None:
            return f"Saved {heatmap_name}"
        return f"Saved {heatmap_name} · Overall diff {ratio:.4f}"


def _change_value(value: str | None) -> str:
    if value is None:
        return "—"
    return value if value else "(blank)"
