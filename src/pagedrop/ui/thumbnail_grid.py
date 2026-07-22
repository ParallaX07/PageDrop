from __future__ import annotations

import os
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QPoint,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import fitz

from pagedrop.assets import empty_state_logo_pixmap
from pagedrop.core.drag_mime import (
    INTERNAL_PAGE_MIME,
    PAGE_TRANSFER_MIME,
    decode_page_indices,
    decode_page_refs,
)
from pagedrop.core.page_extractor import extract_page_refs_to_files
from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_loader import PdfLoadError, PdfLoader, render_page_png
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.core.supported_formats import pdf_paths_from_mime
from pagedrop.ui.accessibility import prefers_reduce_motion
from pagedrop.ui.drag_autoscroll import DragAutoScroller
from pagedrop.ui.grid_helpers import (
    ctrl_wheel_zoom_step,
    drop_index_at_pos as insertion_index_at_pos,
    drop_indicator_rect,
)
from pagedrop.ui.page_card import PageCard
from pagedrop.ui.theme import (
    ACCENT,
    CARD_PADDING,
    CARD_WIDTH,
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_THUMBNAIL_WIDTH,
    MIN_THUMBNAIL_WIDTH,
    PAGE_NUMBER_OVERLAY_MIN_WIDTH,
    ZOOM_WHEEL_STEP,
)
from pagedrop.utils.list_utils import move_items
from pagedrop.utils.temp_manager import TempManager

ZOOM_RENDER_DEBOUNCE_MS = 400
SCROLL_RENDER_DEBOUNCE_MS = 150
RENDER_POOL_DRAIN_MS = 3000
VISIBLE_RENDER_BUFFER_ROWS = 2
DEFERRED_THUMBNAIL_BATCH = 24
LARGE_PDF_PAGE_THRESHOLD = 50
CARD_CREATE_BATCH = 32
DEFERRED_LAYOUT_BATCH = 48
SKELETON_PULSE_MS = 550


