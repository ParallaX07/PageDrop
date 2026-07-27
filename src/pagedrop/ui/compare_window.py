"""Side-by-side PDF compare window (Phase 24)."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core import pdf_tools
from pagedrop.core.jobs import (
    JobCancelledError,
    JobError,
    JobSpec,
    OutputExistsError,
    SourceOverwriteError,
)
from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX, PdfLoadError
from pagedrop.core.pdf_tools import (
    COMPARE_MAX_RENDER_WIDTH_PX,
    CompareChange,
    CompareReport,
)
from pagedrop.ui.busy_overlay import BusyOverlay, ToastOverlay
from pagedrop.ui.dialogs import confirm_overwrite
from pagedrop.ui.organize_tools import ensure_organize_runner
from pagedrop.ui.tool_page import StatusFooter, present_tool_page
from pagedrop.ui.result_actions import ResultActionsBar, preview_pdf, show_in_folder
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.theme import (
    ACCENT,
    BG_CARD,
    CLOSE_TAB,
    TEXT_MUTED,
    TEXT_SECONDARY,
)

_DELETED = QColor(232, 93, 93, 90)
_ADDED = QColor(76, 175, 110, 90)
_MODIFIED = QColor(240, 180, 60, 90)


def _pick_pdf(parent: QWidget, title: str, initial: str = "") -> str | None:
    start = str(Path(initial).parent) if initial else last_directory()
    path, _ = QFileDialog.getOpenFileName(
        parent, title, start, "PDF files (*.pdf);;All files (*)"
    )
    if not path:
        return None
    remember_directory(path)
    return path


def _render_page_pixmap(path: str, page_index: int, width_px: int) -> tuple[QPixmap, fitz.Rect]:
    doc = fitz.open(path)
    try:
        if page_index < 0 or page_index >= len(doc):
            raise PdfLoadError(f"Page out of range: {page_index}")
        page = doc[page_index]
        rect = page.rect
        target = max(1, min(int(width_px), COMPARE_MAX_RENDER_WIDTH_PX, MAX_RENDER_WIDTH_PX))
        scale = target / float(rect.width)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        qpix = QPixmap()
        qpix.loadFromData(pix.tobytes("png"))
        return qpix, fitz.Rect(rect)
    finally:
        doc.close()


class _PathBrowseRow(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: QWidget, *, label: str, browse_title: str) -> None:
        super().__init__(parent)
        self._browse_title = browse_title
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._label = QLabel(label)
        self._label.setMinimumWidth(48)
        self._edit = QLineEdit()
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
        painter.fillRect(self.rect(), QColor(BG_CARD))
        if self._pixmap.isNull():
            painter.setPen(QColor(TEXT_MUTED))
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
        self._title.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(self._title)

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

    def set_content(
        self,
        pixmap: QPixmap,
        page_rect: fitz.Rect,
        highlights: list[tuple[tuple[float, float, float, float], QColor]],
    ) -> None:
        self._canvas.set_content(pixmap, page_rect, highlights)


class CompareWindow(QWidget):
    WINDOW_TITLE = "Compare PDFs"
    PAGE_ID = "compare"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tool_page_id = self.PAGE_ID
        self._status = StatusFooter(initial="Choose two PDFs and click Compare")
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

        self._build_ui()
        self._connect()

    @property
    def tab_title(self) -> str:
        return self.WINDOW_TITLE

    def statusBar(self) -> StatusFooter:  # noqa: N802
        return self._status

    def request_close(self) -> bool:
        return True

    def prefill_a(self, path: str) -> None:
        if path:
            self._row_a.set_text(path)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        paths = QVBoxLayout()
        paths.setContentsMargins(0, 0, 0, 0)
        paths.setSpacing(6)
        self._row_a = _PathBrowseRow(self, label="PDF A", browse_title="Choose first PDF")
        self._row_b = _PathBrowseRow(self, label="PDF B", browse_title="Choose second PDF")
        paths.addWidget(self._row_a)
        paths.addWidget(self._row_b)
        root.addLayout(paths)

        actions = QHBoxLayout()
        self._compare_btn = QPushButton("Compare")
        self._compare_btn.setObjectName("ToolbarPrimary")
        self._compare_btn.setDefault(True)
        actions.addWidget(self._compare_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        toolbar = QToolBar("Compare", self)
        toolbar.setMovable(False)
        root.addWidget(toolbar)
        self._mode_label = QLabel("  Side-by-side  ")
        self._mode_label.setStyleSheet(f"color: {ACCENT}; font-weight: 600;")
        toolbar.addWidget(self._mode_label)
        toolbar.addSeparator()

        self._prev_act = toolbar.addAction("Previous page")
        self._next_act = toolbar.addAction("Next page")
        self._page_label = QLabel("Page —")
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
        self._export_act = toolbar.addAction("Export…")
        self._export_act.setEnabled(False)

        body = QSplitter(Qt.Orientation.Horizontal)
        pages = QSplitter(Qt.Orientation.Horizontal)
        self._pane_a = _ComparePane("PDF A")
        self._pane_b = _ComparePane("PDF B")
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
        self._summary = QLabel("Deleted 0 · Added 0 · Modified 0")
        self._summary.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self._summary.setWordWrap(True)
        side_layout.addWidget(self._summary)
        self._change_list = QListWidget()
        self._change_list.setObjectName("CompareChangeList")
        side_layout.addWidget(self._change_list, stretch=1)
        body.addWidget(side)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        root.addWidget(body, stretch=1)

        self._result_bar = ResultActionsBar()
        root.addWidget(self._result_bar)

        self._busy = BusyOverlay(self)
        self._toast = ToastOverlay(self)
        root.addWidget(self._status)

    def _connect(self) -> None:
        self._compare_btn.clicked.connect(self._run_compare)
        self._prev_act.triggered.connect(lambda: self._nudge_page(-1))
        self._next_act.triggered.connect(lambda: self._nudge_page(1))
        self._zoom_in.triggered.connect(lambda: self._nudge_zoom(1.15))
        self._zoom_out.triggered.connect(lambda: self._nudge_zoom(1 / 1.15))
        self._zoom_fit.triggered.connect(self._fit_width)
        self._export_act.triggered.connect(self._export_heatmap)
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
        self._result_bar.preview_requested.connect(self._preview_export)
        self._result_bar.show_in_folder_requested.connect(self._show_folder)
        self._result_bar.open_in_editor_requested.connect(
            lambda _path: self._toast.show_toast(
                "Open the exported PDF from the editor File → Open", kind="info"
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._report is not None:
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

    def _run_compare(self) -> None:
        path_a = self._row_a.text()
        path_b = self._row_b.text()
        if not path_a or not Path(path_a).is_file():
            QMessageBox.warning(self, self.WINDOW_TITLE, "Choose a valid PDF A.")
            return
        if not path_b or not Path(path_b).is_file():
            QMessageBox.warning(self, self.WINDOW_TITLE, "Choose a valid PDF B.")
            return
        if Path(path_a).resolve() == Path(path_b).resolve():
            QMessageBox.warning(self, self.WINDOW_TITLE, "Choose two different PDF files.")
            return

        self.statusBar().showMessage("Comparing…")
        self._busy.show_message("Comparing…")
        QApplication.processEvents()
        try:
            report = pdf_tools.compare_pdf_text_diff(path_a, path_b)
        except PdfLoadError as exc:
            self.statusBar().showMessage("Compare failed")
            QMessageBox.critical(self, self.WINDOW_TITLE, str(exc))
            return
        except Exception as exc:
            self.statusBar().showMessage("Compare failed")
            QMessageBox.critical(self, self.WINDOW_TITLE, f"Could not compare PDFs:\n{exc}")
            return
        finally:
            self._busy.hide_overlay()

        self._path_a = path_a
        self._path_b = path_b
        self._report = report
        self._page_index = 0
        self._selected_change = None
        self._export_act.setEnabled(True)
        self._result_bar.clear()
        self._populate_changes()
        self._pane_a.set_title(f"PDF A — {Path(path_a).name}")
        self._pane_b.set_title(f"PDF B — {Path(path_b).name}")
        self._fit_width()
        total = max(report.page_count_a, report.page_count_b, 1)
        n = len(report.changes)
        self.statusBar().showMessage(
            f"Compared · {n} change{'s' if n != 1 else ''} · {total} page pair(s)"
        )
        self._toast.show_toast(
            f"{report.deleted_count} deleted · {report.added_count} added · "
            f"{report.modified_count} modified",
            kind="success" if n else "info",
        )

    def _populate_changes(self) -> None:
        assert self._report is not None
        r = self._report
        self._summary.setText(
            f"Deleted {r.deleted_count} · Added {r.added_count} · Modified {r.modified_count}"
        )
        self._change_list.clear()
        for change in r.changes:
            if change.kind == "deleted":
                prefix = "Removed"
                color = CLOSE_TAB
            elif change.kind == "added":
                prefix = "Added"
                color = "#4CAF6E"
            else:
                prefix = "Changed"
                color = "#F0B43C"
            page = (change.page_a if change.page_a is not None else change.page_b) or 0
            label = f"{prefix} “{_truncate(change.text, 72)}”  ·  p.{page + 1}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, change)
            item.setForeground(QColor(color))
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
        if self._report is None:
            return
        total = max(self._report.page_count_a, self._report.page_count_b, 1)
        self._page_index = max(0, min(total - 1, self._page_index + delta))
        self._selected_change = None
        self._change_list.clearSelection()
        self._render_pages()

    def _nudge_zoom(self, factor: float) -> None:
        self._zoom = max(0.4, min(3.0, self._zoom * factor))
        self._render_pages()

    def _fit_width(self) -> None:
        self._zoom = 1.0
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
                color = _DELETED if change.kind == "deleted" else _MODIFIED
                for rect in change.rects_a:
                    out.append((rect, color))
            else:
                if change.page_b != page_index or not change.rects_b:
                    continue
                color = _ADDED if change.kind == "added" else _MODIFIED
                for rect in change.rects_b:
                    out.append((rect, color))
        return out

    def _render_pages(self) -> None:
        if self._report is None or not self._path_a or not self._path_b:
            return
        width = self._target_width()
        total = max(self._report.page_count_a, self._report.page_count_b, 1)
        self._page_label.setText(f"Page {self._page_index + 1} / {total}")
        self._prev_act.setEnabled(self._page_index > 0)
        self._next_act.setEnabled(self._page_index < total - 1)

        empty = QPixmap()
        empty_rect = fitz.Rect(0, 0, 200, 260)

        if self._page_index < self._report.page_count_a:
            try:
                pix_a, rect_a = _render_page_pixmap(
                    self._path_a, self._page_index, width
                )
            except Exception:
                pix_a, rect_a = empty, empty_rect
            hl_a = self._highlights_for_page("a", self._page_index)
            self._pane_a.set_content(pix_a, rect_a, hl_a)
        else:
            self._pane_a.set_content(empty, empty_rect, [])

        if self._page_index < self._report.page_count_b:
            try:
                pix_b, rect_b = _render_page_pixmap(
                    self._path_b, self._page_index, width
                )
            except Exception:
                pix_b, rect_b = empty, empty_rect
            hl_b = self._highlights_for_page("b", self._page_index)
            self._pane_b.set_content(pix_b, rect_b, hl_b)
        else:
            self._pane_b.set_content(empty, empty_rect, [])

    def _export_heatmap(self) -> None:
        if not self._path_a or not self._path_b:
            return
        suggested = str(
            Path(self._path_a).with_name(f"{Path(self._path_a).stem}_compare.pdf")
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export heatmap PDF",
            suggested,
            "PDF files (*.pdf);;All files (*)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"
        remember_directory(path)
        out = Path(path)
        if out.exists() and not confirm_overwrite(
            self, [out], window_title=self.WINDOW_TITLE
        ):
            self.statusBar().showMessage("Cancelled")
            return

        self.statusBar().showMessage("Exporting heatmap…")
        self._busy.show_message("Exporting…")
        QApplication.processEvents()
        try:
            runner = ensure_organize_runner()
            result = runner.run(
                JobSpec.create(
                    "compare",
                    inputs=[self._path_a, self._path_b],
                    output=path,
                    overwrite=True,
                )
            )
        except (JobCancelledError, SourceOverwriteError, OutputExistsError, JobError) as exc:
            self.statusBar().showMessage("Export failed")
            QMessageBox.warning(self, self.WINDOW_TITLE, str(exc))
            return
        except Exception as exc:
            self.statusBar().showMessage("Export failed")
            QMessageBox.critical(self, self.WINDOW_TITLE, f"Could not export:\n{exc}")
            return
        finally:
            self._busy.hide_overlay()

        heatmap_name = Path(result).name
        ratio_path = Path(result).with_suffix(".compare_ratio.txt")
        ratio: float | None = None
        try:
            if ratio_path.exists():
                ratio = float(ratio_path.read_text(encoding="utf-8").strip())
        except Exception:
            ratio = None

        if ratio is None:
            self.statusBar().showMessage(f"Saved {heatmap_name}")
            self._toast.show_toast(f"Saved {heatmap_name}", kind="success")
            self._result_bar.show_for(result, message=f"Saved {heatmap_name}")
        else:
            msg = f"Saved {heatmap_name} · Overall diff {ratio:.4f}"
            self.statusBar().showMessage(msg)
            self._toast.show_toast(msg, kind="success")
            self._result_bar.show_for(result, message=msg)

    def _preview_export(self, path: str) -> None:
        preview_pdf(path, parent=self)

    def _show_folder(self, path: str) -> None:
        if not show_in_folder(path):
            self._toast.show_toast("Could not open folder", kind="error")


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"
