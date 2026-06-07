from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QResizeEvent, QWheelEvent
from PyQt6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

import fitz

from pagedrop.core.pdf_loader import PdfLoader, render_page_png
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.ui.page_card import PageCard
from pagedrop.ui.theme import (
    CARD_PADDING,
    CARD_WIDTH,
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_THUMBNAIL_WIDTH,
    MIN_THUMBNAIL_WIDTH,
    ZOOM_WHEEL_STEP,
)
from pagedrop.utils.temp_manager import TempManager

ZOOM_RENDER_DEBOUNCE_MS = 400


class ThumbnailWorker(QRunnable):
    class Signals(QObject):
        page_ready = pyqtSignal(int, int, QPixmap)  # generation, page_index, pixmap
        finished = pyqtSignal(int)  # generation
        error = pyqtSignal(int, str)  # generation, message

    def __init__(
        self,
        path: str,
        total_pages: int,
        generation: int,
        width_px: int,
        is_cancelled: Callable[[int], bool],
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._path = path
        self._total_pages = total_pages
        self._generation = generation
        self._width_px = width_px
        self._is_cancelled = is_cancelled
        self.setAutoDelete(True)

    def run(self) -> None:
        doc = None
        try:
            doc = fitz.open(self._path)
            for i in range(self._total_pages):
                if self._is_cancelled(self._generation):
                    return
                png = render_page_png(doc, i, width_px=self._width_px)
                if self._is_cancelled(self._generation):
                    return
                pix = QPixmap()
                pix.loadFromData(png, "PNG")
                self.signals.page_ready.emit(self._generation, i, pix)
            if not self._is_cancelled(self._generation):
                self.signals.finished.emit(self._generation)
        except Exception as exc:
            if not self._is_cancelled(self._generation):
                self.signals.error.emit(self._generation, str(exc))
        finally:
            if doc is not None:
                doc.close()


class ThumbnailGrid(QScrollArea):
    rendering_started = pyqtSignal(int)
    rendering_progress = pyqtSignal(int, int)
    rendering_finished = pyqtSignal()
    rendering_error = pyqtSignal(str)
    selection_changed = pyqtSignal(set)
    preview_requested = pyqtSignal(int)
    zoom_changed = pyqtSignal(int)

    def __init__(
        self,
        parent: QWidget | None = None,
        temp_manager: TempManager | None = None,
    ) -> None:
        super().__init__(parent)
        self._temp_manager = temp_manager or TempManager()
        self.setObjectName("ThumbnailGrid")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        self._container = QWidget()
        self._container.setObjectName("ThumbnailContainer")
        self._layout = QGridLayout(self._container)
        self._layout.setSpacing(12)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        self._empty_state = QWidget()
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(4)

        self._empty_title = QLabel("No document open")
        self._empty_title.setObjectName("GridEmptyState")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_hint = QLabel("Use File → Open PDF or the toolbar button to begin")
        self._empty_hint.setObjectName("GridEmptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_layout.addWidget(self._empty_title)
        empty_layout.addWidget(self._empty_hint)
        self._layout.addWidget(self._empty_state, 0, 0, 1, 1)

        self.setWidget(self._container)

        self._cards: list[PageCard] = []
        self._loader: PdfLoader | None = None
        self._thumbnail_width_px = DEFAULT_THUMBNAIL_WIDTH
        self._card_width = CARD_WIDTH
        self._last_rendered_width_px = 0
        self._grid_cols = 0
        self._generation = 0
        self._silent_render = False
        self._render_pool = QThreadPool(self)
        self._render_pool.setMaxThreadCount(1)
        self._zoom_render_timer = QTimer(self)
        self._zoom_render_timer.setSingleShot(True)
        self._zoom_render_timer.setInterval(ZOOM_RENDER_DEBOUNCE_MS)
        self._zoom_render_timer.timeout.connect(self._render_zoom_quality)
        self._last_clicked_index: int | None = None
        self.selection_manager = SelectionManager(
            on_selection_changed=self._on_selection_changed,
        )

    def load_pdf(self, loader: PdfLoader) -> None:
        self._cancel_rendering()
        self._clear_cards()
        self._loader = loader
        self._last_rendered_width_px = 0

        total = loader.page_count
        self._last_clicked_index = None
        self.selection_manager.set_page_count(total)
        self._cards = [PageCard(i, self._container) for i in range(total)]
        for card in self._cards:
            card.set_card_width(self._card_width)
            card.set_drag_context(loader, self.selection_manager, self._temp_manager)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self.preview_requested.emit)
        self._reflow_grid(force=True)
        self._start_rendering(silent=False)

    def _start_rendering(self, *, silent: bool) -> None:
        if self._loader is None:
            return

        self._generation += 1
        self._silent_render = silent
        generation = self._generation
        total = self._loader.page_count
        worker = ThumbnailWorker(
            self._loader.path,
            total,
            generation,
            self._thumbnail_width_px,
            self._is_cancelled,
        )
        worker.signals.page_ready.connect(self._on_page_ready)
        worker.signals.finished.connect(self._on_rendering_finished)
        worker.signals.error.connect(self._on_rendering_error)
        if not silent:
            self.rendering_started.emit(total)
        self._render_pool.start(worker)

    def _schedule_zoom_rerender(self) -> None:
        if self._last_rendered_width_px >= self._thumbnail_width_px:
            return
        self._zoom_render_timer.start()

    def _render_zoom_quality(self) -> None:
        if self._loader is None:
            return
        if self._last_rendered_width_px >= self._thumbnail_width_px:
            return
        self._start_rendering(silent=True)

    def cancel_rendering(self) -> None:
        """Invalidate the current render generation (e.g. before opening another PDF)."""
        self._cancel_rendering()

    def clear(self) -> None:
        self._zoom_render_timer.stop()
        self._cancel_rendering()
        self._clear_cards()
        self._loader = None
        self._last_clicked_index = None
        self.selection_manager.set_page_count(0)

    @property
    def thumbnail_width_px(self) -> int:
        return self._thumbnail_width_px

    @property
    def card_width(self) -> int:
        return self._card_width

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reflow_grid()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return

        step = ZOOM_WHEEL_STEP if delta > 0 else -ZOOM_WHEEL_STEP
        new_width = self._thumbnail_width_px + step
        new_width = max(MIN_THUMBNAIL_WIDTH, min(MAX_THUMBNAIL_WIDTH, new_width))
        if new_width != self._thumbnail_width_px:
            self.set_thumbnail_zoom(new_width)
        event.accept()

    def set_thumbnail_zoom(self, thumbnail_width_px: int) -> None:
        clamped = max(
            MIN_THUMBNAIL_WIDTH,
            min(MAX_THUMBNAIL_WIDTH, thumbnail_width_px),
        )
        if clamped != self._thumbnail_width_px:
            self._apply_zoom(clamped)

    def zoom_by(self, step: int) -> None:
        self.set_thumbnail_zoom(self._thumbnail_width_px + step)

    def _apply_zoom(self, thumbnail_width_px: int) -> None:
        self._thumbnail_width_px = thumbnail_width_px
        self._card_width = thumbnail_width_px + CARD_PADDING
        for card in self._cards:
            card.set_card_width(self._card_width, fast=True)
        self._reflow_grid()
        self.zoom_changed.emit(self._thumbnail_width_px)
        self._schedule_zoom_rerender()

    def _cancel_rendering(self) -> None:
        self._zoom_render_timer.stop()
        self._generation += 1

    def _is_cancelled(self, generation: int) -> bool:
        return generation != self._generation

    def _clear_cards(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._layout.addWidget(self._empty_state, 0, 0, 1, 1)
        self._empty_state.show()

    def _update_empty_state(self) -> None:
        if self._cards:
            self._empty_state.hide()
        else:
            self._empty_state.show()

    def _reflow_grid(self, *, force: bool = False) -> None:
        if not self._cards:
            self._grid_cols = 0
            self._update_empty_state()
            return

        spacing = self._layout.spacing()
        margins = self._layout.contentsMargins()
        available = self.viewport().width() - margins.left() - margins.right()
        cols = max(
            1,
            available // (self._card_width + spacing),
        )

        if not force and cols == self._grid_cols:
            return

        self._grid_cols = cols
        while self._layout.count():
            self._layout.takeAt(0)

        for index, card in enumerate(self._cards):
            self._layout.addWidget(card, index // cols, index % cols)

        self._update_empty_state()

    def _on_page_ready(
        self, generation: int, page_index: int, pixmap: QPixmap
    ) -> None:
        if self._is_cancelled(generation):
            return
        self._cards[page_index].set_thumbnail(pixmap)
        if not self._silent_render:
            self.rendering_progress.emit(page_index + 1, len(self._cards))

    def _on_rendering_finished(self, generation: int) -> None:
        if self._is_cancelled(generation):
            return
        self._last_rendered_width_px = self._thumbnail_width_px
        if not self._silent_render:
            self.rendering_finished.emit()

    def _on_rendering_error(self, generation: int, message: str) -> None:
        if self._is_cancelled(generation):
            return
        self.rendering_error.emit(message)

    def _on_card_clicked(
        self, page_index: int, modifiers: Qt.KeyboardModifier
    ) -> None:
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            anchor = (
                self._last_clicked_index
                if self._last_clicked_index is not None
                else page_index
            )
            self.selection_manager.select_range(anchor, page_index)
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            self.selection_manager.toggle(page_index)
        else:
            self.selection_manager.select_single(page_index)
        self._last_clicked_index = page_index

    def _on_selection_changed(self, selection: set[int]) -> None:
        for index, card in enumerate(self._cards):
            card.set_selected(index in selection)
        self.selection_changed.emit(selection)
