"""Watermark live preview — page PNG + Qt overlay (Phase 28b).

Page pixels come from ``render_ref_png`` / a debounced worker under ``FITZ_LOCK``.
The watermark itself is painted as a lightweight Qt overlay (no UI-thread fitz).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

from PyQt6.QtCore import QObject, QPointF, QRectF, QRunnable, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from pagedrop.core.jobs.credentials import RuntimeCredentials
from pagedrop.ui.theme import accent_qcolor, on_accent_qcolor
from pagedrop.core.modify_ops import watermark_text_box
from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX
from pagedrop.core.pdf_service import page_geometry, render_ref_png
from pagedrop.core.thread_policy import ensure_no_fitz_document

_HANDLE_PX = 7.0
_ROTATE_OFFSET = 22.0
_MIN_DIAG_PCT = 1.0
_MAX_DIAG_PCT = 100.0
_RENDER_DEBOUNCE_MS = 120
_PREVIEW_WIDTH_PX = 720
_MIN_ZOOM = 0.5
_MAX_ZOOM = 4.0
_ZOOM_STEP = 0.1


@dataclass
class WatermarkOverlayState:
    kind: str = "text"  # text | image
    text: str = "CONFIDENTIAL"
    image_path: str = ""
    color: tuple[float, float, float] = (0.55, 0.55, 0.55)
    opacity: float = 0.3
    angle: float = -45.0
    center_x: float = 0.5
    center_y: float = 0.5
    size_mode: str = "diagonal"  # diagonal | absolute
    diagonal_percent: float = 50.0
    fontsize: float = 72.0
    image_scale: float = 0.5


class WatermarkPageRenderWorker(QRunnable):
    class Signals(QObject):
        finished = pyqtSignal(int, bytes, float, float)  # gen, png, page_w, page_h
        error = pyqtSignal(int, str)

    def __init__(
        self,
        path: str,
        page_index: int,
        width_px: int,
        generation: int,
        is_cancelled: Callable[[int], bool],
        *,
        passwords: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        ensure_no_fitz_document(path, what="WatermarkPageRenderWorker")
        self.signals = self.Signals()
        self._path = path
        self._page_index = page_index
        self._width_px = width_px
        self._generation = generation
        self._is_cancelled = is_cancelled
        self._passwords = passwords
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            if self._is_cancelled(self._generation):
                return
            password = RuntimeCredentials.lookup(self._passwords, self._path)
            geom = page_geometry(
                self._path, self._page_index, password=password
            )
            png = render_ref_png(
                PageRef(self._path, self._page_index),
                self._width_px,
                passwords=self._passwords,
            )
            if self._is_cancelled(self._generation):
                return
            self.signals.finished.emit(
                self._generation, png, geom.width, geom.height
            )
        except Exception as exc:
            if not self._is_cancelled(self._generation):
                self.signals.error.emit(self._generation, str(exc))


def _overlay_size_pts(state: WatermarkOverlayState, page_w: float, page_h: float) -> tuple[float, float]:
    """Unrotated watermark width/height in PDF points (matches apply path)."""
    diag = math.hypot(page_w, page_h)
    if state.kind == "image":
        pix = QPixmap(state.image_path) if state.image_path else QPixmap()
        aspect = (pix.height() / max(pix.width(), 1)) if not pix.isNull() else 1.0
        if state.size_mode == "diagonal":
            w = diag * (state.diagonal_percent / 100.0)
        else:
            w = page_w * max(0.05, min(1.0, state.image_scale))
        return w, w * aspect

    if state.size_mode == "diagonal":
        w, h, _fs = watermark_text_box(
            state.text,
            page_width=page_w,
            page_height=page_h,
            diagonal_percent=state.diagonal_percent,
        )
    else:
        w, h, _fs = watermark_text_box(
            state.text,
            page_width=page_w,
            page_height=page_h,
            fontsize=max(4.0, state.fontsize),
        )
    return w, h


class WatermarkPreviewScroll(QScrollArea):
    """Scroll host that feeds viewport size into the canvas for fit-zoom."""

    def __init__(
        self, canvas: WatermarkPreviewCanvas, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self.setObjectName("WatermarkPreviewScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(canvas)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        vp = self.viewport()
        self._canvas.set_host_size(vp.width(), vp.height())

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._canvas.wheelEvent(event)
            return
        super().wheelEvent(event)


class WatermarkPreviewCanvas(QWidget):
    """Page pixmap with draggable / scalable / rotatable watermark overlay."""

    placement_changed = pyqtSignal(float, float)  # center_x, center_y
    angle_changed = pyqtSignal(float)
    size_changed = pyqtSignal()  # sidebar reads state after
    page_changed = pyqtSignal(int)
    geometry_ready = pyqtSignal(float, float)  # page_w, page_h
    render_error = pyqtSignal(str)
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WatermarkPreviewCanvas")
        self.setMinimumSize(240, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._path: str | None = None
        self._passwords: dict[str, str] | None = None
        self._page_index = 0
        self._page_count = 0
        self._page_w = 1.0
        self._page_h = 1.0
        self._page_pix = QPixmap()
        self._state = WatermarkOverlayState()
        self._image_cache_path = ""
        self._image_cache = QPixmap()
        self._zoom = 1.0
        self._host_w = 240
        self._host_h = 280
        self._render_width_px = _PREVIEW_WIDTH_PX

        self._generation = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_RENDER_DEBOUNCE_MS)
        self._timer.timeout.connect(self._start_render)

        self._drag_mode: str | None = None  # move | rotate | nw|ne|…
        self._drag_origin = QPointF()
        self._drag_center = (0.5, 0.5)
        self._drag_angle = 0.0
        self._drag_diag = 50.0
        self._drag_fontsize = 72.0
        self._drag_iscale = 0.5
        self._drag_box_w = 1.0
        self._drag_box_h = 1.0

        self._placeholder = QLabel("Drop a PDF to preview")
        self._placeholder.setObjectName("ToolsHint")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addWidget(self._placeholder)

    @property
    def state(self) -> WatermarkOverlayState:
        return self._state

    @property
    def page_index(self) -> int:
        return self._page_index

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def page_size(self) -> tuple[float, float]:
        return self._page_w, self._page_h

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    def set_host_size(self, width: int, height: int) -> None:
        self._host_w = max(1, int(width))
        self._host_h = max(1, int(height))
        self._update_canvas_size()
        self.update()

    def set_zoom_factor(self, factor: float) -> None:
        z = max(_MIN_ZOOM, min(_MAX_ZOOM, float(factor)))
        if abs(z - self._zoom) < 1e-6:
            return
        self._zoom = z
        self._update_canvas_size()
        self._schedule_render()
        self.zoom_changed.emit(self._zoom)
        self.update()

    def zoom_by(self, delta: float) -> None:
        self.set_zoom_factor(self._zoom + delta)

    def reset_zoom(self) -> None:
        self.set_zoom_factor(1.0)

    def set_state(self, state: WatermarkOverlayState) -> None:
        self._state = state
        self.update()

    def update_state(self, **kwargs: object) -> None:
        self._state = replace(self._state, **kwargs)  # type: ignore[arg-type]
        self.update()

    def clear_source(self) -> None:
        self._cancel_render()
        self._path = None
        self._passwords = None
        self._page_index = 0
        self._page_count = 0
        self._page_pix = QPixmap()
        self._zoom = 1.0
        self._render_width_px = _PREVIEW_WIDTH_PX
        self._placeholder.show()
        self._update_canvas_size()
        self.zoom_changed.emit(self._zoom)
        self.update()

    def set_source(
        self,
        path: str,
        *,
        page_count: int,
        page_index: int = 0,
        password: str | None = None,
    ) -> None:
        self._path = path
        self._passwords = {path: password} if password is not None else None
        self._page_count = max(1, page_count)
        self._page_index = max(0, min(page_index, self._page_count - 1))
        self._placeholder.hide()
        self._schedule_render()

    def set_page(self, page_index: int) -> None:
        if self._path is None or self._page_count <= 0:
            return
        idx = max(0, min(int(page_index), self._page_count - 1))
        if idx == self._page_index:
            return
        self._page_index = idx
        self.page_changed.emit(idx)
        self._schedule_render()

    def _cancel_render(self) -> None:
        self._generation += 1
        self._timer.stop()

    def _schedule_render(self) -> None:
        self._timer.start()

    def _is_cancelled(self, generation: int) -> bool:
        return generation != self._generation

    def _target_render_width(self) -> int:
        return min(
            MAX_RENDER_WIDTH_PX,
            max(_PREVIEW_WIDTH_PX, int(_PREVIEW_WIDTH_PX * self._zoom)),
        )

    def _start_render(self) -> None:
        if not self._path:
            return
        self._generation += 1
        gen = self._generation
        width_px = self._target_render_width()
        self._render_width_px = width_px
        worker = WatermarkPageRenderWorker(
            self._path,
            self._page_index,
            width_px,
            gen,
            self._is_cancelled,
            passwords=self._passwords,
        )
        worker.signals.finished.connect(self._on_render_finished)
        worker.signals.error.connect(self._on_render_error)
        self._pool.start(worker)

    def _on_render_finished(
        self, generation: int, png: bytes, page_w: float, page_h: float
    ) -> None:
        if generation != self._generation:
            return
        pix = QPixmap()
        pix.loadFromData(png)
        self._page_pix = pix
        self._page_w = max(page_w, 1.0)
        self._page_h = max(page_h, 1.0)
        self.geometry_ready.emit(self._page_w, self._page_h)
        self._update_canvas_size()
        self.update()

    def _on_render_error(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self.render_error.emit(message)

    def _fit_scale(self) -> float:
        if self._page_pix.isNull():
            return 1.0
        margin = 8.0
        avail_w = max(1.0, self._host_w - 2 * margin)
        avail_h = max(1.0, self._host_h - 2 * margin)
        pw, ph = float(self._page_pix.width()), float(self._page_pix.height())
        return min(avail_w / pw, avail_h / ph)

    def _update_canvas_size(self) -> None:
        if self._page_pix.isNull():
            self.setMinimumSize(max(240, self._host_w), max(280, self._host_h))
            return
        margin = 8.0
        pw, ph = float(self._page_pix.width()), float(self._page_pix.height())
        scale = self._fit_scale() * self._zoom
        need_w = int(math.ceil(pw * scale + 2 * margin))
        need_h = int(math.ceil(ph * scale + 2 * margin))
        if self._zoom > 1.0 + 1e-6:
            self.setMinimumSize(max(self._host_w, need_w), max(self._host_h, need_h))
        else:
            self.setMinimumSize(self._host_w, self._host_h)

    def _page_display_rect(self) -> QRectF:
        if self._page_pix.isNull():
            return QRectF()
        pw, ph = float(self._page_pix.width()), float(self._page_pix.height())
        scale = self._fit_scale() * self._zoom
        w, h = pw * scale, ph * scale
        x = (self.width() - w) / 2
        y = (self.height() - h) / 2
        return QRectF(x, y, w, h)

    def _page_to_widget(self, px: float, py: float) -> QPointF:
        dr = self._page_display_rect()
        if dr.isEmpty():
            return QPointF()
        return QPointF(
            dr.x() + (px / self._page_w) * dr.width(),
            dr.y() + (py / self._page_h) * dr.height(),
        )

    def _widget_to_page(self, pt: QPointF) -> tuple[float, float]:
        dr = self._page_display_rect()
        if dr.isEmpty():
            return 0.0, 0.0
        nx = (pt.x() - dr.x()) / max(dr.width(), 1e-6)
        ny = (pt.y() - dr.y()) / max(dr.height(), 1e-6)
        return nx * self._page_w, ny * self._page_h

    def _box_pts(self) -> tuple[float, float, float, float]:
        """Unrotated box center + size in PDF points → (cx, cy, w, h)."""
        w, h = _overlay_size_pts(self._state, self._page_w, self._page_h)
        cx = self._state.center_x * self._page_w
        cy = self._state.center_y * self._page_h
        return cx, cy, max(w, 4.0), max(h, 4.0)

    def _box_widget_rect(self) -> QRectF:
        cx, cy, w, h = self._box_pts()
        tl = self._page_to_widget(cx - w / 2, cy - h / 2)
        br = self._page_to_widget(cx + w / 2, cy + h / 2)
        return QRectF(tl, br).normalized()

    def _rotate_handle_pos(self) -> QPointF:
        wr = self._box_widget_rect()
        c = wr.center()
        # Handle sits above unrotated box top-center, then rotate with angle.
        local = QPointF(0.0, -wr.height() / 2 - _ROTATE_OFFSET)
        rad = math.radians(self._state.angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        return QPointF(
            c.x() + local.x() * cos_a - local.y() * sin_a,
            c.y() + local.x() * sin_a + local.y() * cos_a,
        )

    def _hit_test(self, pos: QPointF) -> str | None:
        if self._page_pix.isNull():
            return None
        rh = self._rotate_handle_pos()
        if (pos - rh).manhattanLength() <= _HANDLE_PX + 4:
            return "rotate"
        wr = self._box_widget_rect()
        # Transform pos into unrotated box space for handle hits.
        c = wr.center()
        rad = math.radians(-self._state.angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        local = QPointF(dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a)
        local_pos = c + local
        handle = _hit_resize_handle(wr, local_pos)
        if handle:
            return handle
        # Point-in-rotated-rect via local bounds.
        half_w, half_h = wr.width() / 2, wr.height() / 2
        if abs(local.x()) <= half_w and abs(local.y()) <= half_h:
            return "move"
        return None

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._page_pix.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        dr = self._page_display_rect()
        painter.drawPixmap(dr.toRect(), self._page_pix)

        cx, cy, bw, bh = self._box_pts()
        center = self._page_to_widget(cx, cy)
        # Scale PDF-pt size to widget pixels.
        sx = dr.width() / self._page_w
        sy = dr.height() / self._page_h
        ww, wh = bw * sx, bh * sy

        painter.save()
        painter.translate(center)
        painter.rotate(self._state.angle)
        opacity = max(0.05, min(1.0, self._state.opacity))
        painter.setOpacity(opacity)

        if self._state.kind == "image" and self._state.image_path:
            if self._image_cache_path != self._state.image_path:
                self._image_cache = QPixmap(self._state.image_path)
                self._image_cache_path = self._state.image_path
            if not self._image_cache.isNull():
                target = QRectF(-ww / 2, -wh / 2, ww, wh)
                painter.drawPixmap(target.toRect(), self._image_cache)
        else:
            r, g, b = self._state.color
            color = QColor(int(r * 255), int(g * 255), int(b * 255))
            font = QFont("Helvetica")
            if self._state.size_mode == "diagonal":
                _w, _h, fs = watermark_text_box(
                    self._state.text,
                    page_width=self._page_w,
                    page_height=self._page_h,
                    diagonal_percent=self._state.diagonal_percent,
                )
            else:
                _w, _h, fs = watermark_text_box(
                    self._state.text,
                    page_width=self._page_w,
                    page_height=self._page_h,
                    fontsize=max(4.0, self._state.fontsize),
                )
            font.setPixelSize(max(8, int(round(fs * sy))))
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(
                QRectF(-ww / 2, -wh / 2, ww, wh),
                int(Qt.AlignmentFlag.AlignCenter),
                self._state.text or " ",
            )

        painter.setOpacity(1.0)
        # Selection chrome in local (unrotated) space.
        box = QRectF(-ww / 2, -wh / 2, ww, wh)
        _paint_resize_handles(painter, box)
        # Rotate stem + handle.
        top = QPointF(0.0, -wh / 2)
        rh = QPointF(0.0, -wh / 2 - _ROTATE_OFFSET)
        painter.setPen(QPen(accent_qcolor(), 1, Qt.PenStyle.DashLine))
        painter.drawLine(top, rh)
        painter.setBrush(on_accent_qcolor())
        painter.setPen(QPen(accent_qcolor(), 1))
        painter.drawEllipse(rh, _HANDLE_PX / 2, _HANDLE_PX / 2)
        painter.restore()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._hit_test(event.position())
        if not hit:
            return
        self._drag_mode = hit
        self._drag_origin = event.position()
        self._drag_center = (self._state.center_x, self._state.center_y)
        self._drag_angle = self._state.angle
        self._drag_diag = self._state.diagonal_percent
        self._drag_fontsize = self._state.fontsize
        self._drag_iscale = self._state.image_scale
        _, _, self._drag_box_w, self._drag_box_h = self._box_pts()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_mode is None:
            hit = self._hit_test(event.position())
            if hit == "rotate":
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif hit == "move":
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            elif hit in {"n", "s"}:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif hit in {"e", "w"}:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif hit in {"nw", "se"}:
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif hit in {"ne", "sw"}:
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        pos = event.position()
        if self._drag_mode == "move":
            ox, oy = self._widget_to_page(self._drag_origin)
            nx, ny = self._widget_to_page(pos)
            dx = (nx - ox) / self._page_w
            dy = (ny - oy) / self._page_h
            cx = max(0.0, min(1.0, self._drag_center[0] + dx))
            cy = max(0.0, min(1.0, self._drag_center[1] + dy))
            self._state = replace(self._state, center_x=cx, center_y=cy)
            self.update()
            self.placement_changed.emit(cx, cy)
        elif self._drag_mode == "rotate":
            c = self._box_widget_rect().center()
            a0 = math.degrees(
                math.atan2(
                    self._drag_origin.y() - c.y(),
                    self._drag_origin.x() - c.x(),
                )
            )
            a1 = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x()))
            angle = self._drag_angle + (a1 - a0)
            # Normalize to [-180, 180]
            while angle > 180:
                angle -= 360
            while angle < -180:
                angle += 360
            self._state = replace(self._state, angle=angle)
            self.update()
            self.angle_changed.emit(angle)
        else:
            # Scale from corner/edge — uniform via diagonal distance from center.
            c = self._box_widget_rect().center()
            d0 = math.hypot(
                self._drag_origin.x() - c.x(), self._drag_origin.y() - c.y()
            )
            d1 = math.hypot(pos.x() - c.x(), pos.y() - c.y())
            if d0 < 1e-3:
                return
            factor = max(0.05, d1 / d0)
            if self._state.size_mode == "diagonal":
                diag = max(
                    _MIN_DIAG_PCT,
                    min(_MAX_DIAG_PCT, self._drag_diag * factor),
                )
                self._state = replace(self._state, diagonal_percent=diag)
            elif self._state.kind == "image":
                scale = max(0.05, min(1.0, self._drag_iscale * factor))
                self._state = replace(self._state, image_scale=scale)
            else:
                fs = max(4.0, min(400.0, self._drag_fontsize * factor))
                self._state = replace(self._state, fontsize=fs)
            self.update()
            self.size_changed.emit()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_mode = None
            event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        self.zoom_by(_ZOOM_STEP if delta > 0 else -_ZOOM_STEP)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_0
        ):
            self.reset_zoom()
            event.accept()
            return
        super().keyPressEvent(event)


def _hit_resize_handle(wr: QRectF, pos: QPointF, handle_px: float = _HANDLE_PX) -> str | None:
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
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(accent_qcolor(), 1, Qt.PenStyle.DashLine))
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
    painter.setBrush(on_accent_qcolor())
    painter.setPen(QPen(accent_qcolor(), 1))
    for px, py in points:
        painter.drawRect(QRectF(px - hs / 2, py - hs / 2, hs, hs))
