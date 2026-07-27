"""Full PDF viewer — virtualized read/navigate over ``PdfEditModel``.

Zoom, search, select/copy, links, outline, layers, attachments, print, plus
Phase 30 annotation / AcroForm authoring overlays (applied on Save As).
Renders go through ``pagedrop.core.pdf_service`` (shared fitz lock), not ad-hoc
concurrent pools.
"""

from __future__ import annotations

import bisect
import math
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Literal

from PyQt6.QtCore import (
    QEvent,
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
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.annotations import (
    MOVABLE_ANNOT_KINDS,
    AnnotationOp,
    STAMP_APPROVED,
)
from pagedrop.core.forms import FormCreateOp
from pagedrop.core.markup import MarkupEntry, MarkupSession
from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.redact import (
    RedactionRegion,
    RedactionScope,
    RedactionVerifyError,
    redact_edit_model,
)
from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX, PdfLoader
from pagedrop.core.pdf_service import (
    MAX_PRINT_PAGES,
    AttachmentInfo,
    LinkInfo,
    SearchHit,
    WidgetInfo,
    attachments_for_path,
    extract_attachment,
    layers_for_path,
    logical_index_for_source,
    outline_for_paths,
    page_geometry,
    page_links,
    page_text_dict,
    page_widgets,
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
ANNOT_RAIL_WIDTH = 120
ANNOT_RAIL_COLLAPSED = 28
CACHE_MAX_PIXMAPS = 48
RENDER_DEBOUNCE_MS = 80
DEFAULT_ZOOM_PERCENT = 100
MIN_ZOOM_PERCENT = 25
MAX_ZOOM_PERCENT = 400
# Thin horizontal sweeps still catch a text line.
_TEXT_MARKUP_Y_PAD_PX = 6.0
_DEFAULT_FREETEXT_COLOR = (0.1, 0.1, 0.1)
_DEFAULT_FREETEXT_SIZE = 12.0
_DEFAULT_MARKUP_COLOR = (1.0, 0.92, 0.23)
_HANDLE_PX = 7.0
_MIN_BOX_PDF = 16.0
_IMAGE_FILTERS = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All files (*)"


class ViewerLayout(str, Enum):
    CONTINUOUS = "continuous"
    SINGLE = "single"
    SPREAD = "spread"


class ZoomMode(str, Enum):
    FIT_WIDTH = "fit_width"
    FIT_PAGE = "fit_page"
    PERCENT = "percent"


class AnnotTool(str, Enum):
    SELECT = "select"
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    INK = "ink"
    RECT = "rect"
    CIRCLE = "circle"
    LINE = "line"
    STAMP = "stamp"
    FREETEXT = "freetext"
    IMAGE = "image"
    COMMENT = "comment"
    REDACT = "redact"
    FORM_FILL = "form_fill"
    FORM_TEXT = "form_text"
    FORM_CHECK = "form_check"


# Shared by the right rail and the page context menu.
ANNOT_TOOL_ITEMS: tuple[tuple[str, AnnotTool], ...] = (
    ("Select", AnnotTool.SELECT),
    ("Highlight", AnnotTool.HIGHLIGHT),
    ("Underline", AnnotTool.UNDERLINE),
    ("Strikeout", AnnotTool.STRIKEOUT),
    ("Ink", AnnotTool.INK),
    ("Rect", AnnotTool.RECT),
    ("Circle", AnnotTool.CIRCLE),
    ("Line", AnnotTool.LINE),
    ("Stamp", AnnotTool.STAMP),
    ("Text", AnnotTool.FREETEXT),
    ("Image", AnnotTool.IMAGE),
    ("Comment", AnnotTool.COMMENT),
    ("Redact", AnnotTool.REDACT),
    ("Fill", AnnotTool.FORM_FILL),
    ("Field", AnnotTool.FORM_TEXT),
    ("Check", AnnotTool.FORM_CHECK),
)

_TEXT_MARKUP_TOOLS = frozenset(
    {AnnotTool.HIGHLIGHT, AnnotTool.UNDERLINE, AnnotTool.STRIKEOUT}
)

_HANDLE_CURSORS: dict[str, Qt.CursorShape] = {
    "nw": Qt.CursorShape.SizeFDiagCursor,
    "se": Qt.CursorShape.SizeFDiagCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor,
    "sw": Qt.CursorShape.SizeBDiagCursor,
    "n": Qt.CursorShape.SizeVerCursor,
    "s": Qt.CursorShape.SizeVerCursor,
    "e": Qt.CursorShape.SizeHorCursor,
    "w": Qt.CursorShape.SizeHorCursor,
    "move": Qt.CursorShape.SizeAllCursor,
}


def _prompt_freetext(
    parent: QWidget,
    *,
    text: str = "",
    fontsize: float = _DEFAULT_FREETEXT_SIZE,
    color: tuple[float, float, float] = _DEFAULT_FREETEXT_COLOR,
    border: bool = False,
    title: str = "Free text",
    allow_delete: bool = False,
) -> tuple[str, float, tuple[float, float, float], bool] | Literal["delete"] | None:
    """Edit free-text content, size, color, border. Returns None on cancel."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    edit = QPlainTextEdit()
    edit.setPlainText(text)
    edit.setMinimumHeight(80)
    form.addRow("Text", edit)
    size = QDoubleSpinBox()
    size.setRange(6.0, 96.0)
    size.setDecimals(1)
    size.setValue(fontsize)
    form.addRow("Font size", size)
    rgb = [max(0, min(255, int(c * 255))) for c in color]
    color_btn = QPushButton()
    color_btn.setObjectName("FreeTextColorButton")

    def _apply_swatch() -> None:
        color_btn.setStyleSheet(
            f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]}); min-width: 48px;"
        )

    def _pick_color() -> None:
        chosen = QColorDialog.getColor(QColor(*rgb), dialog, "Text color")
        if chosen.isValid():
            rgb[0], rgb[1], rgb[2] = chosen.red(), chosen.green(), chosen.blue()
            _apply_swatch()

    _apply_swatch()
    color_btn.clicked.connect(_pick_color)
    form.addRow("Color", color_btn)
    border_cb = QCheckBox("Show border")
    border_cb.setChecked(border)
    form.addRow("", border_cb)
    layout.addLayout(form)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    deleted = {"value": False}

    def _on_delete() -> None:
        deleted["value"] = True
        dialog.accept()

    if allow_delete:
        delete_btn = buttons.addButton(
            "Delete", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        delete_btn.clicked.connect(_on_delete)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    if deleted["value"]:
        return "delete"
    body = edit.toPlainText().strip()
    if not body:
        return None
    return (
        body,
        float(size.value()),
        (rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0),
        border_cb.isChecked(),
    )


def _apply_box_transform(
    rect: tuple[float, float, float, float],
    mode: str,
    dx: float,
    dy: float,
    *,
    min_size: float = _MIN_BOX_PDF,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = rect
    if mode == "move":
        return (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
    if "w" in mode:
        x0 = min(x0 + dx, x1 - min_size)
    if "e" in mode:
        x1 = max(x1 + dx, x0 + min_size)
    if "n" in mode:
        y0 = min(y0 + dy, y1 - min_size)
    if "s" in mode:
        y1 = max(y1 + dy, y0 + min_size)
    return (x0, y0, x1, y1)


def _hit_resize_handle(wr: QRectF, pos: QPointF, handle_px: float = _HANDLE_PX) -> str | None:
    """Return handle id (nw/n/ne/…) or None if not on a handle."""
    x, y = pos.x(), pos.y()
    left, right = wr.left(), wr.right()
    top, bottom = wr.top(), wr.bottom()
    on_l = abs(x - left) <= handle_px
    on_r = abs(x - right) <= handle_px
    on_t = abs(y - top) <= handle_px
    on_b = abs(y - bottom) <= handle_px
    in_x = left - handle_px <= x <= right + handle_px
    in_y = top - handle_px <= y <= bottom + handle_px
    if on_t and on_l:
        return "nw"
    if on_t and on_r:
        return "ne"
    if on_b and on_l:
        return "sw"
    if on_b and on_r:
        return "se"
    if on_t and in_x:
        return "n"
    if on_b and in_x:
        return "s"
    if on_l and in_y:
        return "w"
    if on_r and in_y:
        return "e"
    return None


def _paint_resize_handles(painter: QPainter, wr: QRectF) -> None:
    # Outline only — never fill the box (that painted an opaque white cover).
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(47, 155, 230), 1, Qt.PenStyle.DashLine))
    painter.drawRect(wr)
    hs = _HANDLE_PX
    mid_x = wr.center().x()
    mid_y = wr.center().y()
    points = (
        (wr.left(), wr.top()),
        (mid_x, wr.top()),
        (wr.right(), wr.top()),
        (wr.right(), mid_y),
        (wr.right(), wr.bottom()),
        (mid_x, wr.bottom()),
        (wr.left(), wr.bottom()),
        (wr.left(), mid_y),
    )
    painter.setBrush(QColor(255, 255, 255))
    painter.setPen(QPen(QColor(47, 155, 230), 1))
    for px, py in points:
        painter.drawRect(QRectF(px - hs / 2, py - hs / 2, hs, hs))


def _merge_char_rects(
    chars: list[tuple[float, float, float, float]],
) -> tuple[tuple[float, float, float, float], ...]:
    """Merge adjacent character boxes on the same baseline into line fragments."""
    if not chars:
        return ()
    # Sort top-to-bottom, then left-to-right.
    ordered = sorted(chars, key=lambda r: (round(r[1], 1), r[0]))
    merged: list[list[float]] = []
    for x0, y0, x1, y1 in ordered:
        if not merged:
            merged.append([x0, y0, x1, y1])
            continue
        cur = merged[-1]
        same_line = abs(y0 - cur[1]) < 2.0 and abs(y1 - cur[3]) < 2.0
        gap = x0 - cur[2]
        if same_line and gap <= max(3.0, (cur[3] - cur[1]) * 0.35):
            cur[2] = max(cur[2], x1)
            cur[1] = min(cur[1], y0)
            cur[3] = max(cur[3], y1)
        else:
            merged.append([x0, y0, x1, y1])
    return tuple((a, b, c, d) for a, b, c, d in merged)


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
    """One visible page surface — pixmap, search highlights, selection, links, markup."""

    link_activated = pyqtSignal(int, object)  # logical_page, LinkInfo
    selection_changed = pyqtSignal()
    markup_gesture = pyqtSignal(int, str, object)  # logical, tool value, payload
    form_field_activated = pyqtSignal(int, object)  # logical, WidgetInfo
    context_menu_requested = pyqtSignal(object)  # global QPoint

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
        self._widgets: list[WidgetInfo] = []
        self._hits: list[tuple[float, float, float, float]] = []
        self._active_hit: tuple[float, float, float, float] | None = None
        self._text_dict: dict | None = None
        self._text_provider: Callable[[], dict | None] | None = None
        self._tool = AnnotTool.SELECT
        self._overlay_entries: list[MarkupEntry] = []
        self._markup_color = _DEFAULT_MARKUP_COLOR
        self._selected_op: AnnotationOp | None = None
        self._transform_mode: str | None = None
        self._transform_origin: AnnotationOp | None = None
        self._transform_start_pdf: tuple[float, float] | None = None
        self._transform_start_rect: tuple[float, float, float, float] | None = None
        self._live_rect: tuple[float, float, float, float] | None = None
        self._image_pixmaps: dict[str, QPixmap] = {}
        self._selecting = False
        self._drawing = False
        self._ink_points: list[tuple[float, float]] = []
        self._sel_start: QPointF | None = None
        self._sel_end: QPointF | None = None
        self._selected_text = ""
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context_menu)

    def _emit_context_menu(self, pos) -> None:
        self.context_menu_requested.emit(self.mapToGlobal(pos))

    def set_tool(self, tool: AnnotTool) -> None:
        self._tool = tool
        self._update_cursor()

    def set_markup_color(self, color: tuple[float, float, float]) -> None:
        self._markup_color = color
        self.update()

    def set_selected_op(self, op: AnnotationOp | None) -> None:
        self._selected_op = op
        self._live_rect = None
        self.update()

    def set_overlay_entries(self, entries: list[MarkupEntry]) -> None:
        self._overlay_entries = entries
        if self._selected_op is not None:
            if not any(
                e.kind == "annotation" and e.annotation == self._selected_op
                for e in entries
            ):
                self._selected_op = None
        self.update()

    def set_page_meta(
        self,
        page_w: float,
        page_h: float,
        rotation: int,
        links: list[LinkInfo],
        text_dict: dict | None = None,
        *,
        text_provider: Callable[[], dict | None] | None = None,
        widgets: list[WidgetInfo] | None = None,
    ) -> None:
        self._page_w = page_w
        self._page_h = page_h
        self._rotation = rotation
        self._links = links
        self._widgets = widgets or []
        self._text_dict = text_dict
        self._text_provider = text_provider
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def set_hits(
        self,
        hits: list[tuple[float, float, float, float]],
        *,
        active: tuple[float, float, float, float] | None = None,
    ) -> None:
        self._hits = hits
        self._active_hit = active
        self.update()

    def selected_text(self) -> str:
        return self._selected_text

    def clear_selection(self) -> None:
        self._selecting = False
        self._drawing = False
        self._ink_points = []
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
                target = self.rect()
                if (
                    pix.devicePixelRatio() > 0
                    and abs(pix.width() / pix.devicePixelRatio() - target.width()) < 1.5
                    and abs(pix.height() / pix.devicePixelRatio() - target.height()) < 1.5
                ):
                    painter.drawPixmap(0, 0, pix)
                else:
                    painter.drawPixmap(
                        target,
                        pix,
                        QRectF(0, 0, pix.width(), pix.height()),
                    )
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
                if hit == self._active_hit:
                    painter.fillRect(r, QColor(255, 145, 0, 170))
                    painter.setPen(QColor(200, 90, 0, 220))
                    painter.drawRect(r)
                else:
                    painter.fillRect(r, QColor(255, 220, 0, 90))

            self._paint_markup_overlays(painter)

            if self._tool == AnnotTool.FORM_FILL:
                for widget in self._widgets:
                    wr = _map_pdf_rect_to_widget(
                        widget.rect,
                        self._page_w,
                        self._page_h,
                        self.width(),
                        self.height(),
                        self._rotation,
                    )
                    painter.setPen(QPen(QColor(47, 155, 230, 180), 1, Qt.PenStyle.DashLine))
                    painter.fillRect(wr, QColor(47, 155, 230, 30))
                    painter.drawRect(wr)

            if self._sel_start is not None and self._sel_end is not None:
                x0 = min(self._sel_start.x(), self._sel_end.x())
                y0 = min(self._sel_start.y(), self._sel_end.y())
                x1 = max(self._sel_start.x(), self._sel_end.x())
                y1 = max(self._sel_start.y(), self._sel_end.y())
                if self._tool in _TEXT_MARKUP_TOOLS:
                    preview = self._text_rects_in_selection()
                    if preview:
                        for rect in preview:
                            wr = _map_pdf_rect_to_widget(
                                rect,
                                self._page_w,
                                self._page_h,
                                self.width(),
                                self.height(),
                                self._rotation,
                            )
                            self._paint_text_markup_style(
                                painter,
                                self._tool.value,
                                wr,
                                QColor(
                                    int(self._markup_color[0] * 255),
                                    int(self._markup_color[1] * 255),
                                    int(self._markup_color[2] * 255),
                                    110,
                                ),
                            )
                    else:
                        painter.fillRect(
                            QRectF(x0, y0, x1 - x0, y1 - y0), QColor(255, 220, 0, 40)
                        )
                else:
                    fill = QColor(40, 120, 255, 60)
                    if self._tool != AnnotTool.SELECT:
                        fill = QColor(47, 155, 230, 50)
                    painter.fillRect(QRectF(x0, y0, x1 - x0, y1 - y0), fill)
                    if self._tool in (
                        AnnotTool.RECT,
                        AnnotTool.CIRCLE,
                        AnnotTool.LINE,
                        AnnotTool.FORM_TEXT,
                        AnnotTool.FORM_CHECK,
                        AnnotTool.IMAGE,
                        AnnotTool.REDACT,
                    ):
                        painter.setPen(QPen(QColor(47, 155, 230), 1))
                        if self._tool == AnnotTool.CIRCLE:
                            painter.drawEllipse(QRectF(x0, y0, x1 - x0, y1 - y0))
                        elif self._tool == AnnotTool.LINE:
                            painter.drawLine(self._sel_start, self._sel_end)
                        elif self._tool == AnnotTool.REDACT:
                            painter.fillRect(
                                QRectF(x0, y0, x1 - x0, y1 - y0),
                                QColor(0, 0, 0, 160),
                            )
                            painter.setPen(QPen(QColor(220, 40, 40), 2))
                            painter.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
                        else:
                            painter.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))

            if len(self._ink_points) >= 2:
                painter.setPen(QPen(QColor(20, 20, 20), 2))
                for i in range(1, len(self._ink_points)):
                    a = self._pdf_to_widget_point(self._ink_points[i - 1])
                    b = self._pdf_to_widget_point(self._ink_points[i])
                    painter.drawLine(a, b)
        finally:
            painter.end()

    def _paint_text_markup_style(
        self,
        painter: QPainter,
        kind: str,
        wr: QRectF,
        color: QColor,
    ) -> None:
        if kind == "highlight":
            painter.fillRect(wr, color)
            return
        pen = QPen(color)
        pen.setWidth(max(2, int(wr.height() * 0.12)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if kind == "underline":
            y = wr.bottom() - max(1.0, wr.height() * 0.12)
            painter.drawLine(QPointF(wr.left(), y), QPointF(wr.right(), y))
        elif kind == "strikeout":
            y = wr.center().y()
            painter.drawLine(QPointF(wr.left(), y), QPointF(wr.right(), y))
        else:
            painter.fillRect(wr, color)

    def _paint_markup_overlays(self, painter: QPainter) -> None:
        for entry in self._overlay_entries:
            if entry.kind == "redaction" and entry.redaction is not None:
                region = entry.redaction
                if region.page_index != self.logical_page:
                    continue
                wr = _map_pdf_rect_to_widget(
                    region.rect,
                    self._page_w,
                    self._page_h,
                    self.width(),
                    self.height(),
                    self._rotation,
                )
                painter.fillRect(wr, QColor(0, 0, 0, 170))
                painter.setPen(QPen(QColor(220, 40, 40), 2))
                painter.drawRect(wr)
                continue
            if entry.kind != "annotation" or entry.annotation is None:
                continue
            op = entry.annotation
            if op.page_index != self.logical_page:
                continue
            color = QColor(
                int(op.color[0] * 255),
                int(op.color[1] * 255),
                int(op.color[2] * 255),
                90 if op.kind == "highlight" else 220,
            )
            display_rects = op.rects
            if (
                self._selected_op == op
                and self._live_rect is not None
                and op.kind in MOVABLE_ANNOT_KINDS
            ):
                display_rects = (self._live_rect,)
            for rect in display_rects:
                wr = _map_pdf_rect_to_widget(
                    rect,
                    self._page_w,
                    self._page_h,
                    self.width(),
                    self.height(),
                    self._rotation,
                )
                if op.kind in ("highlight", "underline", "strikeout"):
                    self._paint_text_markup_style(painter, op.kind, wr, color)
                elif op.kind == "circle":
                    painter.setPen(QPen(color, 2))
                    painter.drawEllipse(wr)
                elif op.kind == "image":
                    pix = self._image_pixmap(op.image_path)
                    if pix is not None and not pix.isNull():
                        painter.drawPixmap(wr.toRect(), pix)
                    else:
                        painter.fillRect(wr, QColor(200, 200, 200, 120))
                        painter.setPen(QColor(120, 120, 120))
                        painter.drawText(wr, Qt.AlignmentFlag.AlignCenter, "Image")
                elif op.kind in ("rect", "stamp", "freetext"):
                    if op.kind == "freetext":
                        if op.border:
                            painter.setPen(QPen(color, 2))
                            painter.drawRect(wr)
                        if op.text:
                            painter.setPen(
                                QColor(
                                    int(op.color[0] * 255),
                                    int(op.color[1] * 255),
                                    int(op.color[2] * 255),
                                )
                            )
                            font = painter.font()
                            px = max(
                                8,
                                int(op.fontsize * (self.height() / max(self._page_h, 1.0))),
                            )
                            font.setPointSizeF(float(px))
                            painter.setFont(font)
                            painter.drawText(
                                wr,
                                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                                op.text,
                            )
                    else:
                        painter.setPen(QPen(color, 2))
                        painter.drawRect(wr)
                        if op.kind == "stamp":
                            painter.drawText(wr, Qt.AlignmentFlag.AlignCenter, "Stamp")
            if (
                self._selected_op == op
                and op.kind in MOVABLE_ANNOT_KINDS
                and display_rects
            ):
                wr = _map_pdf_rect_to_widget(
                    display_rects[0],
                    self._page_w,
                    self._page_h,
                    self.width(),
                    self.height(),
                    self._rotation,
                )
                _paint_resize_handles(painter, wr)
            if op.kind == "line" and len(op.points) >= 2:
                painter.setPen(QPen(color, 2))
                painter.drawLine(
                    self._pdf_to_widget_point(op.points[0]),
                    self._pdf_to_widget_point(op.points[1]),
                )
            if op.kind == "ink":
                painter.setPen(QPen(QColor(20, 20, 20, 180), 2))
                for stroke in op.strokes:
                    for i in range(1, len(stroke)):
                        painter.drawLine(
                            self._pdf_to_widget_point(stroke[i - 1]),
                            self._pdf_to_widget_point(stroke[i]),
                        )
            if op.kind == "comment" and op.points:
                pt = self._pdf_to_widget_point(op.points[0])
                painter.setBrush(QColor(255, 220, 80))
                painter.setPen(QPen(QColor(180, 140, 0), 1))
                painter.drawEllipse(pt, 6, 6)

    def _image_pixmap(self, path: str) -> QPixmap | None:
        if not path:
            return None
        cached = self._image_pixmaps.get(path)
        if cached is not None:
            return cached
        pix = QPixmap(path)
        if pix.isNull():
            return None
        self._image_pixmaps[path] = pix
        return pix

    def _display_rect_for(self, op: AnnotationOp) -> tuple[float, float, float, float] | None:
        if self._selected_op == op and self._live_rect is not None:
            return self._live_rect
        if op.rects:
            return op.rects[0]
        return None

    def _movable_at(self, pos: QPointF) -> tuple[AnnotationOp, str] | None:
        """Return (op, handle|move) under *pos*, preferring the selected op."""
        candidates: list[AnnotationOp] = []
        for entry in self._overlay_entries:
            op = entry.annotation
            if (
                entry.kind != "annotation"
                or op is None
                or op.page_index != self.logical_page
                or op.kind not in MOVABLE_ANNOT_KINDS
                or not op.rects
            ):
                continue
            candidates.append(op)
        # Top-most last in list; prefer selected.
        ordered = sorted(
            candidates,
            key=lambda o: (0 if o == self._selected_op else 1),
        )
        for op in ordered:
            rect = self._display_rect_for(op)
            if rect is None:
                continue
            wr = _map_pdf_rect_to_widget(
                rect,
                self._page_w,
                self._page_h,
                self.width(),
                self.height(),
                self._rotation,
            )
            if op == self._selected_op:
                handle = _hit_resize_handle(wr, pos)
                if handle is not None:
                    return op, handle
            inflated = wr.adjusted(-_HANDLE_PX, -_HANDLE_PX, _HANDLE_PX, _HANDLE_PX)
            if inflated.contains(pos):
                if wr.contains(pos) or op == self._selected_op:
                    return op, "move" if wr.contains(pos) else (
                        _hit_resize_handle(wr, pos) or "move"
                    )
        return None

    def _pdf_to_widget_point(self, point: tuple[float, float]) -> QPointF:
        r = _map_pdf_rect_to_widget(
            (point[0], point[1], point[0] + 0.1, point[1] + 0.1),
            self._page_w,
            self._page_h,
            self.width(),
            self.height(),
            self._rotation,
        )
        return QPointF(r.x(), r.y())

    def _update_cursor(self, pos: QPointF | None = None) -> None:
        if self._transform_mode is not None:
            shape = _HANDLE_CURSORS.get(self._transform_mode, Qt.CursorShape.ArrowCursor)
            self.setCursor(shape)
            return
        if pos is not None:
            hit = self._movable_at(pos)
            if hit is not None:
                _op, mode = hit
                shape = _HANDLE_CURSORS.get(mode, Qt.CursorShape.SizeAllCursor)
                self.setCursor(shape)
                return
        if self._tool == AnnotTool.SELECT:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        elif self._tool == AnnotTool.FORM_FILL:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def _begin_transform(self, op: AnnotationOp, mode: str, pos: QPointF) -> None:
        rect = self._display_rect_for(op)
        if rect is None:
            return
        self._selected_op = op
        self._transform_mode = mode
        self._transform_origin = op
        self._transform_start_pdf = self._widget_to_pdf(pos)
        self._transform_start_rect = rect
        self._live_rect = rect
        self.markup_gesture.emit(
            self.logical_page,
            "select_overlay",
            {"annotation": op},
        )
        self._update_cursor(pos)
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._movable_at(event.position())
        if hit is not None and hit[0].kind == "freetext":
            self.markup_gesture.emit(
                self.logical_page,
                "edit_freetext",
                {"annotation": hit[0]},
            )
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()

        # Move / resize pending text & image boxes (Select / Text / Image tools).
        if self._tool in (AnnotTool.SELECT, AnnotTool.FREETEXT, AnnotTool.IMAGE):
            hit = self._movable_at(pos)
            if hit is not None:
                self._begin_transform(hit[0], hit[1], pos)
                event.accept()
                return

        if self._tool == AnnotTool.SELECT:
            link = self._link_at(pos)
            if link is not None:
                self.link_activated.emit(self.logical_page, link)
                event.accept()
                return
            if self._selected_op is not None:
                self._selected_op = None
                self._live_rect = None
                self.markup_gesture.emit(self.logical_page, "select_overlay", {"annotation": None})
            self._selecting = True
            self._sel_start = pos
            self._sel_end = pos
            self._selected_text = ""
            self.update()
            event.accept()
            return

        if self._tool == AnnotTool.FORM_FILL:
            widget = self._widget_at(pos)
            if widget is not None:
                self.form_field_activated.emit(self.logical_page, widget)
            event.accept()
            return

        if self._tool == AnnotTool.FREETEXT:
            pdf_pt = self._widget_to_pdf(pos)
            self.markup_gesture.emit(
                self.logical_page,
                self._tool.value,
                {"point": pdf_pt, "widget_pos": (pos.x(), pos.y())},
            )
            event.accept()
            return

        if self._tool in (AnnotTool.STAMP, AnnotTool.COMMENT):
            pdf_pt = self._widget_to_pdf(pos)
            self.markup_gesture.emit(
                self.logical_page,
                self._tool.value,
                {"point": pdf_pt, "widget_pos": (pos.x(), pos.y())},
            )
            event.accept()
            return

        if self._tool == AnnotTool.INK:
            self._drawing = True
            self._ink_points = [self._widget_to_pdf(pos)]
            self.update()
            event.accept()
            return

        # Drag tools: highlight/underline/strikeout/shapes/image/form create
        self._selecting = True
        self._sel_start = pos
        self._sel_end = pos
        self.update()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self._transform_mode and self._transform_start_pdf and self._transform_start_rect:
            cur = self._widget_to_pdf(pos)
            dx = cur[0] - self._transform_start_pdf[0]
            dy = cur[1] - self._transform_start_pdf[1]
            self._live_rect = _apply_box_transform(
                self._transform_start_rect, self._transform_mode, dx, dy
            )
            self.update()
            event.accept()
            return
        if self._tool == AnnotTool.SELECT:
            if self._link_at(pos) is not None:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self._update_cursor(pos)
        else:
            self._update_cursor(pos)
        if self._drawing and self._tool == AnnotTool.INK:
            self._ink_points.append(self._widget_to_pdf(pos))
            self.update()
            event.accept()
            return
        if self._selecting:
            self._sel_end = pos
            if self._tool == AnnotTool.SELECT:
                self._selected_text = self._text_in_selection()
                self.selection_changed.emit()
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return

        if self._transform_mode and self._transform_origin is not None:
            mode = self._transform_mode
            origin = self._transform_origin
            live = self._live_rect
            self._transform_mode = None
            self._transform_origin = None
            self._transform_start_pdf = None
            self._transform_start_rect = None
            if live is not None and origin.rects and live != origin.rects[0]:
                self.markup_gesture.emit(
                    self.logical_page,
                    "transform_overlay",
                    {"annotation": origin, "rect": live, "mode": mode},
                )
            self._live_rect = None
            self.update()
            event.accept()
            return

        if self._drawing and self._tool == AnnotTool.INK:
            self._drawing = False
            if len(self._ink_points) >= 2:
                self.markup_gesture.emit(
                    self.logical_page,
                    AnnotTool.INK.value,
                    {"strokes": [tuple(self._ink_points)]},
                )
            self._ink_points = []
            self.update()
            event.accept()
            return

        if self._selecting:
            self._selecting = False
            self._sel_end = event.position()
            if self._tool == AnnotTool.SELECT:
                self._selected_text = self._text_in_selection()
                self.selection_changed.emit()
                self.update()
                event.accept()
                return
            payload = self._drag_payload()
            self._sel_start = None
            self._sel_end = None
            self.update()
            if payload is not None:
                self.markup_gesture.emit(self.logical_page, self._tool.value, payload)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _drag_payload(self) -> dict | None:
        if self._sel_start is None or self._sel_end is None:
            return None
        p0 = self._widget_to_pdf(self._sel_start)
        p1 = self._widget_to_pdf(self._sel_end)
        if self._tool == AnnotTool.LINE:
            if abs(p0[0] - p1[0]) < 1 and abs(p0[1] - p1[1]) < 1:
                return None
            return {"points": (p0, p1)}
        x0, x1 = sorted((p0[0], p1[0]))
        y0, y1 = sorted((p0[1], p1[1]))
        if x1 - x0 < 2 and y1 - y0 < 2:
            return None
        rect = (x0, y0, x1, y1)
        if self._tool in _TEXT_MARKUP_TOOLS:
            # Never fall back to the raw drag box — that paints oversized yellow rects.
            return {"rects": self._text_rects_in_selection()}
        return {"rect": rect}

    def _widget_to_pdf(self, pos: QPointF) -> tuple[float, float]:
        return _widget_point_to_pdf(
            pos,
            self._page_w,
            self._page_h,
            self.width(),
            self.height(),
            self._rotation,
        )

    def _link_at(self, pos: QPointF) -> LinkInfo | None:
        x, y = self._widget_to_pdf(pos)
        for link in self._links:
            x0, y0, x1, y1 = link.rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                return link
        return None

    def _widget_at(self, pos: QPointF) -> WidgetInfo | None:
        x, y = self._widget_to_pdf(pos)
        for widget in self._widgets:
            x0, y0, x1, y1 = widget.rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                return widget
        return None

    def _freetext_at(self, pos: QPointF) -> AnnotationOp | None:
        x, y = self._widget_to_pdf(pos)
        for entry in reversed(self._overlay_entries):
            if entry.kind != "annotation" or entry.annotation is None:
                continue
            op = entry.annotation
            if op.kind != "freetext" or op.page_index != self.logical_page:
                continue
            for rect in op.rects:
                x0, y0, x1, y1 = rect
                if x0 <= x <= x1 and y0 <= y <= y1:
                    return op
        return None

    def _ensure_text_dict(self) -> dict | None:
        if self._text_dict is not None:
            return self._text_dict
        if self._text_provider is None:
            return None
        try:
            self._text_dict = self._text_provider()
        except Exception:
            self._text_dict = None
        self._text_provider = None
        return self._text_dict

    def _selection_widget_bounds(
        self, *, inflate_y: float = 0.0
    ) -> tuple[float, float, float, float] | None:
        if self._sel_start is None or self._sel_end is None:
            return None
        ax = min(self._sel_start.x(), self._sel_end.x())
        ay = min(self._sel_start.y(), self._sel_end.y())
        bx = max(self._sel_start.x(), self._sel_end.x())
        by = max(self._sel_start.y(), self._sel_end.y())
        if bx - ax < 2 and by - ay < 2:
            return None
        if inflate_y > 0 and (by - ay) < inflate_y * 2:
            mid = (ay + by) / 2
            ay = mid - inflate_y
            by = mid + inflate_y
        return ax, ay, bx, by

    def _text_in_selection(self) -> str:
        text_dict = self._ensure_text_dict()
        bounds = self._selection_widget_bounds(inflate_y=_TEXT_MARKUP_Y_PAD_PX)
        if text_dict is None or bounds is None:
            return ""
        ax, ay, bx, by = bounds
        parts: list[str] = []
        for block in text_dict.get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines", []):
                line_bits: list[str] = []
                for span in line.get("spans", []):
                    for ch in self._span_chars(span):
                        glyph, bbox = ch
                        wr = _map_pdf_rect_to_widget(
                            bbox,
                            self._page_w,
                            self._page_h,
                            self.width(),
                            self.height(),
                            self._rotation,
                        )
                        if wr.right() < ax or wr.left() > bx or wr.bottom() < ay or wr.top() > by:
                            continue
                        line_bits.append(glyph)
                    if not self._span_chars(span):
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

    @staticmethod
    def _span_chars(
        span: dict,
    ) -> list[tuple[str, tuple[float, float, float, float]]]:
        chars = span.get("chars")
        if not chars:
            return []
        out: list[tuple[str, tuple[float, float, float, float]]] = []
        for ch in chars:
            glyph = ch.get("c") or ""
            bbox = ch.get("bbox")
            if not glyph or not bbox:
                continue
            out.append((glyph, tuple(float(v) for v in bbox)))  # type: ignore[arg-type]
        return out

    def text_rects_in_selection(self) -> tuple[tuple[float, float, float, float], ...]:
        return self._text_rects_in_selection()

    def _text_rects_in_selection(self) -> tuple[tuple[float, float, float, float], ...]:
        text_dict = self._ensure_text_dict()
        bounds = self._selection_widget_bounds(inflate_y=_TEXT_MARKUP_Y_PAD_PX)
        if text_dict is None or bounds is None:
            return ()
        ax, ay, bx, by = bounds
        char_rects: list[tuple[float, float, float, float]] = []
        for block in text_dict.get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    chars = self._span_chars(span)
                    if chars:
                        for _glyph, bbox in chars:
                            wr = _map_pdf_rect_to_widget(
                                bbox,
                                self._page_w,
                                self._page_h,
                                self.width(),
                                self.height(),
                                self._rotation,
                            )
                            # Prefer center-in-selection so thin line sweeps work.
                            cx = (wr.left() + wr.right()) / 2
                            cy = (wr.top() + wr.bottom()) / 2
                            if ax <= cx <= bx and ay <= cy <= by:
                                char_rects.append(bbox)
                        continue
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
                    cx = (wr.left() + wr.right()) / 2
                    cy = (wr.top() + wr.bottom()) / 2
                    if ax <= cx <= bx and ay <= cy <= by:
                        char_rects.append(tuple(float(v) for v in bbox))  # type: ignore[arg-type]
                    elif not (
                        wr.right() < ax or wr.left() > bx or wr.bottom() < ay or wr.top() > by
                    ):
                        # Partial span overlap without char data: clip to selection in PDF space.
                        pdf_sel = (
                            self._widget_to_pdf(QPointF(ax, ay)),
                            self._widget_to_pdf(QPointF(bx, by)),
                        )
                        sx0 = min(pdf_sel[0][0], pdf_sel[1][0])
                        sy0 = min(pdf_sel[0][1], pdf_sel[1][1])
                        sx1 = max(pdf_sel[0][0], pdf_sel[1][0])
                        sy1 = max(pdf_sel[0][1], pdf_sel[1][1])
                        x0, y0, x1, y1 = (float(v) for v in bbox)
                        clipped = (
                            max(x0, sx0),
                            max(y0, sy0),
                            min(x1, sx1),
                            min(y1, sy1),
                        )
                        if clipped[2] - clipped[0] > 1 and clipped[3] - clipped[1] > 1:
                            char_rects.append(clipped)
        return _merge_char_rects(char_rects)


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
    markup_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PdfViewer")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._model: PdfEditModel | None = None
        self._get_loader: Callable[[str], PdfLoader] | None = None
        self._markup: MarkupSession | None = None
        self._tool = AnnotTool.SELECT
        self._markup_color = _DEFAULT_MARKUP_COLOR
        self._selected_overlay: AnnotationOp | None = None
        self._layout = ViewerLayout.CONTINUOUS
        self._zoom_mode = ZoomMode.FIT_WIDTH
        self._zoom_percent = DEFAULT_ZOOM_PERCENT
        self._render_width_px = 800
        self._current_page = 0
        self._generation = 0
        self._search_generation = 0
        self._page_sizes: list[tuple[float, float]] = []  # unrotated points
        self._page_offsets: list[int] | None = None
        self._side_panel_dirty = False
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
        self._side_panel_timer = QTimer(self)
        self._side_panel_timer.setSingleShot(True)
        self._side_panel_timer.setInterval(0)
        self._side_panel_timer.timeout.connect(self._refresh_side_panel_if_dirty)

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
        # Scrollbar show/hide changes viewport size without resizing this widget.
        self._scroll.viewport().installEventFilter(self)

        self._canvas = QWidget()
        self._canvas.setObjectName("PdfViewerCanvas")
        # No layout — continuous mode virtualizes with absolute tile geometry;
        # single/spread place tiles the same way.
        self._scroll.setWidget(self._canvas)

        center_layout.addWidget(self._scroll, stretch=1)
        self._overlay = BusyOverlay(self._scroll.viewport())

        self._hint = QLabel(
            "Right-click for markup tools  ·  PgUp/PgDn  ·  Ctrl+scroll zoom  ·  Esc grid"
        )
        self._hint.setObjectName("PdfViewerHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self._hint)

        self._annot_rail = self._build_annot_rail()
        self._annot_rail_collapsed = False

        self._splitter.addWidget(center)
        self._splitter.addWidget(self._annot_rail)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setSizes([SIDE_PANEL_WIDTH, 800, ANNOT_RAIL_WIDTH])
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
        *,
        markup: MarkupSession | None = None,
    ) -> None:
        self._cancel_all()
        self._model = model
        self._get_loader = get_loader
        self._markup = markup
        self._tool = AnnotTool.SELECT
        self._sync_annot_tool_ui()
        self._current_page = 0
        self._hits = []
        self._hit_index = -1
        self._cache.clear()
        self._clear_tiles()
        self._page_sizes = []
        self._invalidate_offsets()
        self._ocg_on.clear()
        self._ocg_source = None
        self._search_edit.clear()
        self._hit_label.setText("")
        if model is None:
            self._side_panel_timer.stop()
            self._side_panel_dirty = False
            self._outline.clear()
            self._layers.clear()
            self._attachments.clear()
            return
        self._load_page_sizes()
        self._refresh_side_panel(outline=False)
        # Large TOCs are built on the next event-loop turn so the first canvas
        # paint is not blocked under FITZ_LOCK.
        self._side_panel_dirty = True
        self._side_panel_timer.start()
        self._rebuild_canvas()
        self._update_render_width()
        self._schedule_render()

    @property
    def markup_session(self) -> MarkupSession | None:
        return self._markup

    @property
    def annot_tool(self) -> AnnotTool:
        return self._tool

    def set_annot_tool(self, tool: AnnotTool) -> None:
        self._tool = tool
        self._sync_annot_tool_ui()
        for tile in self._tiles.values():
            tile.set_tool(tool)
            tile.clear_selection()
        labels = {
            AnnotTool.SELECT: "Select text — click boxes to move or resize",
            AnnotTool.HIGHLIGHT: "Highlight — drag over text (color from Markup color)",
            AnnotTool.UNDERLINE: "Underline — drag over text (color from Markup color)",
            AnnotTool.STRIKEOUT: "Strikeout — drag over text (color from Markup color)",
            AnnotTool.INK: "Ink — draw freehand",
            AnnotTool.RECT: "Rectangle — drag",
            AnnotTool.CIRCLE: "Circle — drag",
            AnnotTool.LINE: "Line — drag",
            AnnotTool.STAMP: "Stamp — click to place",
            AnnotTool.FREETEXT: "Free text — click to place; drag handles to resize",
            AnnotTool.IMAGE: "Image — drag a box, then choose a file",
            AnnotTool.COMMENT: "Comment — click to place",
            AnnotTool.REDACT: "Redact — drag a region; Apply redaction exports a verified copy",
            AnnotTool.FORM_FILL: "Fill form — click a field",
            AnnotTool.FORM_TEXT: "Add text field — drag",
            AnnotTool.FORM_CHECK: "Add checkbox — drag",
        }
        self.status_message.emit(labels.get(tool, tool.value))

    def _sync_annot_tool_ui(self) -> None:
        if not hasattr(self, "_annot_group"):
            return
        for i, (_label, tool) in enumerate(ANNOT_TOOL_ITEMS):
            btn = self._annot_group.button(i)
            if btn is not None:
                btn.setChecked(tool == self._tool)

    def refresh_markup_overlays(self) -> None:
        entries = self._markup.ops() if self._markup is not None else []
        for tile in self._tiles.values():
            tile.set_overlay_entries(entries)
            tile.set_markup_color(self._markup_color)
            tile.set_selected_op(
                self._selected_overlay
                if self._selected_overlay is not None
                and self._selected_overlay.page_index == tile.logical_page
                else None
            )

    def _set_selected_overlay(self, op: AnnotationOp | None) -> None:
        self._selected_overlay = op
        for tile in self._tiles.values():
            tile.set_selected_op(
                op if op is not None and op.page_index == tile.logical_page else None
            )

    def _delete_overlay(self, op: AnnotationOp | None = None) -> bool:
        if self._markup is None:
            return False
        target = op if op is not None else self._selected_overlay
        if target is None or target.kind not in MOVABLE_ANNOT_KINDS:
            return False
        if not self._markup.remove_annotation(target):
            return False
        self._set_selected_overlay(None)
        self.refresh_markup_overlays()
        self.markup_changed.emit()
        label = "Image" if target.kind == "image" else "Text"
        self.status_message.emit(f"{label} removed")
        return True

    def _pick_markup_color(self) -> None:
        rgb = [int(c * 255) for c in self._markup_color]
        chosen = QColorDialog.getColor(QColor(*rgb), self, "Markup color")
        if not chosen.isValid():
            return
        self._markup_color = (chosen.red() / 255.0, chosen.green() / 255.0, chosen.blue() / 255.0)
        self._sync_markup_color_button()
        for tile in self._tiles.values():
            tile.set_markup_color(self._markup_color)
        self.status_message.emit("Markup color updated")

    def _sync_markup_color_button(self) -> None:
        if not hasattr(self, "_markup_color_btn"):
            return
        r, g, b = (int(c * 255) for c in self._markup_color)
        self._markup_color_btn.setStyleSheet(
            f"background-color: rgb({r}, {g}, {b}); min-height: 22px;"
        )

    def set_layout_mode(self, mode: ViewerLayout) -> None:
        if mode == self._layout:
            return
        self._cancel_all()
        self._layout = mode
        self._invalidate_offsets()
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
        self._invalidate_offsets()
        self._update_render_width()
        self._rebuild_canvas()
        self._schedule_render()

    def reset_zoom(self) -> None:
        """Ctrl+0 — fit width."""
        self.set_zoom_mode(ZoomMode.FIT_WIDTH)

    def reset_zoom_to_fit(self) -> None:
        """Alias used by PdfTab / MainWindow preview entry."""
        self.reset_zoom()

    def zoom_by(self, step_px: int) -> None:
        if self._model is None:
            return
        # Convert pixel step into percent mode from current width.
        base = max(self._fit_width_px(), 1)
        current_pct = int(round(100 * self._render_width_px / base))
        delta_pct = int(round(100 * step_px / base)) or (1 if step_px > 0 else -1)
        self.set_zoom_mode(ZoomMode.PERCENT, current_pct + delta_pct)

    def go_to_page(
        self,
        page_index: int,
        *,
        pdf_x: float | None = None,
        pdf_y: float | None = None,
    ) -> None:
        """Jump to a logical page; optional PDF-space point scrolls into view."""
        if self._model is None:
            return
        last = max(0, self._model.logical_count() - 1)
        page_index = max(0, min(page_index, last))
        changed = page_index != self._current_page
        self._current_page = page_index
        if self._layout != ViewerLayout.CONTINUOUS:
            self._rebuild_canvas()
            self._schedule_render()
            self._scroll_to_pdf_point(page_index, pdf_x, pdf_y)
        else:
            self._scroll_to_pdf_point(page_index, pdf_x, pdf_y)
            self._sync_continuous_tiles()
            self._schedule_render()
        if changed:
            self.page_changed.emit(self._current_page)
        self._update_page_label()

    def _scroll_to_pdf_point(
        self,
        logical: int,
        pdf_x: float | None,
        pdf_y: float | None,
    ) -> None:
        """Scroll so *pdf_y* (page top if None) sits near the top of the viewport."""
        if self._model is None or logical >= len(self._page_sizes):
            return
        ref = self._model.page_at(logical)
        pw, ph = self._page_sizes[logical]
        tile_w, tile_h = self._display_size_for(logical)
        x = 0.0 if pdf_x is None else pdf_x
        y = 0.0 if pdf_y is None else pdf_y
        mapped = _map_pdf_rect_to_widget(
            (x, y, x + 1.0, y + 1.0),
            pw,
            ph,
            tile_w,
            tile_h,
            ref.rotation,
        )
        if self._layout == ViewerLayout.CONTINUOUS:
            offsets = self._page_y_offsets()
            if logical >= len(offsets):
                return
            target = offsets[logical] + int(mapped.y()) - PAGE_GAP_PX
        else:
            target = int(mapped.y()) - PAGE_GAP_PX
        self._scroll.verticalScrollBar().setValue(max(0, target))

    def show_page(self, page_index: int) -> None:
        """Alias for MainWindow / tab preview entry (same as go_to_page)."""
        self.go_to_page(page_index)

    def clear_caches(self) -> None:
        """Drop pixmap cache + cancel renders (e.g. return to grid)."""
        self._cancel_all()
        self._cache.clear()
        self._overlay.hide_overlay()
        self.busy_changed.emit(False, "")

    @property
    def cache_size(self) -> int:
        return len(self._cache._items)

    @property
    def cache_max(self) -> int:
        return self._cache._max

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

    def _build_annot_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("PdfViewerAnnotRail")
        rail.setMinimumWidth(ANNOT_RAIL_COLLAPSED)
        rail.setMaximumWidth(ANNOT_RAIL_WIDTH)
        rail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        outer = QVBoxLayout(rail)
        outer.setContentsMargins(4, 6, 4, 6)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        self._annot_rail_title = QLabel("Markup")
        self._annot_rail_title.setObjectName("PdfViewerAnnotRailTitle")
        self._annot_rail_title.setAccessibleName("Markup tools")
        header.addWidget(self._annot_rail_title, stretch=1)

        self._annot_collapse_btn = QToolButton()
        self._annot_collapse_btn.setObjectName("PdfViewerAnnotCollapse")
        self._annot_collapse_btn.setText("»")
        self._annot_collapse_btn.setToolTip("Collapse markup tools")
        self._annot_collapse_btn.setAccessibleName("Collapse markup tools")
        self._annot_collapse_btn.clicked.connect(self._toggle_annot_rail)
        header.addWidget(self._annot_collapse_btn)
        outer.addLayout(header)

        self._annot_tools_host = QWidget()
        self._annot_tools_host.setObjectName("PdfViewerAnnotTools")
        tools_layout = QVBoxLayout(self._annot_tools_host)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(2)

        self._annot_group = QButtonGroup(self)
        self._annot_group.setExclusive(True)
        for i, (label, tool) in enumerate(ANNOT_TOOL_ITEMS):
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setAccessibleName(f"Annotation tool {label}")
            btn.setToolTip(label)
            if tool == AnnotTool.SELECT:
                btn.setChecked(True)
            self._annot_group.addButton(btn, i)
            btn.clicked.connect(lambda _checked=False, t=tool: self.set_annot_tool(t))
            tools_layout.addWidget(btn)

        self._markup_color_btn = QToolButton()
        self._markup_color_btn.setText("Color")
        self._markup_color_btn.setObjectName("PdfViewerMarkupColor")
        self._markup_color_btn.setAccessibleName("Markup color")
        self._markup_color_btn.setToolTip("Color for highlight, underline, and strikeout")
        self._markup_color_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._markup_color_btn.clicked.connect(self._pick_markup_color)
        self._sync_markup_color_button()
        tools_layout.addWidget(self._markup_color_btn)

        flatten_btn = QToolButton()
        flatten_btn.setText("Flatten forms")
        flatten_btn.setAccessibleName("Flatten forms")
        flatten_btn.setToolTip("Bake form appearances on Save As")
        flatten_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        flatten_btn.clicked.connect(self._on_flatten_forms)
        tools_layout.addWidget(flatten_btn)

        apply_redact_btn = QToolButton()
        apply_redact_btn.setText("Apply redaction")
        apply_redact_btn.setAccessibleName("Apply redaction")
        apply_redact_btn.setToolTip(
            "Write a new PDF with marked regions permanently removed and verified"
        )
        apply_redact_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        apply_redact_btn.clicked.connect(self._on_apply_redaction)
        tools_layout.addWidget(apply_redact_btn)
        tools_layout.addStretch(1)
        outer.addWidget(self._annot_tools_host, stretch=1)

        self._annot_expand_btn = QToolButton()
        self._annot_expand_btn.setObjectName("PdfViewerAnnotExpand")
        self._annot_expand_btn.setText("«")
        self._annot_expand_btn.setToolTip("Show markup tools")
        self._annot_expand_btn.setAccessibleName("Show markup tools")
        self._annot_expand_btn.clicked.connect(self._toggle_annot_rail)
        self._annot_expand_btn.hide()
        outer.addWidget(self._annot_expand_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(0)
        return rail

    def _toggle_annot_rail(self) -> None:
        self._annot_rail_collapsed = not self._annot_rail_collapsed
        collapsed = self._annot_rail_collapsed
        self._annot_tools_host.setVisible(not collapsed)
        self._annot_rail_title.setVisible(not collapsed)
        self._annot_collapse_btn.setVisible(not collapsed)
        self._annot_expand_btn.setVisible(collapsed)
        width = ANNOT_RAIL_COLLAPSED if collapsed else ANNOT_RAIL_WIDTH
        self._annot_rail.setMaximumWidth(width)
        self._annot_rail.setMinimumWidth(width)
        sizes = self._splitter.sizes()
        if len(sizes) >= 3:
            # Keep left+center; assign rail width.
            total = sum(sizes)
            rail = width
            left = sizes[0]
            center = max(200, total - left - rail)
            self._splitter.setSizes([left, center, rail])
        tip = "Show markup tools" if collapsed else "Collapse markup tools"
        self.status_message.emit(tip)

    def _show_annot_context_menu(self, global_pos) -> None:
        menu = QMenu(self)
        menu.setObjectName("PdfViewerAnnotMenu")
        for label, tool in ANNOT_TOOL_ITEMS:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(tool == self._tool)
            action.triggered.connect(lambda _checked=False, t=tool: self.set_annot_tool(t))
        if self._selection_has_text():
            menu.addSeparator()
            for label, tool in (
                ("Highlight selection", AnnotTool.HIGHLIGHT),
                ("Underline selection", AnnotTool.UNDERLINE),
                ("Strikeout selection", AnnotTool.STRIKEOUT),
            ):
                action = menu.addAction(label)
                action.triggered.connect(
                    lambda _checked=False, t=tool: self._apply_text_markup_to_selection(t)
                )
        if (
            self._selected_overlay is not None
            and self._selected_overlay.kind in MOVABLE_ANNOT_KINDS
        ):
            menu.addSeparator()
            delete = menu.addAction("Delete")
            delete.triggered.connect(lambda: self._delete_overlay())
        menu.addSeparator()
        flatten = menu.addAction("Flatten forms…")
        flatten.triggered.connect(self._on_flatten_forms)
        menu.exec(global_pos)

    def _selection_has_text(self) -> bool:
        return any(tile.selected_text() for tile in self._tiles.values())

    def _apply_text_markup_to_selection(self, tool: AnnotTool) -> None:
        if self._markup is None or tool not in _TEXT_MARKUP_TOOLS:
            return
        applied = False
        for tile in self._tiles.values():
            rects = tile.text_rects_in_selection()
            if not rects:
                continue
            self._markup.push_annotation(
                AnnotationOp(
                    kind=tool.value,  # type: ignore[arg-type]
                    page_index=tile.logical_page,
                    rects=rects,
                    color=self._markup_color,
                )
            )
            tile.clear_selection()
            applied = True
        if not applied:
            self.status_message.emit("No text under selection")
            return
        self.refresh_markup_overlays()
        self.markup_changed.emit()
        self.status_message.emit("Markup added — Save As to keep")

    def _on_flatten_forms(self) -> None:
        if self._markup is None:
            self.status_message.emit("Open a document to flatten forms")
            return
        reply = QMessageBox.question(
            self,
            "Flatten forms",
            "Form fields will be baked into page content when you Save As. Continue?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._markup.push_form_flatten()
        self.refresh_markup_overlays()
        self.markup_changed.emit()
        self.status_message.emit("Flatten forms queued — Save As to apply")

    def _on_apply_redaction(self) -> None:
        """Export a GC-rewritten copy with marked regions permanently removed."""
        if self._markup is None or self._model is None:
            return
        regions = self._markup.redaction_regions()
        if not regions:
            QMessageBox.information(
                self,
                "Apply redaction",
                "Mark one or more regions with the Redact tool first.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Apply redaction")
        form = QFormLayout(dialog)
        strip_meta = QCheckBox("Strip document metadata")
        strip_meta.setChecked(True)
        strip_xmp = QCheckBox("Strip XMP metadata")
        strip_xmp.setChecked(True)
        remove_att = QCheckBox("Remove embedded attachments")
        remove_att.setChecked(False)
        form.addRow(strip_meta)
        form.addRow(strip_xmp)
        form.addRow(remove_att)
        note = QLabel(
            "Writes a new PDF with marked content permanently removed, then "
            "verifies extraction in a fresh process. The original file is never "
            "modified. Failed verification deletes the output."
        )
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        stem = Path(self._model.original_path).stem if self._model.original_path else "document"
        suggested = str(Path(self._model.original_path).with_name(f"{stem}-redacted.pdf"))
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save redacted PDF",
            suggested,
            "PDF Files (*.pdf);;All Files (*)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"

        scope = RedactionScope(
            strip_metadata=strip_meta.isChecked(),
            strip_xmp=strip_xmp.isChecked(),
            remove_attachments=remove_att.isChecked(),
        )
        try:
            redact_edit_model(
                self._model,
                path,
                regions,
                markup=self._markup.non_redaction_ops(),
                scope=scope,
                verify=True,
            )
        except RedactionVerifyError as exc:
            QMessageBox.critical(
                self,
                "Redaction verification failed",
                f"{exc}\n\nNo redacted copy was produced.",
            )
            self.status_message.emit("Redaction verification failed — output discarded")
            return
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Apply redaction",
                f"Could not write redacted PDF:\n{exc}",
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Apply redaction",
                f"Could not apply redaction:\n{exc}",
            )
            return

        self._markup.clear_redactions()
        self.refresh_markup_overlays()
        self.markup_changed.emit()
        name = Path(path).name
        self.status_message.emit(f"Redacted copy saved as {name}")
        QMessageBox.information(
            self,
            "Redaction complete",
            f"Verified redacted copy saved as:\n{path}",
        )

    def _on_markup_gesture(self, logical: int, tool_value: str, payload: object) -> None:
        if self._markup is None or not isinstance(payload, dict):
            return
        if tool_value == "select_overlay":
            ann = payload.get("annotation")
            self._set_selected_overlay(ann if isinstance(ann, AnnotationOp) else None)
            return
        if tool_value == "transform_overlay":
            old = payload.get("annotation")
            rect = payload.get("rect")
            if not isinstance(old, AnnotationOp) or not rect:
                return
            new = replace(old, rects=(tuple(rect),))  # type: ignore[arg-type]
            if not self._markup.replace_annotation(old, new):
                return
            self._set_selected_overlay(new)
            self.refresh_markup_overlays()
            self.markup_changed.emit()
            self.status_message.emit("Moved — Save As to keep")
            return
        if tool_value == "edit_freetext":
            old = payload.get("annotation")
            if not isinstance(old, AnnotationOp):
                return
            result = _prompt_freetext(
                self,
                text=old.text,
                fontsize=old.fontsize,
                color=old.color,
                border=old.border,
                title="Edit free text",
                allow_delete=True,
            )
            if result is None:
                return
            if result == "delete":
                self._delete_overlay(old)
                return
            text, fontsize, color, border = result
            x0, y0, x1, y1 = old.rects[0] if old.rects else (0.0, 0.0, 160.0, 40.0)
            width = max(x1 - x0, 40.0 + fontsize * max(len(text), 1) * 0.45)
            height = max(y1 - y0, fontsize * (1.6 + text.count("\n")))
            new = AnnotationOp(
                kind="freetext",
                page_index=old.page_index,
                rects=((x0, y0, x0 + width, y0 + height),),
                text=text,
                color=color,
                fontsize=fontsize,
                border=border,
            )
            if not self._markup.replace_annotation(old, new):
                return
            self._set_selected_overlay(new)
            self.refresh_markup_overlays()
            self.markup_changed.emit()
            self.status_message.emit("Free text updated — Save As to keep")
            return

        tool = AnnotTool(tool_value)
        created: AnnotationOp | None = None
        if tool in _TEXT_MARKUP_TOOLS:
            rects = payload.get("rects") or ()
            if not rects:
                self.status_message.emit("No text under selection")
                return
            created = AnnotationOp(
                kind=tool.value,  # type: ignore[arg-type]
                page_index=logical,
                rects=tuple(rects),
                color=self._markup_color,
            )
            self._markup.push_annotation(created)
        elif tool == AnnotTool.INK:
            strokes = payload.get("strokes") or ()
            if not strokes:
                return
            normalized = tuple(
                tuple((float(x), float(y)) for x, y in stroke) for stroke in strokes
            )
            created = AnnotationOp(
                kind="ink", page_index=logical, strokes=normalized, color=self._markup_color
            )
            self._markup.push_annotation(created)
        elif tool in (AnnotTool.RECT, AnnotTool.CIRCLE):
            rect = payload.get("rect")
            if not rect:
                return
            created = AnnotationOp(
                kind=tool.value,  # type: ignore[arg-type]
                page_index=logical,
                rects=(rect,),
                color=(0.9, 0.2, 0.2),
            )
            self._markup.push_annotation(created)
        elif tool == AnnotTool.LINE:
            points = payload.get("points")
            if not points:
                return
            created = AnnotationOp(
                kind="line",
                page_index=logical,
                points=tuple(points),
                color=(0.9, 0.2, 0.2),
            )
            self._markup.push_annotation(created)
        elif tool == AnnotTool.STAMP:
            point = payload.get("point")
            if not point:
                return
            x, y = point
            rect = (x, y, x + 100, y + 40)
            created = AnnotationOp(
                kind="stamp",
                page_index=logical,
                rects=(rect,),
                stamp_id=STAMP_APPROVED,
            )
            self._markup.push_annotation(created)
        elif tool == AnnotTool.FREETEXT:
            point = payload.get("point")
            if not point:
                return
            result = _prompt_freetext(self)
            if result is None:
                return
            text, fontsize, color, border = result
            x, y = point
            width = max(120.0, fontsize * max(len(text), 1) * 0.45)
            height = max(fontsize * 1.8, fontsize * (1.6 + text.count("\n")))
            rect = (x, y, x + width, y + height)
            created = AnnotationOp(
                kind="freetext",
                page_index=logical,
                rects=(rect,),
                text=text,
                color=color,
                fontsize=fontsize,
                border=border,
            )
            self._markup.push_annotation(created)
            self._set_selected_overlay(created)
        elif tool == AnnotTool.IMAGE:
            rect = payload.get("rect")
            if not rect:
                return
            path, _filter = QFileDialog.getOpenFileName(
                self, "Insert image", "", _IMAGE_FILTERS
            )
            if not path:
                return
            created = AnnotationOp(
                kind="image",
                page_index=logical,
                rects=(tuple(rect),),  # type: ignore[arg-type]
                image_path=path,
            )
            self._markup.push_annotation(created)
            self._set_selected_overlay(created)
        elif tool == AnnotTool.COMMENT:
            point = payload.get("point")
            if not point:
                return
            text, ok = QInputDialog.getText(self, "Comment", "Comment:")
            if not ok:
                return
            created = AnnotationOp(
                kind="comment",
                page_index=logical,
                points=(tuple(point),),  # type: ignore[arg-type]
                text=text.strip(),
            )
            self._markup.push_annotation(created)
        elif tool == AnnotTool.REDACT:
            rect = payload.get("rect")
            if not rect:
                return
            region = RedactionRegion(page_index=logical, rect=tuple(rect))  # type: ignore[arg-type]
            self._markup.push_redaction(region)
            self.refresh_markup_overlays()
            self.markup_changed.emit()
            self.status_message.emit(
                "Redaction marked — Apply redaction to export a verified copy"
            )
            return
        elif tool in (AnnotTool.FORM_TEXT, AnnotTool.FORM_CHECK):
            rect = payload.get("rect")
            if not rect:
                return
            name, ok = QInputDialog.getText(self, "Form field", "Field name:")
            if not ok or not name.strip():
                return
            self._markup.push_form_create(
                FormCreateOp(
                    page_index=logical,
                    field_name=name.strip(),
                    field_type="checkbox" if tool == AnnotTool.FORM_CHECK else "text",
                    rect=tuple(rect),  # type: ignore[arg-type]
                )
            )
        else:
            return
        self.refresh_markup_overlays()
        self.markup_changed.emit()
        self.status_message.emit("Markup added — Save As to keep")

    def _on_form_field_activated(self, logical: int, widget: object) -> None:
        if self._markup is None or not isinstance(widget, WidgetInfo):
            return
        if not widget.name:
            self.status_message.emit("Field has no name")
            return
        text, ok = QInputDialog.getText(
            self,
            "Fill form field",
            f"{widget.name} ({widget.field_type}):",
            text=widget.value,
        )
        if not ok:
            return
        self._markup.push_form_fill({widget.name: text})
        self.markup_changed.emit()
        self.status_message.emit(f"Queued fill for “{widget.name}” — Save As to keep")

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
                if self._get_loader is not None:
                    sizes.append(
                        self._get_loader(ref.source_path).page_size_pt(
                            ref.source_index
                        )
                    )
                else:
                    geom = page_geometry(ref.source_path, ref.source_index)
                    sizes.append((geom.width, geom.height))
            except Exception:
                sizes.append((612.0, 792.0))
        self._page_sizes = sizes

    def _refresh_side_panel_if_dirty(self) -> None:
        if not self._side_panel_dirty or self._model is None:
            return
        self._side_panel_dirty = False
        self._populate_outline()

    def _refresh_side_panel(self, *, outline: bool = True) -> None:
        assert self._model is not None
        if outline:
            self._populate_outline()

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

    def _populate_outline(self) -> None:
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
                (item.source_path, item.source_index, item.left_x, item.top_y),
            )
            parent = parents.get(item.level - 1)
            if parent is None or item.level <= 1:
                self._outline.addTopLevelItem(node)
            else:
                parent.addChild(node)
            parents[item.level] = node
        self._outline.expandToDepth(1)

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

    def _invalidate_offsets(self) -> None:
        self._page_offsets = None

    def _page_y_offsets(self) -> list[int]:
        """Top Y of each logical page in continuous canvas coordinates."""
        if self._page_offsets is not None:
            return self._page_offsets
        offsets: list[int] = []
        y = PAGE_GAP_PX
        count = len(self._page_sizes) if self._model else 0
        for i in range(count):
            offsets.append(y)
            _w, h = self._display_size_for(i)
            y += h + PAGE_GAP_PX
        self._page_offsets = offsets
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
        # Offsets are monotonic — bisect to the first page that could intersect.
        start = bisect.bisect_right(offsets, top) - 1
        start = max(0, start)
        needed: set[int] = set()
        for i in range(start, n):
            y = offsets[i]
            if y > bottom:
                break
            _w, h = self._display_size_for(i)
            if y + h < top:
                continue
            needed.add(i)
        for logical in list(self._tiles):
            if logical not in needed:
                tile = self._tiles.pop(logical)
                tile.setParent(None)
                tile.deleteLater()
                self._pending_meta.discard(logical)
        # Exact width — max(old, …) left a stuck-wide canvas and white gutters
        # after fit-width reflow (search jump / scrollbar appearing).
        canvas_w = self._render_width_px + 2 * PAGE_GAP_PX
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
        tile.markup_gesture.connect(self._on_markup_gesture)
        tile.form_field_activated.connect(self._on_form_field_activated)
        tile.context_menu_requested.connect(self._show_annot_context_menu)
        tile.set_tool(self._tool)
        tile.set_markup_color(self._markup_color)
        if self._markup is not None:
            tile.set_overlay_entries(self._markup.ops())
        if (
            self._selected_overlay is not None
            and self._selected_overlay.page_index == logical
        ):
            tile.set_selected_op(self._selected_overlay)
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
        # Viewport already excludes visible scrollbars — no extra -24 reserve
        # (that left a permanent gutter once the v-bar was shown).
        available = max(viewport.width() - 2 * PAGE_GAP_PX, MIN_PREVIEW_RENDER_WIDTH)
        if self._layout == ViewerLayout.SPREAD:
            available = max(MIN_PREVIEW_RENDER_WIDTH, (available - PAGE_GAP_PX) // 2 * 2)
        return min(MAX_RENDER_WIDTH_PX, available)

    def _fit_page_px(self) -> int:
        """Return render width so the page (or spread) fits in the viewport.

        ``_render_width_px`` uses the same convention as ``_fit_width_px``:
        full content width. Spread layout splits it in ``_display_size_for``.
        """
        if self._model is None or not self._page_sizes:
            return self._fit_width_px()
        logical = self._current_page
        ref = self._model.page_at(logical)
        pw, ph = self._page_sizes[min(logical, len(self._page_sizes) - 1)]
        dw, dh = _rotated_size(pw, ph, ref.rotation)
        viewport = self._scroll.viewport()
        avail_w = max(viewport.width() - 2 * PAGE_GAP_PX, MIN_PREVIEW_RENDER_WIDTH)
        avail_h = max(viewport.height() - 2 * PAGE_GAP_PX, 200)
        if dh <= 0 or dw <= 0:
            return self._fit_width_px()
        # Per-page width budgets (spread: two pages share the viewport width).
        if self._layout == ViewerLayout.SPREAD:
            page_budget_w = max(100, (avail_w - PAGE_GAP_PX) // 2)
        else:
            page_budget_w = avail_w
        per_page = int(min(page_budget_w, avail_h * (dw / dh)))
        if self._layout == ViewerLayout.SPREAD:
            # Invert _display_size_for: page_w = render_w // 2 - PAGE_GAP // 2
            render_w = 2 * per_page + PAGE_GAP_PX
        else:
            render_w = per_page
        return min(MAX_RENDER_WIDTH_PX, max(MIN_PREVIEW_RENDER_WIDTH, render_w))

    def _update_render_width(self) -> None:
        previous = self._render_width_px
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
        if self._render_width_px != previous:
            self._invalidate_offsets()
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

    def _device_pixel_ratio(self) -> float:
        return max(1.0, float(self.devicePixelRatioF()))

    def _physical_render_width(self, logical_width: int) -> int:
        return min(
            MAX_RENDER_WIDTH_PX,
            max(1, int(round(logical_width * self._device_pixel_ratio()))),
        )

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
            logical_w, _h = self._display_size_for(logical)
            physical_w = self._physical_render_width(logical_w)
            ref = self._model.page_at(logical)
            ocg = self._ocg_on.get(ref.source_path)
            key = (logical, physical_w, ref.rotation, ocg)
            cached = self._cache.get(key)
            tile = self._tiles.get(logical)
            if cached is not None:
                if tile is not None:
                    tile.set_pixmap(cached)
                continue
            started = True
            worker = _ViewerRenderWorker(
                ref, logical, physical_w, gen, self._is_cancelled, ocg
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
                widgets = page_widgets(ref.source_path, ref.source_index)
            except Exception:
                widgets = []

            def _text_provider(
                r: PageRef = ref,
            ) -> dict | None:
                try:
                    return page_text_dict(r)
                except Exception:
                    return None

            tile = self._tiles.get(logical)
            if tile is not None:
                tile.set_page_meta(
                    pw,
                    ph,
                    ref.rotation,
                    links,
                    text_provider=_text_provider,
                    widgets=widgets,
                )
                if self._markup is not None:
                    tile.set_overlay_entries(self._markup.ops())
            self._pending_meta.discard(logical)

    def _on_render_finished(
        self, generation: int, logical: int, width_px: int, png: bytes
    ) -> None:
        if self._is_cancelled(generation) or self._model is None:
            return
        ref = self._model.page_at(logical)
        ocg = self._ocg_on.get(ref.source_path)
        logical_w, _ = self._display_size_for(logical)
        expected_physical = self._physical_render_width(logical_w)
        if width_px != expected_physical:
            return
        pix = QPixmap()
        pix.loadFromData(png, "PNG")
        dpr = width_px / max(1, logical_w)
        pix.setDevicePixelRatio(dpr)
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
        active: tuple[float, float, float, float] | None = None
        active_page = -1
        if 0 <= self._hit_index < len(self._hits):
            current = self._hits[self._hit_index]
            active = current.rect
            active_page = current.logical_page
        for logical, tile in self._tiles.items():
            tile.set_hits(
                by_page.get(logical, []),
                active=active if logical == active_page else None,
            )

    def _reveal_current_hit(self) -> None:
        if self._hit_index < 0 or self._hit_index >= len(self._hits):
            return
        hit = self._hits[self._hit_index]
        self.go_to_page(hit.logical_page)
        # After go_to_page — tile sync may recreate widgets.
        self._apply_hits_to_tiles()
        self._hit_label.setText(
            f"{self._hit_index + 1} of {len(self._hits)}"
        )

    def _on_outline_activated(self, item: QTreeWidgetItem) -> None:
        if self._model is None or item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        source_path, source_index, left_x, top_y = data
        logical = logical_index_for_source(self._model, source_path, source_index)
        if logical is not None:
            self.go_to_page(logical, pdf_x=left_x, pdf_y=top_y)

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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self._scroll.viewport()
            and event.type() == QEvent.Type.Resize
            and self.isVisible()
            and self._model is not None
            and self._zoom_mode != ZoomMode.PERCENT
        ):
            previous = self._render_width_px
            self._update_render_width()
            if self._render_width_px != previous:
                self._cache.clear()
                self._rebuild_canvas()
                self._schedule_render()
        return super().eventFilter(watched, event)

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
            if self._selected_overlay is not None:
                self._set_selected_overlay(None)
                event.accept()
                return
            self.closed.emit()
            event.accept()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._delete_overlay():
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
