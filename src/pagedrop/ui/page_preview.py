from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QPixmap, QResizeEvent, QShowEvent, QWheelEvent
from PyQt6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import fitz

from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX, PdfLoader, render_page_png
from pagedrop.ui.busy_overlay import BusyOverlay
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    MIN_PREVIEW_RENDER_WIDTH,
    ZOOM_WHEEL_STEP,
)

PREVIEW_RENDER_DEBOUNCE_MS = 150


class PreviewRenderWorker(QRunnable):
    class Signals(QObject):
        finished = pyqtSignal(int, int, int, bytes)  # generation, logical_page, width, png
        error = pyqtSignal(int, str)

    def __init__(
        self,
        source_path: str,
        source_index: int,
        logical_page: int,
        width_px: int,
        generation: int,
        is_cancelled: Callable[[int], bool],
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._source_path = source_path
        self._source_index = source_index
        self._logical_page = logical_page
        self._width_px = width_px
        self._generation = generation
        self._is_cancelled = is_cancelled
        self.setAutoDelete(True)

    def run(self) -> None:
        doc = None
        try:
            if self._is_cancelled(self._generation):
                return
            doc = fitz.open(self._source_path)
            if self._is_cancelled(self._generation):
                return
            png = render_page_png(doc, self._source_index, width_px=self._width_px)
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
                self.signals.error.emit(self._generation, str(exc))
        finally:
            if doc is not None:
                doc.close()


class _PreviewScrollArea(QScrollArea):
    """Scroll area that zooms the preview on Ctrl+scroll."""

    def __init__(self, preview: PagePreviewWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview = preview

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return

        step = ZOOM_WHEEL_STEP * max(1, self._preview.render_width_px // DEFAULT_THUMBNAIL_WIDTH)
        zoom_delta = step if delta > 0 else -step
        self._preview.zoom_by(zoom_delta)
        event.accept()


class PagePreviewWidget(QWidget):
    """Single-page preview pane with arrow-key navigation."""

    page_changed = pyqtSignal(int)
    closed = pyqtSignal()
    busy_changed = pyqtSignal(bool, str)
    render_error = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: PdfEditModel | None = None
        self._get_loader: Callable[[str], PdfLoader] | None = None
        self._current_page = 0
        self._render_width_px = 1200
        self._manual_zoom = False
        self._generation = 0
        self._render_pool = QThreadPool(self)
        self._render_pool.setMaxThreadCount(1)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(PREVIEW_RENDER_DEBOUNCE_MS)
        self._render_timer.timeout.connect(self._start_render)

        self.setObjectName("PagePreview")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scroll = _PreviewScrollArea(self)
        self._scroll.setObjectName("PagePreviewScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._image_label = QLabel()
        self._image_label.setObjectName("PagePreviewImage")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll.setWidget(self._image_label)
        self._scroll.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._scroll, stretch=1)

        self._overlay = BusyOverlay(self._scroll.viewport())

        self._footer = QWidget()
        self._footer.setObjectName("PreviewFooter")
        footer_layout = QVBoxLayout(self._footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)

        self._hint_label = QLabel(
            "← → or ↑ ↓ change page  ·  Ctrl+scroll zoom  ·  Ctrl+0 fit width  ·  Esc back to grid"
        )
        self._hint_label.setObjectName("PagePreviewHint")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_layout.addWidget(self._hint_label)
        layout.addWidget(self._footer)

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def render_width_px(self) -> int:
        return self._render_width_px

    def set_footer_hint(self, text: str) -> None:
        self._hint_label.setText(text)

    def set_model(
        self,
        model: PdfEditModel | None,
        get_loader: Callable[[str], PdfLoader] | None,
    ) -> None:
        self._cancel_render()
        self._model = model
        self._get_loader = get_loader
        if model is None:
            self._current_page = 0
            self._manual_zoom = False
            self._image_label.clear()

    def set_loader(self, loader: PdfLoader | None) -> None:
        """Convenience wrapper for tests — builds a single-source model."""
        if loader is None:
            self.set_model(None, None)
            return
        model = PdfEditModel(loader.path, loader.page_count)
        cache: dict[str, PdfLoader] = {loader.path: loader}

        def get_loader(path: str) -> PdfLoader:
            if path not in cache:
                cache[path] = PdfLoader(path)
            return cache[path]

        self.set_model(model, get_loader)

    def reset_zoom_to_fit(self) -> None:
        self._manual_zoom = False
        previous = self._render_width_px
        self._update_render_width()
        if self._model is not None and self._render_width_px != previous:
            self._schedule_render()

    def show_page(self, page_index: int) -> None:
        if self._model is None:
            return
        last = max(0, self._model.logical_count() - 1)
        self._current_page = max(0, min(page_index, last))
        self._update_render_width()
        self._schedule_render()

    def zoom_by(self, step: int) -> None:
        if self._model is None:
            return
        new_width = self._render_width_px + step
        new_width = max(
            MIN_PREVIEW_RENDER_WIDTH,
            min(MAX_RENDER_WIDTH_PX, new_width),
        )
        if new_width == self._render_width_px:
            return
        self._manual_zoom = True
        self._render_width_px = new_width
        self._schedule_render()

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
            previous_width = self._render_width_px
            self._update_render_width()
            if self._render_width_px != previous_width:
                self._schedule_render()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._go_to_page(self._current_page - 1)
            event.accept()
            return
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._go_to_page(self._current_page + 1)
            event.accept()
            return
        if (
            key == Qt.Key.Key_0
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.reset_zoom_to_fit()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.closed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _fit_render_width(self) -> int:
        viewport = self._scroll.viewport()
        available = max(viewport.width() - 32, MIN_PREVIEW_RENDER_WIDTH)
        return min(MAX_RENDER_WIDTH_PX, available)

    def _update_render_width(self) -> None:
        if not self._manual_zoom:
            self._render_width_px = self._fit_render_width()

    def _go_to_page(self, page_index: int) -> None:
        if self._model is None:
            return
        last = max(0, self._model.logical_count() - 1)
        clamped = max(0, min(page_index, last))
        if clamped == self._current_page:
            return
        self._current_page = clamped
        self._schedule_render()
        self.page_changed.emit(self._current_page)

    def _schedule_render(self) -> None:
        if self._model is None:
            return
        self._overlay.show_message("Rendering page…")
        self.busy_changed.emit(True, "Rendering page…")
        self._render_timer.start()

    def _start_render(self) -> None:
        if self._model is None or self._get_loader is None:
            return
        ref = self._model.page_at(self._current_page)
        self._generation += 1
        generation = self._generation
        worker = PreviewRenderWorker(
            ref.source_path,
            ref.source_index,
            self._current_page,
            self._render_width_px,
            generation,
            self._is_cancelled,
        )
        worker.signals.finished.connect(self._on_render_finished)
        worker.signals.error.connect(self._on_render_error)
        self._render_pool.start(worker)

    def _cancel_render(self) -> None:
        self._render_timer.stop()
        self._generation += 1
        self._overlay.hide_overlay()
        self.busy_changed.emit(False, "")

    def _is_cancelled(self, generation: int) -> bool:
        return generation != self._generation

    def _on_render_finished(
        self,
        generation: int,
        logical_page: int,
        width_px: int,
        png: bytes,
    ) -> None:
        if self._is_cancelled(generation):
            return
        if logical_page != self._current_page or width_px != self._render_width_px:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(png, "PNG")
        self._image_label.setPixmap(pixmap)
        self._image_label.adjustSize()
        self._overlay.hide_overlay()
        self.busy_changed.emit(False, "")

    def _on_render_error(self, generation: int, message: str) -> None:
        if self._is_cancelled(generation):
            return
        self._overlay.hide_overlay()
        self.busy_changed.emit(False, "")
        self._image_label.setText(f"Could not render page:\n{message}")
        self.render_error.emit(message)
