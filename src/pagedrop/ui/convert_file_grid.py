from __future__ import annotations

import os
from collections.abc import Callable

import fitz
from PyQt6.QtCore import (
    QObject,
    QPoint,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QPixmap, QResizeEvent
from PyQt6.QtWidgets import QFrame, QGridLayout, QScrollArea, QVBoxLayout, QWidget

from pagedrop.assets import empty_state_logo_pixmap
from pagedrop.core.drag_mime import (
    INTERNAL_MERGE_FILE_MIME,
    decode_page_indices,
)
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.core.supported_formats import image_paths_from_mime
from pagedrop.ui.convert_file_card import ConvertFileCard
from pagedrop.ui.grid_helpers import (
    ctrl_wheel_zoom_step,
    drop_index_at_pos,
    drop_indicator_rect,
)
from pagedrop.ui.theme import (
    CARD_PADDING,
    CARD_WIDTH,
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_THUMBNAIL_WIDTH,
    MIN_THUMBNAIL_WIDTH,
)
from pagedrop.utils.list_utils import move_items

ZOOM_RENDER_DEBOUNCE_MS = 200
RENDER_POOL_DRAIN_MS = 2000


def render_image_thumbnail_png(path: str, width_px: int) -> bytes | None:
    with fitz.open(path) as doc:
        if doc.page_count == 0:
            return None
        page = doc[0]
        page_width = page.rect.width
        if page_width <= 0:
            return None
        scale = width_px / page_width
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")


class _ConvertThumbnailWorker(QRunnable):
    class Signals(QObject):
        ready = pyqtSignal(str, int, int, object)  # path, width_px, generation, png

    def __init__(
        self,
        path: str,
        width_px: int,
        generation: int,
        is_cancelled: Callable[[int], bool],
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._path = path
        self._width_px = width_px
        self._generation = generation
        self._is_cancelled = is_cancelled
        self.setAutoDelete(True)

    def run(self) -> None:
        if self._is_cancelled(self._generation):
            return
        try:
            png = render_image_thumbnail_png(self._path, self._width_px)
        except Exception:
            return
        if self._is_cancelled(self._generation) or png is None:
            return
        self.signals.ready.emit(self._path, self._width_px, self._generation, png)


class ConvertFileGrid(QScrollArea):
    """Resizable grid of image files queued for PDF conversion."""

    files_dropped = pyqtSignal(list)
    files_reordered = pyqtSignal(list)
    preview_requested = pyqtSignal(str)
    selection_changed = pyqtSignal()
    zoom_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._paths: list[str] = []
        self._dimensions: dict[str, tuple[int, int]] = {}
        self._render_width_by_path: dict[str, int] = {}
        self._cards: list[ConvertFileCard] = []
        self._grid_cols = 0
        self._thumbnail_width_px = DEFAULT_THUMBNAIL_WIDTH
        self._card_width = CARD_WIDTH
        self._generation = 0
        self._last_clicked_index: int | None = None
        self._drop_insertion_index: int | None = None
        self._render_pool = QThreadPool(self)
        self._render_pool.setMaxThreadCount(1)
        self._zoom_render_timer = QTimer(self)
        self._zoom_render_timer.setSingleShot(True)
        self._zoom_render_timer.setInterval(ZOOM_RENDER_DEBOUNCE_MS)
        self._zoom_render_timer.timeout.connect(self._schedule_thumbnails)

        self.setObjectName("ConvertFileGrid")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)

        self._container = QWidget()
        self._container.setObjectName("ConvertFileGridContainer")
        self._layout = QGridLayout(self._container)
        self._layout.setSpacing(12)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        self._empty_state = QWidget()
        self._empty_state.setObjectName("ConvertEmptyState")
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(8)
        empty_layout.setContentsMargins(32, 48, 32, 48)

        from PyQt6.QtWidgets import QLabel

        self._empty_logo = QLabel()
        self._empty_logo.setObjectName("ConvertEmptyLogo")
        self._empty_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_logo.setPixmap(empty_state_logo_pixmap())

        self._empty_title = QLabel("Add images to create PDF")
        self._empty_title.setObjectName("ConvertEmptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_hint = QLabel("Use Add Images or drop files here")
        self._empty_hint.setObjectName("ConvertEmptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_layout.addStretch(1)
        empty_layout.addWidget(self._empty_logo)
        empty_layout.addWidget(self._empty_title)
        empty_layout.addWidget(self._empty_hint)
        empty_layout.addStretch(2)

        self._layout.addWidget(self._empty_state, 0, 0, 1, 1)

        self._drop_indicator = QFrame(self._container)
        self._drop_indicator.setObjectName("DropIndicator")
        self._drop_indicator.setFixedWidth(3)
        self._drop_indicator.hide()

        self.setWidget(self._container)

        self.selection_manager = SelectionManager(
            on_selection_changed=self._on_selection_changed,
        )

    @property
    def thumbnail_width_px(self) -> int:
        return self._thumbnail_width_px

    @property
    def ordered_paths(self) -> list[str]:
        return list(self._paths)

    def set_files(
        self,
        paths: list[str],
        dimensions: dict[str, tuple[int, int]],
        *,
        selected_paths: set[str] | None = None,
    ) -> None:
        selected_indices: set[int] = set()
        if selected_paths:
            for index, path in enumerate(paths):
                if path in selected_paths:
                    selected_indices.add(index)

        self._paths = list(paths)
        self._dimensions = dict(dimensions)
        self._generation += 1
        self._clear_cards()

        for index, path in enumerate(paths):
            card = ConvertFileCard(
                index,
                path,
                dimensions.get(path, (0, 0)),
            )
            card.set_selection_manager(self.selection_manager)
            card.set_card_width(self._card_width, refresh_thumbnail=False)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._on_card_double_clicked)
            card.set_selected(index in selected_indices)
            self._cards.append(card)

        self.selection_manager.set_page_count(len(paths))
        if selected_indices:
            self.selection_manager.set_selection(selected_indices)

        self._reflow_grid(force=True)
        self._update_empty_state()
        self._schedule_thumbnails()

    def selected_indices(self) -> list[int]:
        return sorted(self.selection_manager.selection)

    def set_thumbnail_zoom(self, thumbnail_width_px: int) -> None:
        clamped = max(
            MIN_THUMBNAIL_WIDTH,
            min(MAX_THUMBNAIL_WIDTH, thumbnail_width_px),
        )
        if clamped == self._thumbnail_width_px:
            return
        self._thumbnail_width_px = clamped
        self._card_width = clamped + CARD_PADDING
        for card in self._cards:
            card.set_card_width(self._card_width, fast=True)
        self._reflow_grid()
        self.zoom_changed.emit(self._thumbnail_width_px)
        self._zoom_render_timer.start()

    def zoom_by(self, step: int) -> None:
        self.set_thumbnail_zoom(self._thumbnail_width_px + step)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reflow_grid()

    def wheelEvent(self, event) -> None:
        step = ctrl_wheel_zoom_step(event)
        if step is None:
            super().wheelEvent(event)
            return

        self.set_thumbnail_zoom(self._thumbnail_width_px + step)
        event.accept()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime.hasFormat(INTERNAL_MERGE_FILE_MIME) or image_paths_from_mime(mime):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        mime = event.mimeData()
        if mime.hasFormat(INTERNAL_MERGE_FILE_MIME) or image_paths_from_mime(mime):
            pos = self._container.mapFrom(self, event.position().toPoint())
            self._update_drop_indicator(self._drop_index_at_pos(pos))
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._hide_drop_indicator()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        self._hide_drop_indicator()

        if mime.hasFormat(INTERNAL_MERGE_FILE_MIME):
            indices = decode_page_indices(mime.data(INTERNAL_MERGE_FILE_MIME))
            pos = self._container.mapFrom(self, event.position().toPoint())
            to_index = self._drop_index_at_pos(pos)
            if self._reorder_by_drop(indices, to_index):
                event.acceptProposedAction()
            return

        paths = image_paths_from_mime(mime)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return

        super().dropEvent(event)

    def _on_selection_changed(self, _selection: set[int]) -> None:
        for index, card in enumerate(self._cards):
            card.set_selected(index in self.selection_manager.selection)
        self.selection_changed.emit()

    def _on_card_clicked(self, index: int, modifiers: Qt.KeyboardModifier) -> None:
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self.selection_manager.toggle(index)
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            anchor = self._last_clicked_index
            if anchor is None:
                self.selection_manager.select_single(index)
            else:
                self.selection_manager.select_range(anchor, index)
        else:
            self.selection_manager.select_single(index)
        self._last_clicked_index = index

    def _on_card_double_clicked(self, index: int) -> None:
        if 0 <= index < len(self._paths):
            self.preview_requested.emit(self._paths[index])

    def _clear_cards(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    def _update_empty_state(self) -> None:
        if self._cards:
            self._empty_state.hide()
        else:
            self._layout.addWidget(self._empty_state, 0, 0, 1, 1)
            self._empty_state.show()

    def _reflow_grid(self, *, force: bool = False) -> None:
        if not self._cards:
            self._grid_cols = 0
            self._update_empty_state()
            return

        spacing = self._layout.spacing()
        margins = self._layout.contentsMargins()
        available = self.viewport().width() - margins.left() - margins.right()
        cols = max(1, available // (self._card_width + spacing))

        if not force and cols == self._grid_cols:
            return

        self._grid_cols = cols
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget and widget is not self._empty_state:
                widget.setParent(None)

        for index, card in enumerate(self._cards):
            self._layout.addWidget(card, index // cols, index % cols)

        self._empty_state.hide()

    def _drop_index_at_pos(self, pos: QPoint) -> int:
        return drop_index_at_pos(self._cards, pos)

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

    def _reorder_by_drop(self, indices: list[int], to_index: int) -> bool:
        if not indices or not self._paths:
            return False

        new_paths, adjusted = move_items(self._paths, indices, to_index)
        if new_paths == self._paths:
            return False

        ordered = sorted(set(indices))
        path_to_card = {card.path: card for card in self._cards}
        self._paths = new_paths
        self._cards = [path_to_card[path] for path in new_paths]
        for index, card in enumerate(self._cards):
            card.set_file_index(index)
        new_selection = set(range(adjusted, adjusted + len(ordered)))
        self._reflow_grid(force=True)
        self.selection_manager.set_selection(new_selection)
        self.files_reordered.emit(new_paths)
        return True

    def _schedule_thumbnails(self) -> None:
        self._generation += 1
        generation = self._generation
        target = self._thumbnail_width_px

        paths_to_render: list[str] = []
        for path in self._paths:
            if self._render_width_by_path.get(path, 0) >= target:
                if self._find_card_pixmap(path) is not None:
                    continue
            paths_to_render.append(path)

        if not paths_to_render:
            return

        if os.environ.get("PAGEDROP_TESTING") == "1":
            for path in paths_to_render:
                if generation != self._generation:
                    return
                png = render_image_thumbnail_png(path, target)
                if png is not None:
                    self._on_thumbnail_ready(path, target, generation, png)
            return

        for path in paths_to_render:
            worker = _ConvertThumbnailWorker(
                path,
                target,
                generation,
                self._is_cancelled,
            )
            worker.signals.ready.connect(self._on_thumbnail_ready)
            self._render_pool.start(worker)

    def _find_card_pixmap(self, path: str) -> QPixmap | None:
        for card in self._cards:
            if card.path == path and card._source_pixmap is not None:
                return card._source_pixmap
        return None

    def _is_cancelled(self, generation: int) -> bool:
        return generation != self._generation

    def cancel_rendering(self) -> None:
        self._zoom_render_timer.stop()
        self._generation += 1
        self._render_pool.waitForDone(RENDER_POOL_DRAIN_MS)

    def _on_thumbnail_ready(
        self, path: str, width_px: int, generation: int, png: bytes
    ) -> None:
        if generation != self._generation:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(png, "PNG") or pixmap.isNull():
            return
        self._render_width_by_path[path] = width_px
        for card in self._cards:
            if card.path == path:
                card.set_thumbnail(pixmap)
                break
