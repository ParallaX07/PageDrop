from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QPixmap, QResizeEvent, QWheelEvent
from PyQt6.QtWidgets import QGridLayout, QLabel, QMenu, QScrollArea, QVBoxLayout, QWidget

import fitz

from pagedrop.core.page_extractor import extract_pages_to_files
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
RENDER_POOL_DRAIN_MS = 3000


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
    extract_to_folder_requested = pyqtSignal()

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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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
        self._focused_index: int | None = None
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
        self._focused_index = 0 if total else None
        self.selection_manager.set_page_count(total)
        self._cards = [PageCard(i, self._container) for i in range(total)]
        for card in self._cards:
            card.set_card_width(self._card_width)
            card.set_drag_context(loader, self.selection_manager, self._temp_manager)
            width_mm, height_mm = loader.page_size_mm(card.page_index)
            card.set_page_tooltip(width_mm, height_mm)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self.preview_requested.emit)
            card.context_menu_requested.connect(self._on_card_context_menu)
        self._reflow_grid(force=True)
        self._update_focus_highlight()
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
        self._render_pool.waitForDone(RENDER_POOL_DRAIN_MS)
        self._clear_cards()
        self._loader = None
        self._last_clicked_index = None
        self._focused_index = None
        self.selection_manager.set_page_count(0)

    @property
    def thumbnail_width_px(self) -> int:
        return self._thumbnail_width_px

    @property
    def card_width(self) -> int:
        return self._card_width

    @property
    def focused_index(self) -> int | None:
        return self._focused_index

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reflow_grid()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._cards:
            super().keyPressEvent(event)
            return

        if self._focused_index is None:
            self._set_focused_index(0)
            event.accept()
            return

        cols = max(self._grid_cols, 1)
        idx = self._focused_index
        key = event.key()

        if key == Qt.Key.Key_Left:
            self._set_focused_index(max(0, idx - 1))
            event.accept()
        elif key == Qt.Key.Key_Right:
            self._set_focused_index(min(len(self._cards) - 1, idx + 1))
            event.accept()
        elif key == Qt.Key.Key_Up:
            self._set_focused_index(max(0, idx - cols))
            event.accept()
        elif key == Qt.Key.Key_Down:
            self._set_focused_index(min(len(self._cards) - 1, idx + cols))
            event.accept()
        elif key in (Qt.Key.Key_Space, Qt.Key.Key_Select):
            self.selection_manager.toggle(idx)
            event.accept()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self._show_context_menu(event.globalPos())
        event.accept()

    def _on_card_context_menu(self, page_index: int, global_pos) -> None:
        if page_index not in self.selection_manager.selection:
            self.selection_manager.select_single(page_index)
            self._last_clicked_index = page_index
        self._set_focused_index(page_index)
        self._show_context_menu(global_pos)

    def _show_context_menu(self, global_pos) -> None:
        menu = QMenu(self)
        extract_action = menu.addAction("Extract selected pages to folder…")
        has_pdf = self._loader is not None
        has_selection = bool(self.selection_manager.selection)
        extract_action.setEnabled(has_pdf and has_selection)

        if os.environ.get("QT_QPA_PLATFORM") == "offscreen" or os.environ.get(
            "PAGEDROP_TESTING"
        ):
            chosen = None
        else:
            chosen = menu.exec(global_pos)
        if chosen is extract_action:
            self.extract_to_folder_requested.emit()

    def extract_selected_to_folder(self, output_dir) -> list:
        """Write selected pages to *output_dir*; returns paths or raises."""
        if self._loader is None:
            return []
        page_indices = sorted(self.selection_manager.selection)
        if not page_indices:
            return []
        base_name = Path(self._loader.path).stem
        return extract_pages_to_files(
            self._loader.path,
            page_indices,
            output_dir,
            base_name,
        )

    def _set_focused_index(self, index: int) -> None:
        if not self._cards:
            self._focused_index = None
            return
        clamped = max(0, min(len(self._cards) - 1, index))
        if self._focused_index == clamped:
            return
        self._focused_index = clamped
        self._update_focus_highlight()
        self._scroll_to_focused_card()

    def _update_focus_highlight(self) -> None:
        for index, card in enumerate(self._cards):
            card.set_keyboard_focused(index == self._focused_index)

    def _scroll_to_focused_card(self) -> None:
        if self._focused_index is None or not self._cards:
            return
        card = self._cards[self._focused_index]
        self.ensureWidgetVisible(card, 24, 24)

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
        self._set_focused_index(page_index)
        self.setFocus()

    def _on_selection_changed(self, selection: set[int]) -> None:
        for index, card in enumerate(self._cards):
            card.set_selected(index in selection)
        self.selection_changed.emit(selection)
