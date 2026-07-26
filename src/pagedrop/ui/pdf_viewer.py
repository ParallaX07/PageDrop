"""Full PDF viewer — virtualized read/navigate over ``PdfEditModel``.

Read-only: zoom, search, select/copy, links, outline, layers, attachments, print.
Renders go through ``pagedrop.core.pdf_service`` (shared fitz lock), not ad-hoc
concurrent pools.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from PyQt6.QtCore import (
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX, PdfLoader
from pagedrop.core.pdf_service import (
    MAX_PRINT_PAGES,
    AttachmentInfo,
    LinkInfo,
    SearchHit,
    attachments_for_path,
    extract_attachment,
    layers_for_path,
    logical_index_for_source,
    outline_for_paths,
    page_geometry,
    page_links,
    page_text_dict,
    render_ref_png,
    search_model,
)
from pagedrop.core.thread_policy import ensure_no_fitz_document
from pagedrop.ui.busy_overlay import BusyOverlay
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    MIN_PREVIEW_RENDER_WIDTH,
    ZOOM_WHEEL_STEP,
)

PAGE_GAP_PX = 16
SIDE_PANEL_WIDTH = 240
CACHE_MAX_PIXMAPS = 48
RENDER_DEBOUNCE_MS = 80
DEFAULT_ZOOM_PERCENT = 100
MIN_ZOOM_PERCENT = 25
MAX_ZOOM_PERCENT = 400


class ViewerLayout(str, Enum):
    CONTINUOUS = "continuous"
    SINGLE = "single"
    SPREAD = "spread"


class ZoomMode(str, Enum):
    FIT_WIDTH = "fit_width"
    FIT_PAGE = "fit_page"
    PERCENT = "percent"


class _LruPixmapCache:
    def __init__(self, max_items: int = CACHE_MAX_PIXMAPS) -> None:
        self._max = max_items
        self._items: OrderedDict[tuple, QPixmap] = OrderedDict()

    def get(self, key: tuple) -> QPixmap | None:
        pix = self._items.get(key)
        if pix is not None:
            self._items.move_to_end(key)
        return pix

    def put(self, key: tuple, pixmap: QPixmap) -> None:
        self._items[key] = pixmap
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


class _ViewerRenderWorker(QRunnable):
    class Signals(QObject):
        finished = pyqtSignal(int, int, int, bytes)  # gen, logical, width, png
        error = pyqtSignal(int, int, str)

    def __init__(
        self,
        ref: PageRef,
        logical_page: int,
        width_px: int,
        generation: int,
        is_cancelled: Callable[[int], bool],
        ocg_on: frozenset[int] | None,
    ) -> None:
        super().__init__()
        ensure_no_fitz_document(ref.source_path, what="ViewerRenderWorker")
        self.signals = self.Signals()
        self._ref = ref
        self._logical_page = logical_page
        self._width_px = width_px
        self._generation = generation
        self._is_cancelled = is_cancelled
        self._ocg_on = ocg_on
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            if self._is_cancelled(self._generation):
                return
            png = render_ref_png(
                self._ref,
                self._width_px,
                ocg_on=self._ocg_on,
            )
            if self._is_cancelled(self._generation):
                return
            self.signals.finished.emit(
                self._generation,
                self._logical_page,
                self._width_px,
                png,
            )
        except Exception as exc:
            if not self._is_cancelled(self._generation):
                self.signals.error.emit(
                    self._generation, self._logical_page, str(exc)
                )


class _ViewerSearchWorker(QRunnable):
    class Signals(QObject):
        finished = pyqtSignal(int, object)  # gen, list[SearchHit]
        error = pyqtSignal(int, str)

    def __init__(
        self,
        model: PdfEditModel,
        query: str,
        generation: int,
        is_cancelled: Callable[[int], bool],
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._model = model
        self._query = query
        self._generation = generation
        self._is_cancelled = is_cancelled
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            hits = search_model(
                self._model,
                self._query,
                is_cancelled=lambda: self._is_cancelled(self._generation),
            )
            if self._is_cancelled(self._generation):
                return
            self.signals.finished.emit(self._generation, hits)
        except Exception as exc:
            if not self._is_cancelled(self._generation):
                self.signals.error.emit(self._generation, str(exc))


def _rotated_size(width: float, height: float, rotation: int) -> tuple[float, float]:
    if rotation % 180 == 90:
        return height, width
    return width, height


def _map_pdf_rect_to_widget(
    rect: tuple[float, float, float, float],
    page_w: float,
    page_h: float,
    widget_w: int,
    widget_h: int,
    rotation: int,
) -> QRectF:
    """Map unrotated PDF rect into the displayed (possibly rotated) widget."""
    x0, y0, x1, y1 = rect
    rot = rotation % 360
    if rot == 90:
        pts = [(page_h - y1, x0), (page_h - y0, x1)]
        page_w, page_h = page_h, page_w
    elif rot == 180:
        pts = [(page_w - x1, page_h - y1), (page_w - x0, page_h - y0)]
    elif rot == 270:
        pts = [(y0, page_w - x1), (y1, page_w - x0)]
        page_w, page_h = page_h, page_w
    else:
        pts = [(x0, y0), (x1, y1)]

    sx = widget_w / page_w if page_w else 1.0
    sy = widget_h / page_h if page_h else 1.0
    ax = min(p[0] for p in pts) * sx
    ay = min(p[1] for p in pts) * sy
    bx = max(p[0] for p in pts) * sx
    by = max(p[1] for p in pts) * sy
    return QRectF(ax, ay, max(1.0, bx - ax), max(1.0, by - ay))


def _widget_point_to_pdf(
    pos: QPointF,
    page_w: float,
    page_h: float,
    widget_w: int,
    widget_h: int,
    rotation: int,
) -> tuple[float, float]:
    sx = page_w / widget_w if widget_w else 1.0
    sy = page_h / widget_h if widget_h else 1.0
    # Inverse of display rotation: map widget → unrotated PDF space.
    rot = rotation % 360
    if rot == 0:
        return pos.x() * sx, pos.y() * sy
    if rot == 90:
        # display uses (page_h, page_w); widget (x,y) ← (page_h-y, x)
        disp_w, disp_h = page_h, page_w
        dx = pos.x() * (disp_w / widget_w if widget_w else 1.0)
        dy = pos.y() * (disp_h / widget_h if widget_h else 1.0)
        return dy, page_h - dx
    if rot == 180:
        return page_w - pos.x() * sx, page_h - pos.y() * sy
    # 270
    disp_w, disp_h = page_h, page_w
    dx = pos.x() * (disp_w / widget_w if widget_w else 1.0)
    dy = pos.y() * (disp_h / widget_h if widget_h else 1.0)
    return page_w - dy, dx


class _PageTile(QWidget):
    """One visible page surface — pixmap, search highlights, selection, links."""

    link_activated = pyqtSignal(int, object)  # logical_page, LinkInfo
    selection_changed = pyqtSignal()

    def __init__(self, logical_page: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.logical_page = logical_page
        self.setObjectName("PdfViewerPage")
        self.setAccessibleName(f"Page {logical_page + 1}")
        self._pixmap: QPixmap | None = None
        self._page_w = 1.0
        self._page_h = 1.0
        self._rotation = 0
        self._links: list[LinkInfo] = []
        self._hits: list[tuple[float, float, float, float]] = []
        self._text_dict: dict | None = None
        self._selecting = False
        self._sel_start: QPointF | None = None
        self._sel_end: QPointF | None = None
        self._selected_text = ""
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_page_meta(
        self,
        page_w: float,
        page_h: float,
        rotation: int,
        links: list[LinkInfo],
        text_dict: dict | None,
    ) -> None:
        self._page_w = page_w
        self._page_h = page_h
        self._rotation = rotation
        self._links = links
        self._text_dict = text_dict
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def set_hits(self, hits: list[tuple[float, float, float, float]]) -> None:
        self._hits = hits
        self.update()

    def selected_text(self) -> str:
        return self._selected_text

    def clear_selection(self) -> None:
        self._selecting = False
        self._sel_start = None
        self._sel_end = None
        self._selected_text = ""
        self.update()
        self.selection_changed.emit()

    def sizeHint(self):
        from PyQt6.QtCore import QSize

        if self._pixmap is not None and not self._pixmap.isNull():
            return self._pixmap.size()
        return QSize(400, 560)

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self.isVisible() or self.width() <= 0 or self.height() <= 0:
            return
        painter = QPainter(self)
        if not painter.isActive():
            return
        try:
            painter.fillRect(self.rect(), QColor("#FAFAFA"))
            pix = self._pixmap
            if pix is not None and not pix.isNull():
                painter.drawPixmap(0, 0, pix)
            else:
                painter.setPen(QColor("#888888"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "…")

            for hit in self._hits:
                r = _map_pdf_rect_to_widget(
                    hit,
                    self._page_w,
                    self._page_h,
                    self.width(),
                    self.height(),
                    self._rotation,
                )
                painter.fillRect(r, QColor(255, 220, 0, 90))

            if self._sel_start is not None and self._sel_end is not None:
                x0 = min(self._sel_start.x(), self._sel_end.x())
                y0 = min(self._sel_start.y(), self._sel_end.y())
                x1 = max(self._sel_start.x(), self._sel_end.x())
                y1 = max(self._sel_start.y(), self._sel_end.y())
                painter.fillRect(
                    QRectF(x0, y0, x1 - x0, y1 - y0),
                    QColor(40, 120, 255, 60),
                )
        finally:
            painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        link = self._link_at(pos)
        if link is not None:
            self.link_activated.emit(self.logical_page, link)
            event.accept()
            return
        self._selecting = True
        self._sel_start = pos
        self._sel_end = pos
        self._selected_text = ""
        self.update()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self._link_at(pos) is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        if self._selecting:
            self._sel_end = pos
            self._selected_text = self._text_in_selection()
            self.update()
            self.selection_changed.emit()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            self._sel_end = event.position()
            self._selected_text = self._text_in_selection()
            self.selection_changed.emit()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _link_at(self, pos: QPointF) -> LinkInfo | None:
        pdf_pt = _widget_point_to_pdf(
            pos,
            self._page_w,
            self._page_h,
            self.width(),
            self.height(),
            self._rotation,
        )
        x, y = pdf_pt
        for link in self._links:
            x0, y0, x1, y1 = link.rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                return link
        return None

    def _text_in_selection(self) -> str:
        if (
            self._text_dict is None
            or self._sel_start is None
            or self._sel_end is None
        ):
            return ""
        ax = min(self._sel_start.x(), self._sel_end.x())
        ay = min(self._sel_start.y(), self._sel_end.y())
        bx = max(self._sel_start.x(), self._sel_end.x())
        by = max(self._sel_start.y(), self._sel_end.y())
        if bx - ax < 2 and by - ay < 2:
            return ""
        parts: list[str] = []
        for block in self._text_dict.get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines", []):
                line_bits: list[str] = []
                for span in line.get("spans", []):
                    bbox = span.get("bbox")
                    text = span.get("text") or ""
                    if not bbox or not text:
                        continue
                    wr = _map_pdf_rect_to_widget(
                        tuple(bbox),
                        self._page_w,
                        self._page_h,
                        self.width(),
                        self.height(),
                        self._rotation,
                    )
                    if wr.right() < ax or wr.left() > bx or wr.bottom() < ay or wr.top() > by:
                        continue
                    line_bits.append(text)
                if line_bits:
                    parts.append("".join(line_bits))
        return "\n".join(parts)


class _ViewerScrollArea(QScrollArea):
    def __init__(self, viewer: PdfViewerWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._viewer = viewer

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta != 0:
                step = ZOOM_WHEEL_STEP * max(
                    1, self._viewer.render_width_px // DEFAULT_THUMBNAIL_WIDTH
                )
                self._viewer.zoom_by(step if delta > 0 else -step)
                event.accept()
                return
        super().wheelEvent(event)


class PdfViewerWidget(QWidget):
    """Virtualized continuous / single / spread PDF viewer."""

    page_changed = pyqtSignal(int)
    closed = pyqtSignal()
    busy_changed = pyqtSignal(bool, str)
    status_message = pyqtSignal(str)
    render_error = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PdfViewer")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._model: PdfEditModel | None = None
        self._get_loader: Callable[[str], PdfLoader] | None = None
        self._layout = ViewerLayout.CONTINUOUS
        self._zoom_mode = ZoomMode.FIT_WIDTH
        self._zoom_percent = DEFAULT_ZOOM_PERCENT
        self._render_width_px = 800
        self._current_page = 0
        self._generation = 0
        self._search_generation = 0
        self._page_sizes: list[tuple[float, float]] = []  # unrotated points
        self._cache = _LruPixmapCache()
        self._tiles: dict[int, _PageTile] = {}
        self._pending_meta: set[int] = set()
        self._hits: list[SearchHit] = []
        self._hit_index = -1
        self._ocg_on: dict[str, frozenset[int]] = {}
        self._ocg_source: str | None = None

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(RENDER_DEBOUNCE_MS)
        self._render_timer.timeout.connect(self._render_visible)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._toolbar = self._build_toolbar()
        root.addWidget(self._toolbar)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._side = self._build_side_panel()
        self._splitter.addWidget(self._side)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self._scroll = _ViewerScrollArea(self)
        self._scroll.setObjectName("PdfViewerScroll")
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        self._canvas = QWidget()
        self._canvas.setObjectName("PdfViewerCanvas")
        # No layout — continuous mode virtualizes with absolute tile geometry;
        # single/spread place tiles the same way.
        self._scroll.setWidget(self._canvas)

        center_layout.addWidget(self._scroll, stretch=1)
        self._overlay = BusyOverlay(self._scroll.viewport())

        self._hint = QLabel(
            "PgUp/PgDn pages  ·  Ctrl+scroll zoom  ·  Ctrl+0 reset  ·  Esc back to grid"
        )
        self._hint.setObjectName("PdfViewerHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self._hint)

        self._splitter.addWidget(center)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([SIDE_PANEL_WIDTH, 800])
        root.addWidget(self._splitter, stretch=1)

    # --- public API ---------------------------------------------------------

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def render_width_px(self) -> int:
        return self._render_width_px

    @property
    def layout_mode(self) -> ViewerLayout:
        return self._layout

    @property
    def zoom_mode(self) -> ZoomMode:
        return self._zoom_mode

    @property
    def search_hit_count(self) -> int:
        return len(self._hits)

    def set_model(
        self,
        model: PdfEditModel | None,
        get_loader: Callable[[str], PdfLoader] | None,
    ) -> None:
        self._cancel_all()
        self._model = model
        self._get_loader = get_loader
        self._current_page = 0
        self._hits = []
        self._hit_index = -1
        self._cache.clear()
        self._clear_tiles()
        self._page_sizes = []
        self._ocg_on.clear()
        self._ocg_source = None
        self._search_edit.clear()
        self._hit_label.setText("")
        if model is None:
            self._outline.clear()
            self._layers.clear()
            self._attachments.clear()
            return
        self._load_page_sizes()
        self._refresh_side_panel()
        self._rebuild_canvas()
        self._update_render_width()
        self._schedule_render()

    def set_layout_mode(self, mode: ViewerLayout) -> None:
        if mode == self._layout:
            return
        self._cancel_all()
        self._layout = mode
        self._layout_continuous.setChecked(mode == ViewerLayout.CONTINUOUS)
        self._layout_single.setChecked(mode == ViewerLayout.SINGLE)
        self._layout_spread.setChecked(mode == ViewerLayout.SPREAD)
        self._rebuild_canvas()
        self._update_render_width()
        self._schedule_render()
        self.go_to_page(self._current_page)

    def set_zoom_mode(self, mode: ZoomMode, percent: int | None = None) -> None:
        self._zoom_mode = mode
        if percent is not None:
            self._zoom_percent = max(MIN_ZOOM_PERCENT, min(MAX_ZOOM_PERCENT, percent))
        self._cache.clear()
        self._update_render_width()
        self._rebuild_canvas()
        self._schedule_render()

    def reset_zoom(self) -> None:
        """Ctrl+0 — fit width."""
        self.set_zoom_mode(ZoomMode.FIT_WIDTH)

    def zoom_by(self, step_px: int) -> None:
        if self._model is None:
            return
        # Convert pixel step into percent mode from current width.
        base = max(self._fit_width_px(), 1)
        current_pct = int(round(100 * self._render_width_px / base))
        delta_pct = int(round(100 * step_px / base)) or (1 if step_px > 0 else -1)
        self.set_zoom_mode(ZoomMode.PERCENT, current_pct + delta_pct)

    def go_to_page(self, page_index: int) -> None:
        if self._model is None:
            return
        last = max(0, self._model.logical_count() - 1)
        page_index = max(0, min(page_index, last))
        changed = page_index != self._current_page
        self._current_page = page_index
        if self._layout != ViewerLayout.CONTINUOUS:
            self._rebuild_canvas()
            self._schedule_render()
        else:
            offsets = self._page_y_offsets()
            if page_index < len(offsets):
                self._scroll.verticalScrollBar().setValue(
                    max(0, offsets[page_index] - PAGE_GAP_PX)
                )
            self._sync_continuous_tiles()
            self._schedule_render()
        if changed:
            self.page_changed.emit(self._current_page)
        self._update_page_label()

    def search(self, query: str) -> None:
        if self._model is None:
            return
        query = query.strip()
        self._search_generation += 1
        gen = self._search_generation
        self._hits = []
        self._hit_index = -1
        self._apply_hits_to_tiles()
        if not query:
            self._hit_label.setText("")
            self.busy_changed.emit(False, "")
            return
        self._overlay.show_message("Searching…")
        self.busy_changed.emit(True, "Searching…")
        worker = _ViewerSearchWorker(self._model, query, gen, self._search_cancelled)
        worker.signals.finished.connect(self._on_search_finished)
        worker.signals.error.connect(self._on_search_error)
        self._pool.start(worker)

    def find_next(self) -> None:
        if not self._hits:
            return
        self._hit_index = (self._hit_index + 1) % len(self._hits)
        self._reveal_current_hit()

    def find_prev(self) -> None:
        if not self._hits:
            return
        self._hit_index = (self._hit_index - 1) % len(self._hits)
        self._reveal_current_hit()

    def copy_selection(self) -> bool:
        text = ""
        for tile in self._tiles.values():
            if tile.selected_text():
                text = tile.selected_text()
                break
        if not text:
            return False
        QGuiApplication.clipboard().setText(text)
        self.status_message.emit("Copied")
        return True

    def print_document(self) -> bool:
        """Banded raster print via QPrinter. Returns False if cancelled / blocked."""
        if self._model is None:
            return False
        count = self._model.logical_count()
        if count > MAX_PRINT_PAGES:
            QMessageBox.warning(
                self,
                "Print limit",
                f"This document has {count} pages. "
                f"Printing is limited to {MAX_PRINT_PAGES} pages in this version.",
            )
            return False

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False

        painter = QPainter(printer)
        try:
            for i, ref in enumerate(self._model.iter_pages()):
                if i > 0:
                    printer.newPage()
                # Banded: render at a bounded width, scale to page rect.
                width_px = min(1200, MAX_RENDER_WIDTH_PX)
                ocg = self._ocg_on.get(ref.source_path)
                png = render_ref_png(ref, width_px, ocg_on=ocg)
                pix = QPixmap()
                pix.loadFromData(png, "PNG")
                page_rect = printer.pageRect(QPrinter.Unit.DevicePixel).toRect()
                target = page_rect
                scaled = pix.scaled(
                    target.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = target.x() + (target.width() - scaled.width()) // 2
                y = target.y() + (target.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
        finally:
            painter.end()
        return True

    # --- UI construction ----------------------------------------------------

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("PdfViewerToolbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Find in document")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setAccessibleName("Find in document")
        self._search_edit.returnPressed.connect(self._on_search_submit)
        layout.addWidget(self._search_edit, stretch=1)

        prev_btn = QToolButton()
        prev_btn.setText("Prev")
        prev_btn.setToolTip("Previous result")
        prev_btn.setAccessibleName("Previous search result")
        prev_btn.clicked.connect(self.find_prev)
        layout.addWidget(prev_btn)

        next_btn = QToolButton()
        next_btn.setText("Next")
        next_btn.setToolTip("Next result")
        next_btn.setAccessibleName("Next search result")
        next_btn.clicked.connect(self.find_next)
        layout.addWidget(next_btn)

        self._hit_label = QLabel("")
        self._hit_label.setObjectName("PdfViewerHitLabel")
        self._hit_label.setAccessibleName("Search results")
        layout.addWidget(self._hit_label)

        self._page_label = QLabel("")
        self._page_label.setObjectName("PdfViewerPageLabel")
        layout.addWidget(self._page_label)

        self._layout_continuous = QToolButton()
        self._layout_continuous.setText("Continuous")
        self._layout_continuous.setCheckable(True)
        self._layout_continuous.setChecked(True)
        self._layout_continuous.clicked.connect(
            lambda: self.set_layout_mode(ViewerLayout.CONTINUOUS)
        )
        layout.addWidget(self._layout_continuous)

        self._layout_single = QToolButton()
        self._layout_single.setText("Single")
        self._layout_single.setCheckable(True)
        self._layout_single.clicked.connect(
            lambda: self.set_layout_mode(ViewerLayout.SINGLE)
        )
        layout.addWidget(self._layout_single)

        self._layout_spread = QToolButton()
        self._layout_spread.setText("Two-page")
        self._layout_spread.setCheckable(True)
        self._layout_spread.clicked.connect(
            lambda: self.set_layout_mode(ViewerLayout.SPREAD)
        )
        layout.addWidget(self._layout_spread)

        fit_w = QToolButton()
        fit_w.setText("Fit width")
        fit_w.clicked.connect(lambda: self.set_zoom_mode(ZoomMode.FIT_WIDTH))
        layout.addWidget(fit_w)

        fit_p = QToolButton()
        fit_p.setText("Fit page")
        fit_p.clicked.connect(lambda: self.set_zoom_mode(ZoomMode.FIT_PAGE))
        layout.addWidget(fit_p)

        print_btn = QToolButton()
        print_btn.setText("Print")
        print_btn.setAccessibleName("Print")
        print_btn.clicked.connect(self.print_document)
        layout.addWidget(print_btn)

        return bar

    def _build_side_panel(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("PdfViewerSide")
        tabs.setMinimumWidth(160)

        self._outline = QTreeWidget()
        self._outline.setHeaderHidden(True)
        self._outline.setAccessibleName("Bookmarks")
        self._outline.itemActivated.connect(self._on_outline_activated)
        self._outline.itemClicked.connect(self._on_outline_activated)
        tabs.addTab(self._outline, "Bookmarks")

        layers_host = QWidget()
        layers_layout = QVBoxLayout(layers_host)
        layers_layout.setContentsMargins(4, 4, 4, 4)
        self._layers = QListWidget()
        self._layers.setAccessibleName("Layers")
        layers_layout.addWidget(self._layers)
        tabs.addTab(layers_host, "Layers")

        att_host = QWidget()
        att_layout = QVBoxLayout(att_host)
        att_layout.setContentsMargins(4, 4, 4, 4)
        self._attachments = QListWidget()
        self._attachments.setAccessibleName("Attachments")
        att_layout.addWidget(self._attachments)
        extract_btn = QPushButton("Extract to folder…")
        extract_btn.setObjectName("ToolbarSecondary")
        extract_btn.clicked.connect(self._extract_selected_attachment)
        att_layout.addWidget(extract_btn)
        tabs.addTab(att_host, "Attachments")

        return tabs

    # --- model / layout -----------------------------------------------------

    def _load_page_sizes(self) -> None:
        assert self._model is not None
        sizes: list[tuple[float, float]] = []
        for ref in self._model.iter_pages():
            try:
                geom = page_geometry(ref.source_path, ref.source_index)
                sizes.append((geom.width, geom.height))
            except Exception:
                sizes.append((612.0, 792.0))
        self._page_sizes = sizes

    def _refresh_side_panel(self) -> None:
        assert self._model is not None
        paths = sorted(self._model.source_paths())
        self._outline.clear()
        try:
            items = outline_for_paths(paths)
        except Exception:
            items = []
        parents: dict[int, QTreeWidgetItem] = {}
        for item in items:
            node = QTreeWidgetItem([item.title])
            node.setData(
                0,
                Qt.ItemDataRole.UserRole,
                (item.source_path, item.source_index),
            )
            parent = parents.get(item.level - 1)
            if parent is None or item.level <= 1:
                self._outline.addTopLevelItem(node)
            else:
                parent.addChild(node)
            parents[item.level] = node
        self._outline.expandToDepth(1)

        self._layers.clear()
        self._ocg_source = self._model.original_path
        try:
            layer_infos = layers_for_path(self._ocg_source)
        except Exception:
            layer_infos = []
        visible = {layer.number for layer in layer_infos if layer.visible}
        self._ocg_on[self._ocg_source] = frozenset(visible)
        for layer in layer_infos:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)
            check = QCheckBox(layer.name)
            check.setChecked(layer.visible)
            check.setAccessibleName(f"Layer {layer.name}")
            check.toggled.connect(
                lambda on, n=layer.number: self._toggle_layer(n, on)
            )
            row_layout.addWidget(check)
            list_item = QListWidgetItem()
            list_item.setSizeHint(row.sizeHint())
            self._layers.addItem(list_item)
            self._layers.setItemWidget(list_item, row)

        self._attachments.clear()
        try:
            atts = attachments_for_path(self._model.original_path)
        except Exception:
            atts = []
        for att in atts:
            label = f"{att.name} ({att.size} bytes)" if att.size else att.name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, att)
            self._attachments.addItem(item)

    def _toggle_layer(self, number: int, on: bool) -> None:
        if self._ocg_source is None:
            return
        current = set(self._ocg_on.get(self._ocg_source, frozenset()))
        if on:
            current.add(number)
        else:
            current.discard(number)
        self._ocg_on[self._ocg_source] = frozenset(current)
        self._cache.clear()
        self._schedule_render()

    def _clear_tiles(self) -> None:
        for tile in list(self._tiles.values()):
            tile.hide()
            tile.setParent(None)
            tile.deleteLater()
        self._tiles.clear()
        self._pending_meta.clear()

    def _pages_to_show(self) -> list[int]:
        if self._model is None:
            return []
        n = self._model.logical_count()
        if n == 0:
            return []
        if self._layout == ViewerLayout.CONTINUOUS:
            return list(range(n))
        if self._layout == ViewerLayout.SINGLE:
            return [self._current_page]
        left = self._current_page - (self._current_page % 2)
        pages = [left]
        if left + 1 < n:
            pages.append(left + 1)
        return pages

    def _page_y_offsets(self) -> list[int]:
        """Top Y of each logical page in continuous canvas coordinates."""
        offsets: list[int] = []
        y = PAGE_GAP_PX
        count = len(self._page_sizes) if self._model else 0
        for i in range(count):
            offsets.append(y)
            _w, h = self._display_size_for(i)
            y += h + PAGE_GAP_PX
        return offsets

    def _continuous_canvas_height(self) -> int:
        if not self._page_sizes:
            return 400
        offsets = self._page_y_offsets()
        last = len(offsets) - 1
        _w, h = self._display_size_for(last)
        return offsets[last] + h + PAGE_GAP_PX

    def _rebuild_canvas(self) -> None:
        self._clear_tiles()
        if self._model is None:
            self._canvas.setMinimumSize(0, 0)
            self._canvas.resize(0, 0)
            return
        if self._layout == ViewerLayout.CONTINUOUS:
            width = self._render_width_px + 2 * PAGE_GAP_PX
            height = self._continuous_canvas_height()
            self._canvas.setMinimumSize(width, height)
            self._canvas.resize(width, height)
            self._sync_continuous_tiles()
            return
        pages = self._pages_to_show()
        if self._layout == ViewerLayout.SPREAD and len(pages) == 2:
            sizes = [self._display_size_for(p) for p in pages]
            total_w = sizes[0][0] + sizes[1][0] + 3 * PAGE_GAP_PX
            total_h = max(sizes[0][1], sizes[1][1]) + 2 * PAGE_GAP_PX
            self._canvas.setMinimumSize(total_w, total_h)
            self._canvas.resize(total_w, total_h)
            x = PAGE_GAP_PX
            for p, (w, h) in zip(pages, sizes):
                tile = self._make_tile(p)
                tile.setParent(self._canvas)
                tile.setGeometry(x, PAGE_GAP_PX, w, h)
                tile.show()
                x += w + PAGE_GAP_PX
            return
        # single
        w, h = self._display_size_for(pages[0])
        total_w = w + 2 * PAGE_GAP_PX
        total_h = h + 2 * PAGE_GAP_PX
        self._canvas.setMinimumSize(total_w, total_h)
        self._canvas.resize(total_w, total_h)
        tile = self._make_tile(pages[0])
        tile.setParent(self._canvas)
        tile.setGeometry(PAGE_GAP_PX, PAGE_GAP_PX, w, h)
        tile.show()

    def _sync_continuous_tiles(self) -> None:
        """Create/destroy continuous-mode tiles for the visible band (+ prefetch)."""
        if self._model is None or self._layout != ViewerLayout.CONTINUOUS:
            return
        n = self._model.logical_count()
        if n == 0:
            return
        offsets = self._page_y_offsets()
        viewport = self._scroll.viewport().rect()
        top = self._canvas.mapFrom(self._scroll.viewport(), viewport.topLeft()).y()
        bottom = self._canvas.mapFrom(
            self._scroll.viewport(), viewport.bottomRight()
        ).y()
        pad = max(viewport.height(), 400)
        top -= pad
        bottom += pad
        needed: set[int] = set()
        for i, y in enumerate(offsets):
            _w, h = self._display_size_for(i)
            if y + h < top or y > bottom:
                continue
            needed.add(i)
        for logical in list(self._tiles):
            if logical not in needed:
                tile = self._tiles.pop(logical)
                tile.setParent(None)
                tile.deleteLater()
                self._pending_meta.discard(logical)
        canvas_w = max(self._canvas.width(), self._render_width_px + 2 * PAGE_GAP_PX)
        for logical in needed:
            w, h = self._display_size_for(logical)
            x = max(PAGE_GAP_PX, (canvas_w - w) // 2)
            y = offsets[logical]
            tile = self._tiles.get(logical)
            if tile is None:
                tile = self._make_tile(logical)
                tile.setParent(self._canvas)
                tile.show()
            tile.setGeometry(x, y, w, h)
        height = self._continuous_canvas_height()
        self._canvas.setMinimumSize(canvas_w, height)
        self._canvas.resize(canvas_w, height)

    def _make_tile(self, logical: int) -> _PageTile:
        tile = _PageTile(logical)
        tile.link_activated.connect(self._on_link)
        self._tiles[logical] = tile
        self._pending_meta.add(logical)
        return tile

    def _display_size_for(self, logical: int) -> tuple[int, int]:
        if logical >= len(self._page_sizes) or self._model is None:
            return self._render_width_px, int(self._render_width_px * 1.4)
        ref = self._model.page_at(logical)
        pw, ph = self._page_sizes[logical]
        dw, dh = _rotated_size(pw, ph, ref.rotation)
        width = self._render_width_px
        if self._layout == ViewerLayout.SPREAD:
            width = max(MIN_PREVIEW_RENDER_WIDTH // 2, width // 2 - PAGE_GAP_PX // 2)
        height = max(1, int(round(width * (dh / dw)))) if dw else width
        return width, height

    def _relayout_tile_sizes(self) -> None:
        if self._layout == ViewerLayout.CONTINUOUS:
            self._sync_continuous_tiles()
            return
        pages = sorted(self._tiles)
        if not pages:
            return
        if self._layout == ViewerLayout.SPREAD and len(pages) >= 2:
            sizes = [self._display_size_for(p) for p in pages[:2]]
            total_w = sizes[0][0] + sizes[1][0] + 3 * PAGE_GAP_PX
            total_h = max(sizes[0][1], sizes[1][1]) + 2 * PAGE_GAP_PX
            self._canvas.setMinimumSize(total_w, total_h)
            self._canvas.resize(total_w, total_h)
            x = PAGE_GAP_PX
            for p, (w, h) in zip(pages[:2], sizes):
                tile = self._tiles[p]
                tile.setGeometry(x, PAGE_GAP_PX, w, h)
                x += w + PAGE_GAP_PX
            return
        p = pages[0]
        w, h = self._display_size_for(p)
        total_w = w + 2 * PAGE_GAP_PX
        total_h = h + 2 * PAGE_GAP_PX
        self._canvas.setMinimumSize(total_w, total_h)
        self._canvas.resize(total_w, total_h)
        self._tiles[p].setGeometry(PAGE_GAP_PX, PAGE_GAP_PX, w, h)

    def _fit_width_px(self) -> int:
        viewport = self._scroll.viewport()
        available = max(viewport.width() - 2 * PAGE_GAP_PX - 24, MIN_PREVIEW_RENDER_WIDTH)
        if self._layout == ViewerLayout.SPREAD:
            available = max(MIN_PREVIEW_RENDER_WIDTH, (available - PAGE_GAP_PX) // 2 * 2)
        return min(MAX_RENDER_WIDTH_PX, available)

    def _fit_page_px(self) -> int:
        if self._model is None or not self._page_sizes:
            return self._fit_width_px()
        logical = self._current_page
        ref = self._model.page_at(logical)
        pw, ph = self._page_sizes[min(logical, len(self._page_sizes) - 1)]
        dw, dh = _rotated_size(pw, ph, ref.rotation)
        viewport = self._scroll.viewport()
        avail_w = max(viewport.width() - 2 * PAGE_GAP_PX - 24, MIN_PREVIEW_RENDER_WIDTH)
        avail_h = max(viewport.height() - 2 * PAGE_GAP_PX - 24, 200)
        if self._layout == ViewerLayout.SPREAD:
            avail_w = max(100, (avail_w - PAGE_GAP_PX) // 2)
        if dh <= 0 or dw <= 0:
            return self._fit_width_px()
        by_w = avail_w
        by_h = avail_h * (dw / dh)
        return min(MAX_RENDER_WIDTH_PX, max(MIN_PREVIEW_RENDER_WIDTH, int(min(by_w, by_h))))

    def _update_render_width(self) -> None:
        if self._zoom_mode == ZoomMode.FIT_WIDTH:
            self._render_width_px = self._fit_width_px()
        elif self._zoom_mode == ZoomMode.FIT_PAGE:
            self._render_width_px = self._fit_page_px()
        else:
            base = self._fit_width_px()
            self._render_width_px = max(
                MIN_PREVIEW_RENDER_WIDTH,
                min(
                    MAX_RENDER_WIDTH_PX,
                    int(round(base * self._zoom_percent / 100)),
                ),
            )
        self._relayout_tile_sizes()

    # --- rendering ----------------------------------------------------------

    def _schedule_render(self) -> None:
        if self._model is None:
            return
        self._render_timer.start()

    def _visible_pages(self) -> list[int]:
        if self._layout != ViewerLayout.CONTINUOUS:
            return self._pages_to_show()
        if self._tiles:
            return sorted(self._tiles)
        return [self._current_page] if self._model else []

    def _render_visible(self) -> None:
        if self._model is None:
            return
        self._update_render_width()
        if self._layout == ViewerLayout.CONTINUOUS:
            self._sync_continuous_tiles()
        pages = self._visible_pages()
        self._load_meta_for(pages)
        self._generation += 1
        gen = self._generation
        started = False
        for logical in pages:
            width, _h = self._display_size_for(logical)
            ref = self._model.page_at(logical)
            ocg = self._ocg_on.get(ref.source_path)
            key = (logical, width, ref.rotation, ocg)
            cached = self._cache.get(key)
            tile = self._tiles.get(logical)
            if cached is not None:
                if tile is not None:
                    tile.set_pixmap(cached)
                continue
            started = True
            worker = _ViewerRenderWorker(
                ref, logical, width, gen, self._is_cancelled, ocg
            )
            worker.signals.finished.connect(self._on_render_finished)
            worker.signals.error.connect(self._on_render_error)
            self._pool.start(worker)
        if started:
            self._overlay.show_message("Rendering…")
            self.busy_changed.emit(True, "Rendering…")
        else:
            self._overlay.hide_overlay()
            self.busy_changed.emit(False, "")
        self._apply_hits_to_tiles()
        self._update_page_label()

    def _load_meta_for(self, pages: list[int]) -> None:
        if self._model is None:
            return
        for logical in pages:
            if logical not in self._pending_meta:
                continue
            ref = self._model.page_at(logical)
            pw, ph = (
                self._page_sizes[logical]
                if logical < len(self._page_sizes)
                else (612.0, 792.0)
            )
            try:
                links = page_links(ref)
            except Exception:
                links = []
            try:
                text = page_text_dict(ref)
            except Exception:
                text = None
            tile = self._tiles.get(logical)
            if tile is not None:
                tile.set_page_meta(pw, ph, ref.rotation, links, text)
            self._pending_meta.discard(logical)

    def _on_render_finished(
        self, generation: int, logical: int, width_px: int, png: bytes
    ) -> None:
        if self._is_cancelled(generation) or self._model is None:
            return
        ref = self._model.page_at(logical)
        ocg = self._ocg_on.get(ref.source_path)
        expected_w, _ = self._display_size_for(logical)
        if width_px != expected_w:
            return
        pix = QPixmap()
        pix.loadFromData(png, "PNG")
        key = (logical, width_px, ref.rotation, ocg)
        self._cache.put(key, pix)
        tile = self._tiles.get(logical)
        if tile is not None:
            tile.set_pixmap(pix)
        if self._pool.activeThreadCount() == 0:
            self._overlay.hide_overlay()
            self.busy_changed.emit(False, "")

    def _on_render_error(self, generation: int, logical: int, message: str) -> None:
        if self._is_cancelled(generation):
            return
        self._overlay.hide_overlay()
        self.busy_changed.emit(False, "")
        tile = self._tiles.get(logical)
        if tile is not None:
            tile.set_pixmap(None)
        self.render_error.emit(message)

    def _is_cancelled(self, generation: int) -> bool:
        return generation != self._generation

    def _search_cancelled(self, generation: int) -> bool:
        return generation != self._search_generation

    def _cancel_all(self) -> None:
        self._render_timer.stop()
        self._generation += 1
        self._search_generation += 1
        self._overlay.hide_overlay()
        self.busy_changed.emit(False, "")

    # --- search / navigation / links ----------------------------------------

    def _on_search_submit(self) -> None:
        self.search(self._search_edit.text())

    def _on_search_finished(self, generation: int, hits: object) -> None:
        if self._search_cancelled(generation):
            return
        self._overlay.hide_overlay()
        self.busy_changed.emit(False, "")
        self._hits = list(hits) if isinstance(hits, list) else []
        self._hit_index = 0 if self._hits else -1
        n = len(self._hits)
        self._hit_label.setText(f"{n} result{'s' if n != 1 else ''}" if n else "No results")
        self._hit_label.setAccessibleName(
            f"{n} search results" if n else "No search results"
        )
        self._apply_hits_to_tiles()
        if self._hits:
            self._reveal_current_hit()

    def _on_search_error(self, generation: int, message: str) -> None:
        if self._search_cancelled(generation):
            return
        self._overlay.hide_overlay()
        self.busy_changed.emit(False, "")
        self._hit_label.setText("Search failed")
        self.render_error.emit(message)

    def _apply_hits_to_tiles(self) -> None:
        by_page: dict[int, list[tuple[float, float, float, float]]] = {}
        for hit in self._hits:
            by_page.setdefault(hit.logical_page, []).append(hit.rect)
        for logical, tile in self._tiles.items():
            tile.set_hits(by_page.get(logical, []))

    def _reveal_current_hit(self) -> None:
        if self._hit_index < 0 or self._hit_index >= len(self._hits):
            return
        hit = self._hits[self._hit_index]
        self.go_to_page(hit.logical_page)
        self._hit_label.setText(
            f"{self._hit_index + 1} of {len(self._hits)}"
        )

    def _on_outline_activated(self, item: QTreeWidgetItem) -> None:
        if self._model is None or item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        source_path, source_index = data
        logical = logical_index_for_source(self._model, source_path, source_index)
        if logical is not None:
            self.go_to_page(logical)

    def _on_link(self, logical_page: int, link: object) -> None:
        if not isinstance(link, LinkInfo) or self._model is None:
            return
        if link.kind == "goto" and link.page is not None:
            ref = self._model.page_at(logical_page)
            logical = logical_index_for_source(
                self._model, ref.source_path, link.page
            )
            if logical is not None:
                self.go_to_page(logical)
            return
        if link.kind == "uri" and link.uri:
            reply = QMessageBox.question(
                self,
                "Open link",
                f"Open this link in your browser?\n\n{link.uri}",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Open:
                QDesktopServices.openUrl(QUrl(link.uri))

    def _extract_selected_attachment(self) -> None:
        if self._model is None:
            return
        item = self._attachments.currentItem()
        if item is None:
            self.status_message.emit("Select an attachment first")
            return
        att = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(att, AttachmentInfo):
            return
        folder = QFileDialog.getExistingDirectory(self, "Extract attachment to folder")
        if not folder:
            return
        try:
            out = extract_attachment(att.source_path, att.name, folder)
        except Exception as exc:
            QMessageBox.warning(self, "Extract failed", str(exc))
            return
        self.status_message.emit(f"Saved {out.name}")

    def _on_scroll(self, _value: int = 0) -> None:
        if self._layout != ViewerLayout.CONTINUOUS or self._model is None:
            return
        self._sync_continuous_tiles()
        # Update current page from the top-most visible tile.
        viewport = self._scroll.viewport().rect()
        anchor = self._canvas.mapFrom(
            self._scroll.viewport(), viewport.center()
        )
        best = self._current_page
        best_dist = math.inf
        for logical, tile in self._tiles.items():
            dist = abs(tile.geometry().center().y() - anchor.y())
            if dist < best_dist:
                best_dist = dist
                best = logical
        if best != self._current_page:
            self._current_page = best
            self.page_changed.emit(best)
            self._update_page_label()
        self._schedule_render()

    def _update_page_label(self) -> None:
        if self._model is None:
            self._page_label.setText("")
            return
        total = self._model.logical_count()
        self._page_label.setText(f"Page {self._current_page + 1} of {total}")
        self._page_label.setAccessibleName(
            f"Page {self._current_page + 1} of {total}"
        )

    # --- events -------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._model is not None:
            self._update_render_width()
            self._schedule_render()
        self.setFocus()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._overlay._sync_geometry()
        if self.isVisible() and self._model is not None:
            previous = self._render_width_px
            self._update_render_width()
            if self._render_width_px != previous and self._zoom_mode != ZoomMode.PERCENT:
                self._cache.clear()
                self._rebuild_canvas()
                self._schedule_render()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Escape:
            self.closed.emit()
            event.accept()
            return
        if key == Qt.Key.Key_0 and mods & Qt.KeyboardModifier.ControlModifier:
            self.reset_zoom()
            event.accept()
            return
        if key == Qt.Key.Key_C and mods & Qt.KeyboardModifier.ControlModifier:
            if self.copy_selection():
                event.accept()
                return
        if key == Qt.Key.Key_F and mods & Qt.KeyboardModifier.ControlModifier:
            self._search_edit.setFocus()
            self._search_edit.selectAll()
            event.accept()
            return
        if key == Qt.Key.Key_G and mods & Qt.KeyboardModifier.ControlModifier:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self.find_prev()
            else:
                self.find_next()
            event.accept()
            return
        if key in (Qt.Key.Key_PageDown, Qt.Key.Key_Down, Qt.Key.Key_Right, Qt.Key.Key_Space):
            self.go_to_page(self._current_page + (2 if self._layout == ViewerLayout.SPREAD else 1))
            event.accept()
            return
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_Up, Qt.Key.Key_Left, Qt.Key.Key_Backspace):
            self.go_to_page(self._current_page - (2 if self._layout == ViewerLayout.SPREAD else 1))
            event.accept()
            return
        if key == Qt.Key.Key_Home:
            self.go_to_page(0)
            event.accept()
            return
        if key == Qt.Key.Key_End and self._model is not None:
            self.go_to_page(self._model.logical_count() - 1)
            event.accept()
            return
        super().keyPressEvent(event)