class ThumbnailWorker(QRunnable):
    class Signals(QObject):
        # PNG bytes — QPixmap is GUI-thread only (see PreviewRenderWorker).
        page_ready = pyqtSignal(int, int, bytes)  # generation, logical_index, png
        finished = pyqtSignal(int)  # generation
        error = pyqtSignal(int, str)  # generation, message

    def __init__(
        self,
        pages: list[tuple[int, PageRef]],
        generation: int,
        width_px: int,
        is_cancelled: Callable[[int], bool],
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._pages = pages
        self._generation = generation
        self._width_px = width_px
        self._is_cancelled = is_cancelled
        self.setAutoDelete(True)

    def run(self) -> None:
        # fitz.Document is not thread-safe — never share PdfTab._loader_cache
        # docs with this worker. One open per source path per run is enough; the open
        # cost is noise vs get_pixmap, and progressive batches cancel via generation.
        docs: dict[str, fitz.Document] = {}
        try:
            for logical_index, ref in self._pages:
                if self._is_cancelled(self._generation):
                    return
                if ref.source_path not in docs:
                    docs[ref.source_path] = fitz.open(ref.source_path)
                doc = docs[ref.source_path]
                png = render_page_png(
                    doc,
                    ref.source_index,
                    width_px=self._width_px,
                    rotation=ref.rotation,
                )
                if self._is_cancelled(self._generation):
                    return
                self.signals.page_ready.emit(self._generation, logical_index, png)
            if not self._is_cancelled(self._generation):
                self.signals.finished.emit(self._generation)
        except Exception as exc:
            if not self._is_cancelled(self._generation):
                self.signals.error.emit(self._generation, str(exc))
        finally:
            for doc in docs.values():
                doc.close()


@dataclass
class _CrossWindowMoveUndo:
    """Reverses a Shift+drop move while both undo stacks are still at capture depth."""

    source_grid: ThumbnailGrid
    target_grid: ThumbnailGrid
    blank_init: bool
    source_undo_depth: int
    target_undo_depth: int

    def still_valid(self) -> bool:
        source_model = self.source_grid._model
        if source_model is None or source_model.undo_depth() != self.source_undo_depth:
            return False
        if self.blank_init:
            target_tab = self.target_grid._parent_tab()
            return target_tab is not None and not target_tab.is_blank
        target_model = self.target_grid._model
        return (
            target_model is not None
            and target_model.undo_depth() == self.target_undo_depth
        )

    def undo(self) -> bool:
        if not self.still_valid():
            return False
        source_model = self.source_grid._model
        assert source_model is not None
        if not source_model.undo():
            return False
        self.source_grid.reload_from_model()
        source_tab = self.source_grid._parent_tab()
        if source_tab is not None:
            source_tab._sync_dirty_from_model()

        if self.blank_init:
            target_tab = self.target_grid._parent_tab()
            if target_tab is not None:
                target_tab.close_loader()
            return True

        target_model = self.target_grid._model
        assert target_model is not None
        if not target_model.undo():
            return False
        self.target_grid.reload_from_model()
        target_tab = self.target_grid._parent_tab()
        if target_tab is not None:
            target_tab._sync_dirty_from_model()
        return True


class ThumbnailGrid(QScrollArea):
    rendering_started = pyqtSignal(int)
    rendering_progress = pyqtSignal(int, int)
    rendering_finished = pyqtSignal()
    rendering_error = pyqtSignal(str)
    busy_changed = pyqtSignal(bool, str)
    selection_changed = pyqtSignal(set)
    preview_requested = pyqtSignal(int)
    zoom_changed = pyqtSignal(int)
    zoom_render_pending = pyqtSignal(bool)
    extract_to_folder_requested = pyqtSignal()
    extract_to_new_tab_requested = pyqtSignal()
    extract_to_new_window_requested = pyqtSignal()
    pages_reordered = pyqtSignal()
    pages_inserted = pyqtSignal(int, str, int)  # count, filename, 1-based position
    cross_window_pages_inserted = pyqtSignal(int, str)  # count, source filename
    pages_moved_out = pyqtSignal(int, str, object)  # count, target filename, undo callable|None
    pages_transferred_via_tab_bar = pyqtSignal(
        int, str, bool, object
    )  # count, target filename, moved, undo callable|None
    page_transfer_failed = pyqtSignal(str)
    pdf_drop_failed = pyqtSignal(object)
    open_pdfs_requested = pyqtSignal(list)  # blank-tab file-manager drops

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
        self.setAcceptDrops(True)

        self._container = QWidget()
        self._container.setObjectName("ThumbnailContainer")
        self._layout = QGridLayout(self._container)
        self._layout.setSpacing(12)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        self._empty_state = QWidget()
        self._empty_state.setObjectName("EmptyStatePanel")
        self._empty_state.setAccessibleName("No document open")
        self._empty_state.setAccessibleDescription(
            "Choose a file or drop one onto the grid"
        )
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(6)
        empty_layout.setContentsMargins(32, 48, 32, 48)

        self._empty_logo = QLabel()
        self._empty_logo.setObjectName("GridEmptyLogo")
        self._empty_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_logo.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._empty_logo.setAccessibleName("PageDrop logo")
        self._refresh_empty_logo()

        self._empty_title = QLabel("No document open")
        self._empty_title.setObjectName("GridEmptyState")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_hint = QLabel("Choose a file or drop one onto the grid")
        self._empty_hint.setObjectName("GridEmptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)

        self._empty_kbd = QLabel("Ctrl+O open  ·  Ctrl+A select all  ·  drag pages to export")
        self._empty_kbd.setObjectName("GridEmptyKbd")
        self._empty_kbd.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_layout.addWidget(self._empty_logo)
        empty_layout.addWidget(self._empty_title)
        empty_layout.addWidget(self._empty_hint)
        empty_layout.addWidget(self._empty_kbd)
        self._layout.addWidget(self._empty_state, 0, 0, 1, 1)

        self.setWidget(self._container)

        self._cards: list[PageCard] = []
        self._model: PdfEditModel | None = None
        self._get_loader: Callable[[str], PdfLoader] | None = None
        self._thumbnail_width_px = DEFAULT_THUMBNAIL_WIDTH
        self._card_width = CARD_WIDTH
        self._page_render_width: list[int] = []
        self._last_rendered_width_px = 0
        self._grid_cols = 0
        # session flag only — resize does not re-fit (upgrade: optional live fit).
        self._manual_zoom = False
        self._generation = 0
        self._silent_render = False
        self._progress_active = False
        self._render_pool = QThreadPool(self)
        self._render_pool.setMaxThreadCount(1)
        # Keep Signals QObjects alive until drain; autoDelete drops the QRunnable.
        self._worker_signals: list[ThumbnailWorker.Signals] = []
        self._zoom_render_timer = QTimer(self)
        self._zoom_render_timer.setSingleShot(True)
        self._zoom_render_timer.setInterval(ZOOM_RENDER_DEBOUNCE_MS)
        self._zoom_render_timer.timeout.connect(self._render_zoom_quality)
        self._scroll_render_timer = QTimer(self)
        self._scroll_render_timer.setSingleShot(True)
        self._scroll_render_timer.setInterval(SCROLL_RENDER_DEBOUNCE_MS)
        self._scroll_render_timer.timeout.connect(self._render_visible_quality)
        self._background_render_timer = QTimer(self)
        self._background_render_timer.setSingleShot(True)
        self._background_render_timer.setInterval(200)
        self._background_render_timer.timeout.connect(self._render_background_quality)
        self._deferred_thumbnail_timer = QTimer(self)
        self._deferred_thumbnail_timer.setSingleShot(True)
        self._deferred_thumbnail_timer.timeout.connect(
            self._process_deferred_thumbnail_refresh
        )
        self._pending_thumbnail_refresh: list[int] = []
        self._pending_card_indices: list[int] = []
        self._card_create_timer = QTimer(self)
        self._card_create_timer.setSingleShot(True)
        self._card_create_timer.timeout.connect(self._process_card_creation_batch)
        self._deferred_layout_timer = QTimer(self)
        self._deferred_layout_timer.setSingleShot(True)
        self._deferred_layout_timer.timeout.connect(self._process_deferred_layout_batch)
        self._pending_layout_indices: list[int] = []
        self._busy_reasons: set[str] = set()
        self._busy_message = ""
        self._busy_render_generation = -1
        self._busy_render_width = 0
        self._skeleton_pulse_dim = False
        self._skeleton_pulse_timer = QTimer(self)
        self._skeleton_pulse_timer.setInterval(SKELETON_PULSE_MS)
        self._skeleton_pulse_timer.timeout.connect(self._pulse_skeleton_cards)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self.horizontalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self._last_clicked_index: int | None = None
        self._focused_index: int | None = None
        self._drop_insertion_index: int | None = None
        self._drop_indicator = QFrame(self._container)
        self._drop_indicator.setObjectName("DropIndicator")
        self._drop_indicator.setStyleSheet(
            f"background-color: {ACCENT}; border: none; border-radius: 1px;"
        )
        self._drop_indicator.setFixedWidth(3)
        self._drop_indicator.hide()
        self._drag_autoscroller = DragAutoScroller(self)
        self._drag_autoscroller.set_scroll_callback(self._on_drag_autoscroll)
        self._drag_over_grid = False
        self._drag_filter_installed = False
        self.selection_manager = SelectionManager(
            on_selection_changed=self._on_selection_changed,
        )

    def set_empty_state_message(
        self,
        title: str,
        *,
        hint: str | None = None,
        show_hint: bool = True,
        show_shortcuts: bool = True,
    ) -> None:
        self._empty_title.setText(title)
        self._empty_state.setAccessibleName(title)
        if hint is not None:
            self._empty_hint.setText(hint)
            self._empty_state.setAccessibleDescription(hint)
        if show_hint:
            self._empty_hint.show()
        else:
            self._empty_hint.hide()
        if show_shortcuts:
            self._empty_kbd.show()
        else:
            self._empty_kbd.hide()

    def load_model(
        self,
        model: PdfEditModel,
        get_loader: Callable[[str], PdfLoader],
    ) -> None:
        self.cancel_rendering()
        self._clear_cards()
        self._model = model
        self._get_loader = get_loader
        self._last_rendered_width_px = 0

        total = model.logical_count()
        self._page_render_width = [0] * total
        self._last_clicked_index = None
        self._focused_index = 0 if total else None
        self.selection_manager.set_page_count(total)

        if total <= LARGE_PDF_PAGE_THRESHOLD:
            self._create_all_cards(range(total))
            self._reflow_grid(force=True)
            self._update_focus_highlight()
            self._start_rendering(silent=False)
            return

        self._pending_card_indices = list(range(total))
        self._enter_busy("loading", f"Preparing {total} pages…")
        self.rendering_started.emit(total)
        self._card_create_timer.start(0)

    def load_pdf(self, loader: PdfLoader) -> None:
        """Convenience wrapper for tests — builds a single-source model."""
        model = PdfEditModel(loader.path, loader.page_count)
        cache: dict[str, PdfLoader] = {loader.path: loader}

        def get_loader(path: str) -> PdfLoader:
            if path not in cache:
                cache[path] = PdfLoader(path)
            return cache[path]

        self.load_model(model, get_loader)

    def reload_from_model(self) -> None:
        """Rebuild cards from the current model (e.g. after undo/redo)."""
        if self._model is None or self._get_loader is None:
            return
        total = self._model.logical_count()
        if total == 0:
            self.set_empty_state_message(
                "No pages in this document",
                hint="Open another PDF or add pages to continue",
                show_hint=True,
                show_shortcuts=False,
            )
        self.load_model(self._model, self._get_loader)

    def _create_all_cards(self, indices: range | list[int]) -> None:
        for i in indices:
            self._cards.append(self._make_page_card(i))
        self._start_skeleton_pulse()

    def _make_page_card(self, logical_index: int) -> PageCard:
        assert self._model is not None
        assert self._get_loader is not None
        card = PageCard(logical_index, self._container)
        card.set_card_width(self._card_width)
        card.set_drag_context(
            self._model, self.selection_manager, self._temp_manager
        )
        ref = self._model.page_at(logical_index)
        card.set_page_ref(ref)
        card.set_page_size_provider(lambda r=ref: self._page_size_mm_for(r))
        card.clicked.connect(self._on_card_clicked)
        card.double_clicked.connect(self.preview_requested.emit)
        card.context_menu_requested.connect(self._on_card_context_menu)
        card.set_page_overlay_visible(self._page_overlay_visible())
        return card

    def _page_size_mm_for(self, ref: PageRef) -> tuple[int, int]:
        assert self._get_loader is not None
        return self._get_loader(ref.source_path).page_size_mm(
            ref.source_index, rotation=ref.rotation
        )

    def _process_card_creation_batch(self) -> None:
        if self._model is None or not self._pending_card_indices:
            return

        batch = self._pending_card_indices[:CARD_CREATE_BATCH]
        self._pending_card_indices = self._pending_card_indices[CARD_CREATE_BATCH:]
        self._create_all_cards(batch)
        self._reflow_grid(force=len(self._cards) <= CARD_CREATE_BATCH)
        remaining = len(self._pending_card_indices)
        total = len(self._cards) + remaining
        created = len(self._cards)
        self._enter_busy("loading", f"Preparing pages ({created}/{total})…")
        self.rendering_progress.emit(created, total)

        if self._pending_card_indices:
            self._card_create_timer.start(0)
            return

        self._leave_busy("loading")
        self._update_focus_highlight()
        self._start_rendering(silent=False)

    def _start_rendering(
        self, *, silent: bool, page_indices: list[int] | None = None
    ) -> None:
        if self._model is None or self._get_loader is None:
            return

        if page_indices is None:
            page_indices = list(range(self._model.logical_count()))
        else:
            target = self._target_render_width()
            page_indices = [
                i
                for i in page_indices
                if 0 <= i < len(self._page_render_width)
                and self._page_render_width[i] < target
            ]

        if not page_indices:
            self._sync_rendered_width_state()
            self._maybe_continue_or_dismiss_progress()
            return

        page_indices = self._priority_render_order(page_indices)
        pages = [(i, self._model.page_at(i)) for i in page_indices]

        self._generation += 1
        self._silent_render = silent
        generation = self._generation
        render_width = self._target_render_width()
        self._busy_render_width = render_width
        worker = ThumbnailWorker(
            pages,
            generation,
            render_width,
            self._is_cancelled,
        )
        worker.signals.page_ready.connect(self._on_page_ready)
        worker.signals.finished.connect(self._on_rendering_finished)
        worker.signals.error.connect(self._on_rendering_error)
        self._worker_signals.append(worker.signals)
        self._busy_render_generation = generation
        if not silent:
            self._progress_active = True
            self._enter_busy("rendering", "Rendering thumbnails…")
            self.rendering_started.emit(len(page_indices))
        self._render_pool.start(worker)

    def _priority_render_order(self, page_indices: list[int]) -> list[int]:
        """Page 1 first, then visible pages, then the rest in order."""
        if not page_indices:
            return []
        index_set = set(page_indices)
        ordered: list[int] = []
        seen: set[int] = set()

        def _add(index: int) -> None:
            if index in index_set and index not in seen:
                ordered.append(index)
                seen.add(index)

        _add(0)
        visible = self._get_visible_page_indices()
        if not visible and self._cards:
            cols = max(self._grid_cols, 1)
            sample = self._cards[0]
            row_stride = max(sample.height() + self._layout.spacing(), 1)
            rows = max(1, self.viewport().height() // row_stride)
            rows += VISIBLE_RENDER_BUFFER_ROWS
            visible = list(range(min(len(self._cards), cols * rows)))
        for index in visible:
            _add(index)
        for index in page_indices:
            _add(index)
        return ordered

    def _schedule_zoom_rerender(self) -> None:
        if not self._pages_needing_render():
            return
        self.zoom_render_pending.emit(True)
        self._zoom_render_timer.start()

    def _render_zoom_quality(self) -> None:
        self.zoom_render_pending.emit(False)
        if self._model is None:
            return
        visible = self._visible_pages_needing_render()
        if not visible:
            needing = self._pages_needing_render()
            if not needing:
                return
            cols = max(self._grid_cols, 1)
            row_count = VISIBLE_RENDER_BUFFER_ROWS + 1
            visible = needing[: cols * row_count]
        self._start_rendering(silent=True, page_indices=visible)

    def _render_visible_quality(self) -> None:
        if self._model is None:
            return
        visible = self._visible_pages_needing_render()
        if visible:
            self._start_rendering(silent=True, page_indices=visible)

    def _render_background_quality(self) -> None:
        if self._model is None:
            return
        if self._render_pool.activeThreadCount() > 0:
            self._schedule_background_render()
            return
        background = self._background_pages_needing_render()
        if background:
            self._start_rendering(silent=True, page_indices=background)

    def _schedule_background_render(self) -> None:
        if not self._background_pages_needing_render():
            return
        self._background_render_timer.start()

    def _on_scroll_changed(self, _value: int) -> None:
        if self._model is None:
            return
        visible = self._get_visible_page_indices()
        for index in visible:
            if 0 <= index < len(self._cards):
                card = self._cards[index]
                card.apply_layout_width()
                if card._source_pixmap is not None:
                    card.refresh_thumbnail_display(fast=True)
        if self._pages_needing_render():
            if self._visible_pages_needing_render():
                self._scroll_render_timer.start()

    def has_pending_work(self) -> bool:
        """True when a load/render batch is still in flight."""
        return (
            self._busy_render_generation >= 0
            or self._progress_active
            or bool(self._busy_reasons)
            or self._card_create_timer.isActive()
            or bool(self._pending_card_indices)
        )

    def cancel_rendering(self) -> None:
        """Invalidate in-flight workers and drain the pool before teardown/reload."""
        self._cancel_rendering()
        self._drain_render_pool()

    def _drain_render_pool(self) -> None:
        self._render_pool.waitForDone(RENDER_POOL_DRAIN_MS)
        # Worker signals are queued to this object; flush them before cards go away.
        QCoreApplication.sendPostedEvents(self, QEvent.Type.MetaCall)
        self._worker_signals.clear()

    def clear(self) -> None:
        self._zoom_render_timer.stop()
        self._scroll_render_timer.stop()
        self._background_render_timer.stop()
        self._deferred_thumbnail_timer.stop()
        self._card_create_timer.stop()
        self._deferred_layout_timer.stop()
        self._pending_thumbnail_refresh.clear()
        self._pending_card_indices.clear()
        self._pending_layout_indices.clear()
        self._cancel_rendering()
        self._stop_skeleton_pulse()
        self._drain_render_pool()
        self._stop_drag_autoscroll()
        self._hide_drop_indicator()
        self._clear_cards()
        self._model = None
        self._get_loader = None
        self._page_render_width = []
        self._last_clicked_index = None
        self._focused_index = None
        self.selection_manager.set_page_count(0)
        self._busy_reasons.clear()
        self._busy_render_generation = -1
        self._progress_active = False
        self.zoom_render_pending.emit(False)
        self.busy_changed.emit(False, "")

    @property
    def thumbnail_width_px(self) -> int:
        return self._thumbnail_width_px

    @property
    def card_width(self) -> int:
        return self._card_width

    @property
    def focused_index(self) -> int | None:
        return self._focused_index

    def _refresh_empty_logo(self) -> None:
        pixmap = empty_state_logo_pixmap(self.devicePixelRatioF())
        if pixmap.isNull():
            self._empty_logo.clear()
        else:
            self._empty_logo.setPixmap(pixmap)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._refresh_empty_logo()

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
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                super().keyPressEvent(event)
                return
            self._set_focused_index(max(0, idx - cols))
            event.accept()
        elif key == Qt.Key.Key_Down:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                super().keyPressEvent(event)
                return
            self._set_focused_index(min(len(self._cards) - 1, idx + cols))
            event.accept()
        elif key in (Qt.Key.Key_Space, Qt.Key.Key_Select):
            self.selection_manager.toggle(idx)
            event.accept()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.preview_requested.emit(idx)
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
        has_pdf = self._model is not None
        has_selection = bool(self.selection_manager.selection)

        move_up_action = menu.addAction("Move up")
        move_up_action.setEnabled(has_pdf and self.can_move_selection_up())
        move_down_action = menu.addAction("Move down")
        move_down_action.setEnabled(has_pdf and self.can_move_selection_down())

        menu.addSeparator()

        duplicate_action = menu.addAction("Duplicate selected pages")
        duplicate_action.setEnabled(has_pdf and has_selection)
        rotate_cw_action = menu.addAction("Rotate clockwise")
        rotate_cw_action.setEnabled(has_pdf and has_selection)
        rotate_ccw_action = menu.addAction("Rotate counter-clockwise")
        rotate_ccw_action.setEnabled(has_pdf and has_selection)

        menu.addSeparator()

        delete_action = menu.addAction("Delete selected pages")
        delete_action.setEnabled(has_pdf and has_selection)

        menu.addSeparator()
        extract_action = menu.addAction("Extract selected pages to folder")
        extract_action.setEnabled(has_pdf and has_selection)
        extract_tab_action = menu.addAction("Extract selected to new tab")
        extract_tab_action.setEnabled(has_pdf and has_selection)
        extract_window_action = menu.addAction("Extract selected to new window")
        extract_window_action.setEnabled(has_pdf and has_selection)

        if os.environ.get("QT_QPA_PLATFORM") == "offscreen" or os.environ.get(
            "PAGEDROP_TESTING"
        ):
            chosen = None
        else:
            chosen = menu.exec(global_pos)
        if chosen is move_up_action:
            self.move_selection_up()
        elif chosen is move_down_action:
            self.move_selection_down()
        elif chosen is duplicate_action:
            tab = self._parent_tab()
            if tab is not None:
                tab.duplicate_selected_pages()
            else:
                self.duplicate_selected_pages()
        elif chosen is rotate_cw_action:
            tab = self._parent_tab()
            if tab is not None:
                tab.rotate_selected_pages(90)
            else:
                self.rotate_selected_pages(90)
        elif chosen is rotate_ccw_action:
            tab = self._parent_tab()
            if tab is not None:
                tab.rotate_selected_pages(-90)
            else:
                self.rotate_selected_pages(-90)
        elif chosen is delete_action:
            tab = self._parent_tab()
            if tab is not None:
                tab.delete_selected_pages()
            else:
                self.delete_selected_pages()
        elif chosen is extract_action:
            self.extract_to_folder_requested.emit()
        elif chosen is extract_tab_action:
            self.extract_to_new_tab_requested.emit()
        elif chosen is extract_window_action:
            self.extract_to_new_window_requested.emit()

    def can_move_selection_up(self) -> bool:
        if self._model is None:
            return False
        ordered = sorted(self.selection_manager.selection)
        return bool(ordered) and ordered[0] > 0

    def can_move_selection_down(self) -> bool:
        if self._model is None:
            return False
        ordered = sorted(self.selection_manager.selection)
        return bool(ordered) and ordered[-1] < self._model.logical_count() - 1

    def move_selection_up(self) -> bool:
        """Move selected pages up one position, preserving relative order."""
        if self._model is None or self._get_loader is None:
            return False
        ordered = sorted(self.selection_manager.selection)
        if not ordered or ordered[0] == 0:
            return False

        self._model.move_up(ordered)
        self._restore_after_reorder({index - 1 for index in ordered})
        return True

    def move_selection_down(self) -> bool:
        """Move selected pages down one position, preserving relative order."""
        if self._model is None or self._get_loader is None:
            return False
        ordered = sorted(self.selection_manager.selection)
        if not ordered or ordered[-1] >= self._model.logical_count() - 1:
            return False

        self._model.move_down(ordered)
        self._restore_after_reorder({index + 1 for index in ordered})
        return True

    def duplicate_selected_pages(self) -> int:
        """Insert copies of the selection after the last selected page."""
        if self._model is None or self._get_loader is None:
            return 0
        ordered = sorted(self.selection_manager.selection)
        if not ordered:
            return 0

        refs = [self._model.page_at(index) for index in ordered]
        insert_at = ordered[-1] + 1
        self._model.insert_pages(insert_at, refs)
        self._sync_grid_after_insert(insert_at, len(refs))
        new_selection = set(range(insert_at, insert_at + len(refs)))
        self.selection_manager.set_selection(new_selection)
        self._last_clicked_index = insert_at
        self._set_focused_index(insert_at)
        self.pages_reordered.emit()
        return len(refs)

    def rotate_selected_pages(self, delta_degrees: int) -> bool:
        """Rotate selected pages by *delta_degrees* (typically ±90)."""
        if self._model is None or self._get_loader is None:
            return False
        ordered = sorted(self.selection_manager.selection)
        if not ordered:
            return False

        self._model.rotate_pages(ordered, delta_degrees)
        self._reindex_cards()
        # Width cache would skip re-render; rotation changes the pixels.
        for index in ordered:
            if 0 <= index < len(self._page_render_width):
                self._page_render_width[index] = 0
        self._start_rendering(silent=True, page_indices=ordered)
        self.pages_reordered.emit()
        return True

    def _restore_after_reorder(self, new_selection: set[int]) -> None:
        self._sync_grid_after_reorder()
        self.selection_manager.set_selection(new_selection)
        if new_selection:
            anchor = min(new_selection)
            self._last_clicked_index = anchor
            self._set_focused_index(anchor)

    def _invalidate_render_generation(self) -> None:
        """Drop in-flight thumbnail callbacks without restarting a full render."""
        self._generation += 1
        self._busy_render_generation = -1
        self._leave_busy("rendering")
        # Keep _progress_active; callers that still owe work will restart.

    def _dismiss_progress(self) -> None:
        if not self._progress_active:
            return
        self._progress_active = False
        self.rendering_finished.emit()

    def _maybe_continue_or_dismiss_progress(self) -> None:
        """After a worker ends/no-ops, keep the bar alive until all pages are done."""
        if not self._progress_active:
            if self._pages_needing_render():
                self._schedule_background_render()
            return
        needing = self._pages_needing_render()
        if not needing:
            self._dismiss_progress()
            return
        if self._busy_render_generation >= 0:
            return
        # Remaining pages keep the same progress session (visible-first ordered).
        self._start_rendering(silent=True, page_indices=needing)

    def _remove_cards_at_indices(self, indices: list[int]) -> None:
        for idx in sorted(indices, reverse=True):
            card = self._cards.pop(idx)
            card.setParent(None)
            card.deleteLater()
            if idx < len(self._page_render_width):
                self._page_render_width.pop(idx)

    def _reindex_cards(self) -> None:
        assert self._model is not None
        assert self._get_loader is not None
        for index, card in enumerate(self._cards):
            ref = self._model.page_at(index)
            card.set_logical_index(index)
            card.set_page_ref(ref)
            card.set_page_size_provider(lambda r=ref: self._page_size_mm_for(r))

    def _reorder_cards_to_model(self) -> None:
        """Reorder existing cards to match the model without re-rendering."""
        assert self._model is not None
        assert self._get_loader is not None
        if not self._cards:
            return

        refs = [self._model.page_at(i) for i in range(self._model.logical_count())]
        card_pools: dict[PageRef, deque[PageCard]] = defaultdict(deque)
        width_pools: dict[PageRef, deque[int]] = defaultdict(deque)
        for card, width in zip(self._cards, self._page_render_width):
            ref = card.page_ref
            if ref is None:
                self.load_model(self._model, self._get_loader)
                return
            card_pools[ref].append(card)
            width_pools[ref].append(width)

        new_cards: list[PageCard] = []
        new_widths: list[int] = []
        for ref in refs:
            pool = card_pools.get(ref)
            if not pool:
                self.load_model(self._model, self._get_loader)
                return
            new_cards.append(pool.popleft())
            new_widths.append(width_pools[ref].popleft())

        self._cards = new_cards
        self._page_render_width = new_widths

    def _sync_grid_after_reorder(self) -> None:
        assert self._model is not None
        assert self._get_loader is not None
        if self._pending_card_indices:
            self.load_model(self._model, self._get_loader)
            return
        if len(self._cards) != self._model.logical_count():
            self.load_model(self._model, self._get_loader)
            return

        self._invalidate_render_generation()
        self._reorder_cards_to_model()
        self._reindex_cards()
        self.selection_manager.set_page_count(self._model.logical_count())
        self._reflow_grid(force=True)
        self._update_focus_highlight()

    def _sync_grid_after_delete(self, removed_indices: list[int]) -> None:
        assert self._model is not None
        assert self._get_loader is not None
        if self._pending_card_indices:
            self.load_model(self._model, self._get_loader)
            return

        self._invalidate_render_generation()
        self._remove_cards_at_indices(removed_indices)

        total = self._model.logical_count()
        self.selection_manager.set_page_count(total)
        if total == 0:
            self._focused_index = None
            self._reflow_grid(force=True)
            return

        self._reindex_cards()
        if self._focused_index is not None:
            self._focused_index = min(self._focused_index, total - 1)
        self._reflow_grid(force=True)
        self._update_focus_highlight()

    @staticmethod
    def pdf_paths_from_mime(mime) -> list[str]:
        """Return sorted local *.pdf paths from a file-manager drag payload."""
        return pdf_paths_from_mime(mime)

    def insert_pdf_pages(self, paths: list[str], drop_index: int) -> bool:
        """Insert all pages from *paths* at *drop_index*. Returns True on success.

        Edge cases (Phase 14):
        - Same file as the tab primary source: duplicate ``PageRef`` rows are allowed.
        - Multiple paths in one drop: processed in path-sorted order at the same index.
        - Thumbnails still loading: ``_sync_grid_after_insert`` reloads the model
          (cancel-then-insert) instead of patching cards mid-render.
        - Blank tab (no model): ``dropEvent`` opens the PDF(s) via ``open_pdfs_requested``.
        """
        if self._model is None or self._get_loader is None or not paths:
            return False

        insert_at = drop_index
        total_inserted = 0
        last_filename = ""

        for path in sorted(paths):
            loader = self._get_loader(path)
            refs = [PageRef(path, index) for index in range(loader.page_count)]
            if not refs:
                continue
            self._model.insert_pages(insert_at, refs)
            self._sync_grid_after_insert(insert_at, len(refs))
            total_inserted += len(refs)
            last_filename = Path(path).name
            insert_at += len(refs)

        if total_inserted == 0:
            return False

        self._last_clicked_index = None
        self.pages_inserted.emit(total_inserted, last_filename, drop_index + 1)
        return True

    def _sync_grid_after_insert(self, insert_index: int, count: int) -> None:
        assert self._model is not None
        assert self._get_loader is not None
        if self._pending_card_indices or self._pages_needing_render():
            self.load_model(self._model, self._get_loader)
            return
        if len(self._cards) + count != self._model.logical_count():
            self.load_model(self._model, self._get_loader)
            return

        self._invalidate_render_generation()
        new_cards: list[PageCard] = []
        for offset in range(count):
            logical_index = insert_index + offset
            new_cards.append(self._make_page_card(logical_index))

        self._cards[insert_index:insert_index] = new_cards
        for _ in range(count):
            self._page_render_width.insert(insert_index, 0)

        self._reindex_cards()
        self.selection_manager.set_page_count(self._model.logical_count())
        self._reflow_grid(force=True)
        self._start_skeleton_pulse()
        self._start_rendering(
            silent=False,
            page_indices=list(range(insert_index, insert_index + count)),
        )

    def insert_page_refs(self, refs: list[PageRef], drop_index: int) -> bool:
        """Insert explicit ``PageRef`` rows at *drop_index* (cross-window copy/move)."""
        if self._model is None or self._get_loader is None or not refs:
            return False

        for ref in refs:
            self._get_loader(ref.source_path)

        self._model.insert_pages(drop_index, refs)
        self._sync_grid_after_insert(drop_index, len(refs))
        self._last_clicked_index = None
        return True

    def remove_pages_by_indices(self, logical_indices: list[int]) -> bool:
        """Remove logical pages without using the selection manager (cross-window move)."""
        if self._model is None or self._get_loader is None or not logical_indices:
            return False

        ordered = sorted(set(logical_indices))
        self._model.remove_pages(ordered)
        self._last_clicked_index = None
        self._sync_grid_after_delete(ordered)
        return True

    @staticmethod
    def _grid_for_widget(widget: QWidget | None) -> ThumbnailGrid | None:
        current: QWidget | None = widget
        while current is not None:
            if isinstance(current, ThumbnailGrid):
                return current
            current = current.parentWidget()
        return None

    def _parent_tab(self):
        from pagedrop.ui.pdf_tab import PdfTab

        current: QWidget | None = self
        while current is not None:
            if isinstance(current, PdfTab):
                return current
            current = current.parentWidget()
        return None

    def _accepts_page_transfer(self, mime) -> bool:
        if not mime.hasFormat(PAGE_TRANSFER_MIME):
            return False
        if self._model is not None:
            return True
        tab = self._parent_tab()
        return tab is not None and tab.is_blank

    def _rollback_page_transfer_insert(
        self,
        refs: list[PageRef],
        drop_index: int,
        *,
        inited_blank_tab: bool,
    ) -> None:
        """Undo a target insert after a failed page transfer move."""
        tab = self._parent_tab()
        if inited_blank_tab:
            if tab is not None:
                tab.close_loader()
            return

        if self._model is None:
            return

        # Insert recorded an undo snapshot; pop it instead of remove+push.
        if self._model.can_undo():
            self._model.undo()
            self.reload_from_model()
        if tab is not None:
            tab._sync_dirty_from_model()

    def handle_tab_bar_page_drop(
        self,
        refs: list[PageRef],
        *,
        move: bool,
        source_grid: ThumbnailGrid | None,
        mime,
    ) -> bool:
        """Append page refs from a tab-bar drop (always end of target document)."""
        return self._handle_page_transfer(
            refs,
            0,
            move=move,
            source_grid=source_grid,
            mime=mime,
            via_tab_bar=True,
            append_only=True,
        )

    def _handle_page_transfer(
        self,
        refs: list[PageRef],
        drop_index: int,
        *,
        move: bool,
        source_grid: ThumbnailGrid | None,
        mime,
        via_tab_bar: bool = False,
        append_only: bool = False,
    ) -> bool:
        if source_grid is self:
            return False

        tab = self._parent_tab()
        source_filename = Path(refs[0].source_path).name

        # Tab-bar drops always append; grid drops (cross-window and same-window
        # cross-tab) keep the caller-supplied insertion index (Phase 18).
        if append_only:
            drop_index = 0
            if self._model is not None:
                drop_index = self._model.logical_count()

        move_indices: list[int] | None = None
        if move and source_grid is not None:
            move_indices = decode_page_indices(mime.data(INTERNAL_PAGE_MIME))
            if not move_indices:
                self.page_transfer_failed.emit(
                    "Could not move pages: invalid drag data."
                )
                return False
            if source_grid._model is None or source_grid._get_loader is None:
                self.page_transfer_failed.emit(
                    "Could not move pages: source document unavailable."
                )
                return False

        inited_blank_tab = False
        if self._model is None:
            if tab is None or not tab.is_blank:
                return False
            tab.init_from_page_refs(refs)
            inited_blank_tab = True
        elif not self.insert_page_refs(refs, drop_index):
            return False
        elif tab is not None:
            tab._on_pages_inserted()

        target_name = ""
        if tab is not None and tab.edit_model is not None:
            display = tab.edit_model.save_path or tab.edit_model.original_path
            target_name = Path(display).name

        if move_indices is not None:
            assert source_grid is not None
            if not source_grid.remove_pages_by_indices(move_indices):
                self._rollback_page_transfer_insert(
                    refs,
                    drop_index,
                    inited_blank_tab=inited_blank_tab,
                )
                self.page_transfer_failed.emit(
                    "Could not move pages from the source document."
                )
                return False

            source_tab = source_grid._parent_tab()
            if source_tab is not None:
                source_tab._sync_dirty_from_model()

            move_undo = _CrossWindowMoveUndo(
                source_grid=source_grid,
                target_grid=self,
                blank_init=inited_blank_tab,
                source_undo_depth=source_grid._model.undo_depth()
                if source_grid._model is not None
                else 0,
                target_undo_depth=(
                    0
                    if inited_blank_tab or self._model is None
                    else self._model.undo_depth()
                ),
            ).undo
        else:
            move_undo = None

        if via_tab_bar:
            notifier = source_grid if source_grid is not None else self
            notifier.pages_transferred_via_tab_bar.emit(
                len(refs), target_name, move, move_undo
            )
        else:
            if move_indices is not None:
                assert source_grid is not None
                source_grid.pages_moved_out.emit(len(refs), target_name, move_undo)
            self.cross_window_pages_inserted.emit(len(refs), source_filename)
        return True

    def drop_index_at_pos(self, pos: QPoint) -> int:
        """Return the logical insertion index (0…N) for a point in container coords."""
        return insertion_index_at_pos(self._cards, pos)

    def _start_drag_autoscroll_tracking(self) -> None:
        self._drag_over_grid = True
        if self._drag_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._drag_filter_installed = True

    def _stop_drag_autoscroll(self) -> None:
        self._drag_over_grid = False
        self._drag_autoscroller.stop()
        if not self._drag_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._drag_filter_installed = False

    def _on_drag_autoscroll(self, pos_in_grid: QPoint) -> None:
        self._update_drop_at_drag_pos(pos_in_grid)

    def _update_drop_at_drag_pos(self, pos_in_grid: QPoint) -> None:
        container_pos = self._container.mapFrom(self, pos_in_grid)
        self._update_drop_indicator(self.drop_index_at_pos(container_pos))

    def _hide_drop_indicator(self) -> None:
        self._drop_insertion_index = None
        self._drop_indicator.hide()

    def _update_drop_indicator(self, insertion_index: int) -> None:
        rect = drop_indicator_rect(
            self._cards, self._layout.spacing(), insertion_index
        )
        if rect is None:
            self._hide_drop_indicator()
            return

        self._drop_insertion_index = insertion_index
        self._drop_indicator.setGeometry(rect)
        self._drop_indicator.show()
        self._drop_indicator.raise_()

    def _new_selection_after_move(
        self, indices: list[int], to_index: int
    ) -> set[int]:
        _, adjusted = move_items(
            list(range(self._model.logical_count())),
            indices,
            to_index,
        )
        return set(range(adjusted, adjusted + len(set(indices))))

    def _would_move_change_order(self, indices: list[int], to_index: int) -> bool:
        if self._model is None or not indices:
            return False
        before = [self._model.page_at(i) for i in range(self._model.logical_count())]
        after, _ = move_items(before, indices, to_index)
        return before != after

    def reorder_pages_by_drop(self, indices: list[int], to_index: int) -> bool:
        """Move *indices* to *to_index* via internal drag-and-drop."""
        if self._model is None or self._get_loader is None or not indices:
            return False

        ordered = sorted(set(indices))
        if not self._would_move_change_order(ordered, to_index):
            return False

        new_selection = self._new_selection_after_move(ordered, to_index)
        self._model.move_pages(ordered, to_index)
        self._last_clicked_index = None
        self._sync_grid_after_reorder()
        self.selection_manager.set_selection(new_selection)
        if new_selection:
            self._set_focused_index(min(new_selection))
        self.pages_reordered.emit()
        return True

    def _accepts_inbound_pdf_drop(self, mime) -> bool:
        if not self.pdf_paths_from_mime(mime):
            return False
        if self._model is not None:
            return True
        tab = self._parent_tab()
        return tab is not None and tab.is_blank

    def _accept_drag_over_grid(self, event: QDragEnterEvent | QDragMoveEvent) -> bool:
        mime = event.mimeData()
        return bool(
            mime.hasFormat(INTERNAL_PAGE_MIME)
            or self._accepts_page_transfer(mime)
            or self._accepts_inbound_pdf_drop(mime)
        )

    def _handle_drag_over_grid(self, event: QDragEnterEvent | QDragMoveEvent) -> None:
        pos_in_grid = event.position().toPoint()
        self._drag_autoscroller.update(pos_in_grid)
        self._update_drop_at_drag_pos(pos_in_grid)
        self._show_drag_place_status()
        event.acceptProposedAction()

    def _show_drag_place_status(self) -> None:
        window = self.window()
        status_bar = getattr(window, "statusBar", None)
        if callable(status_bar):
            status_bar().showMessage("Release to place pages")

    def _restore_status_after_drag(self) -> None:
        window = self.window()
        restore = getattr(window, "_restore_document_status", None)
        if callable(restore):
            restore()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not getattr(self, "_drag_over_grid", False):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.Wheel:
            wheel = event
            if isinstance(wheel, QWheelEvent) and not (
                wheel.modifiers() & Qt.KeyboardModifier.ControlModifier
            ):
                local = self.mapFromGlobal(wheel.globalPosition().toPoint())
                if self.rect().contains(local):
                    self._drag_autoscroller.update(local)
                    if self._drag_autoscroller.handle_wheel(wheel.angleDelta().y()):
                        self._update_drop_at_drag_pos(local)
                        wheel.accept()
                        return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._accept_drag_over_grid(event):
            self._start_drag_autoscroll_tracking()
            self._handle_drag_over_grid(event)
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._accept_drag_over_grid(event):
            self._start_drag_autoscroll_tracking()
            self._handle_drag_over_grid(event)
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._stop_drag_autoscroll()
        self._hide_drop_indicator()
        self._restore_status_after_drag()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._stop_drag_autoscroll()
        self._hide_drop_indicator()
        self._restore_status_after_drag()
        mime = event.mimeData()
        source_grid = self._grid_for_widget(event.source())

        if mime.hasFormat(INTERNAL_PAGE_MIME) and source_grid is self:
            indices = decode_page_indices(mime.data(INTERNAL_PAGE_MIME))
            pos = self._container.mapFrom(self, event.position().toPoint())
            to_index = self.drop_index_at_pos(pos)
            if self.reorder_pages_by_drop(indices, to_index):
                event.acceptProposedAction()
            else:
                event.ignore()
            return

        if mime.hasFormat(PAGE_TRANSFER_MIME) and source_grid is not self:
            refs = decode_page_refs(mime.data(PAGE_TRANSFER_MIME))
            if not refs:
                event.ignore()
                return

            move = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            pos = self._container.mapFrom(self, event.position().toPoint())
            drop_index = self.drop_index_at_pos(pos)
            try:
                if self._handle_page_transfer(
                    refs,
                    drop_index,
                    move=move,
                    source_grid=source_grid,
                    mime=mime,
                    append_only=False,
                ):
                    event.acceptProposedAction()
                else:
                    event.ignore()
            except PdfLoadError as exc:
                self.pdf_drop_failed.emit(exc)
                event.ignore()
            return

        pdf_paths = self.pdf_paths_from_mime(mime)
        if not pdf_paths:
            event.ignore()
            return

        if self._model is None:
            tab = self._parent_tab()
            if tab is None or not tab.is_blank:
                event.ignore()
                return
            self.open_pdfs_requested.emit(pdf_paths)
            event.acceptProposedAction()
            return

        pos = self._container.mapFrom(self, event.position().toPoint())
        drop_index = self.drop_index_at_pos(pos)
        try:
            if self.insert_pdf_pages(pdf_paths, drop_index):
                event.acceptProposedAction()
            else:
                event.ignore()
        except PdfLoadError as exc:
            self.pdf_drop_failed.emit(exc)
            event.ignore()

    def delete_selected_pages(self) -> bool:
        """Remove selected logical pages from the model and refresh the grid."""
        if self._model is None or self._get_loader is None:
            return False
        logical_indices = sorted(self.selection_manager.selection)
        if not logical_indices:
            return False

        self._model.remove_pages(logical_indices)
        self.selection_manager.clear()
        self._last_clicked_index = None

        total = self._model.logical_count()
        if total == 0:
            self.set_empty_state_message(
                "No pages in this document",
                hint="Open another PDF or add pages to continue",
                show_hint=True,
                show_shortcuts=False,
            )

        self._sync_grid_after_delete(logical_indices)
        return True

    def extract_selected_to_folder(self, output_dir) -> list:
        """Write selected pages to *output_dir*; returns paths or raises."""
        if self._model is None:
            return []
        logical_indices = sorted(self.selection_manager.selection)
        if not logical_indices:
            return []
        refs = [self._model.page_at(i) for i in logical_indices]
        base_name = Path(self._model.original_path).stem
        return extract_page_refs_to_files(
            refs,
            output_dir,
            base_name,
        )

    def extract_all_to_folder(self, output_dir) -> list:
        """Write every page to *output_dir*; returns paths or raises."""
        if self._model is None:
            return []
        total = self._model.logical_count()
        if total == 0:
            return []
        refs = [self._model.page_at(i) for i in range(total)]
        base_name = Path(self._model.original_path).stem
        return extract_page_refs_to_files(refs, output_dir, base_name)

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
        step = ctrl_wheel_zoom_step(event)
        if step is None:
            super().wheelEvent(event)
            return

        self.set_thumbnail_zoom(self._thumbnail_width_px + step)
        event.accept()

    @property
    def manual_zoom(self) -> bool:
        """True after the user changes zoom (wheel / slider / reset)."""
        return self._manual_zoom

    def fitted_thumbnail_width(self) -> int:
        """Thumbnail width that fills the current column count without horizontal scroll."""
        spacing = self._layout.spacing()
        margins = self._layout.contentsMargins()
        available = self.viewport().width() - margins.left() - margins.right()
        if available <= 0:
            return self._thumbnail_width_px
        cols = max(1, available // (self._card_width + spacing))
        card = (available - (cols - 1) * spacing) // cols
        raw = max(
            MIN_THUMBNAIL_WIDTH,
            min(MAX_THUMBNAIL_WIDTH, card - CARD_PADDING),
        )
        # Snap down to zoom-step grid so the slider stays aligned.
        steps = (raw - MIN_THUMBNAIL_WIDTH) // ZOOM_WHEEL_STEP
        return MIN_THUMBNAIL_WIDTH + steps * ZOOM_WHEEL_STEP


    def autofit_thumbnails_if_allowed(self) -> bool:
        """Fill columns on open. No-op after manual zoom. Returns True when size changed."""
        if self._manual_zoom:
            return False
        fitted = self.fitted_thumbnail_width()
        if fitted == self._thumbnail_width_px:
            return False
        self._apply_zoom(fitted)
        return True

    def set_thumbnail_zoom(
        self, thumbnail_width_px: int, *, manual: bool = True
    ) -> None:
        clamped = max(
            MIN_THUMBNAIL_WIDTH,
            min(MAX_THUMBNAIL_WIDTH, thumbnail_width_px),
        )
        if manual:
            self._manual_zoom = True
        if clamped != self._thumbnail_width_px:
            self._apply_zoom(clamped)

    def zoom_by(self, step: int) -> None:
        self.set_thumbnail_zoom(self._thumbnail_width_px + step)

    def jump_to_pages(self, indices: list[int]) -> None:
        """Select *indices* (0-based) and scroll the first into view."""
        if not indices or not self._cards:
            return
        valid = sorted({i for i in indices if 0 <= i < len(self._cards)})
        if not valid:
            return
        self.selection_manager.set_selection(set(valid))
        self._last_clicked_index = valid[0]
        self._set_focused_index(valid[0])
        self._scroll_to_focused_card()

    def _page_overlay_visible(self) -> bool:
        return self._thumbnail_width_px >= PAGE_NUMBER_OVERLAY_MIN_WIDTH

    def _sync_page_overlays(self) -> None:
        visible = self._page_overlay_visible()
        for card in self._cards:
            card.set_page_overlay_visible(visible)

    def _apply_zoom(self, thumbnail_width_px: int) -> None:
        self._thumbnail_width_px = thumbnail_width_px
        self._card_width = thumbnail_width_px + CARD_PADDING
        visible = set(self._get_visible_page_indices())
        deferred_layout: list[int] = []
        for index, card in enumerate(self._cards):
            in_view = index in visible
            if in_view:
                card.set_card_width(
                    self._card_width,
                    fast=True,
                    refresh_thumbnail=True,
                    apply_layout=True,
                )
            else:
                card.set_card_width(
                    self._card_width,
                    fast=True,
                    refresh_thumbnail=False,
                    apply_layout=False,
                )
                deferred_layout.append(index)
        self._sync_page_overlays()
        if deferred_layout:
            self._schedule_deferred_layout_update(deferred_layout)
        self._reflow_grid()
        self.zoom_changed.emit(self._thumbnail_width_px)
        self._schedule_zoom_rerender()

    def _schedule_deferred_layout_update(self, indices: list[int]) -> None:
        self._pending_layout_indices.extend(indices)
        if not self._deferred_layout_timer.isActive():
            self._deferred_layout_timer.start(0)

    def _process_deferred_layout_batch(self) -> None:
        batch = self._pending_layout_indices[:DEFERRED_LAYOUT_BATCH]
        self._pending_layout_indices = self._pending_layout_indices[
            DEFERRED_LAYOUT_BATCH:
        ]
        for index in batch:
            if 0 <= index < len(self._cards):
                self._cards[index].apply_layout_width()
        if self._pending_layout_indices:
            self._deferred_layout_timer.start(0)

    def _schedule_deferred_thumbnail_refresh(self, indices: list[int]) -> None:
        self._pending_thumbnail_refresh.extend(indices)
        if not self._deferred_thumbnail_timer.isActive():
            self._deferred_thumbnail_timer.start(0)

    def _process_deferred_thumbnail_refresh(self) -> None:
        batch = self._pending_thumbnail_refresh[:DEFERRED_THUMBNAIL_BATCH]
        self._pending_thumbnail_refresh = self._pending_thumbnail_refresh[
            DEFERRED_THUMBNAIL_BATCH:
        ]
        for index in batch:
            if 0 <= index < len(self._cards):
                self._cards[index].refresh_thumbnail_display(fast=True)
        if self._pending_thumbnail_refresh:
            self._deferred_thumbnail_timer.start(0)

    def _get_visible_page_indices(
        self, *, buffer_rows: int = VISIBLE_RENDER_BUFFER_ROWS
    ) -> list[int]:
        if not self._cards:
            return []

        top_left = self._container.mapFrom(self.viewport(), QPoint(0, 0))
        bottom_right = self._container.mapFrom(
            self.viewport(),
            QPoint(self.viewport().width(), self.viewport().height()),
        )
        visible_top = min(top_left.y(), bottom_right.y())
        visible_bottom = max(top_left.y(), bottom_right.y())

        if buffer_rows > 0:
            sample = self._cards[0]
            row_stride = max(sample.height() + self._layout.spacing(), 1)
            buffer_px = buffer_rows * row_stride
            visible_top -= buffer_px
            visible_bottom += buffer_px

        indices: list[int] = []
        for index, card in enumerate(self._cards):
            card_top = card.y()
            card_bottom = card_top + card.height()
            if card_bottom >= visible_top and card_top <= visible_bottom:
                indices.append(index)
        return indices

    def _target_render_width(self) -> int:
        from pagedrop.ui.settings import thumbnail_render_width

        return thumbnail_render_width(self._thumbnail_width_px)

    def refresh_thumbnail_quality(self) -> None:
        """Re-render pages that are below the current quality band cap."""
        if self._model is None:
            return
        if self._pages_needing_render():
            self._schedule_zoom_rerender()

    def _pages_needing_render(self) -> list[int]:
        target = self._target_render_width()
        return [
            index
            for index, width in enumerate(self._page_render_width)
            if width < target
        ]

    def _visible_pages_needing_render(self) -> list[int]:
        visible = set(self._get_visible_page_indices())
        return [index for index in self._pages_needing_render() if index in visible]

    def _background_pages_needing_render(self) -> list[int]:
        visible = set(self._get_visible_page_indices())
        return [index for index in self._pages_needing_render() if index not in visible]

    def _sync_rendered_width_state(self) -> None:
        target = self._target_render_width()
        if self._page_render_width and all(
            width >= target for width in self._page_render_width
        ):
            self._last_rendered_width_px = self._thumbnail_width_px

    def _cancel_rendering(self) -> None:
        self._zoom_render_timer.stop()
        self.zoom_render_pending.emit(False)
        self._scroll_render_timer.stop()
        self._background_render_timer.stop()
        self._card_create_timer.stop()
        self._pending_card_indices.clear()
        self._generation += 1
        self._busy_render_generation = -1
        self._leave_busy("rendering")
        self._leave_busy("loading")
        self._dismiss_progress()

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
        self, generation: int, page_index: int, png: bytes
    ) -> None:
        if self._is_cancelled(generation):
            return
        if page_index >= len(self._cards):
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(png, "PNG") or pixmap.isNull():
            return
        self._cards[page_index].set_thumbnail(pixmap)
        self._page_render_width[page_index] = (
            self._busy_render_width or self._target_render_width()
        )
        self._sync_rendered_width_state()
        if not any(card._is_skeleton for card in self._cards):
            self._stop_skeleton_pulse()
        # Keep the status-bar bar moving across silent zoom/scroll follow-ups;
        # otherwise cancelling the initial job freezes the percentage forever.
        if self._progress_active:
            target = self._target_render_width()
            rendered = sum(
                1
                for width in self._page_render_width
                if width >= target
            )
            self.rendering_progress.emit(rendered, len(self._cards))

    def _on_rendering_finished(self, generation: int) -> None:
        if self._is_cancelled(generation):
            return
        self._sync_rendered_width_state()
        if generation == self._busy_render_generation:
            self._busy_render_generation = -1
            self._leave_busy("rendering")
        self._maybe_continue_or_dismiss_progress()

    def _on_rendering_error(self, generation: int, message: str) -> None:
        if self._is_cancelled(generation):
            return
        if generation == self._busy_render_generation:
            self._busy_render_generation = -1
            self._leave_busy("rendering")
        self._dismiss_progress()
        self.rendering_error.emit(message)

    def _enter_busy(self, reason: str, message: str) -> None:
        # Status + pulsing skeletons + progress bar; no blocking overlay.
        self._busy_reasons.add(reason)
        self._busy_message = message
        self.busy_changed.emit(True, message)

    def _leave_busy(self, reason: str) -> None:
        self._busy_reasons.discard(reason)
        if self._busy_reasons:
            return
        self._busy_message = ""
        self.busy_changed.emit(False, "")

    def _start_skeleton_pulse(self) -> None:
        if prefers_reduce_motion():
            return
        if not any(card._is_skeleton for card in self._cards):
            return
        if not self._skeleton_pulse_timer.isActive():
            self._skeleton_pulse_dim = False
            self._skeleton_pulse_timer.start()

    def _stop_skeleton_pulse(self) -> None:
        self._skeleton_pulse_timer.stop()
        self._skeleton_pulse_dim = False

    def _pulse_skeleton_cards(self) -> None:
        skeletons = [card for card in self._cards if card._is_skeleton]
        if not skeletons:
            self._stop_skeleton_pulse()
            return
        self._skeleton_pulse_dim = not self._skeleton_pulse_dim
        for card in skeletons:
            card.set_skeleton_pulse(self._skeleton_pulse_dim)

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
