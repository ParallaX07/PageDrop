"""Shared scroll-grid shell for merge/convert file queues.

ThumbnailGrid stays separate: page-model editing, keyboard focus, busy overlay,
cross-window transfer, and deferred zoom/render are not the same problem as
path-list reorder. Forcing one hierarchy would break or obscure that behavior.

Merge/Convert share internal MIME reorder + external file drop via this base.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QPixmap,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pagedrop.assets import empty_state_logo_pixmap
from pagedrop.core.drag_mime import (
    INTERNAL_MERGE_FILE_MIME,
    decode_page_indices,
)
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.ui.base_file_card import InternalReorderFileCard
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
    SPACE_2,
    SPACE_3,
    SPACE_4,
    SPACE_6,
    SPACE_7,
)
from pagedrop.utils.list_utils import move_items

ZOOM_RENDER_DEBOUNCE_MS = 200
RENDER_POOL_DRAIN_MS = 2000


class BaseFileGrid(QScrollArea):
    """Path-list grid with selection, zoom, drop indicator, and reorder."""

    files_dropped = pyqtSignal(list)
    files_reordered = pyqtSignal(list)
    preview_requested = pyqtSignal(str)
    selection_changed = pyqtSignal()
    zoom_changed = pyqtSignal(int)
    # Same contract as ThumbnailGrid.rendering_error — window shows status/toast.
    rendering_error = pyqtSignal(str)

    def __init__(
        self,
        *,
        object_name: str,
        container_object_name: str,
        empty_object_name: str,
        empty_logo_object_name: str,
        empty_title_object_name: str,
        empty_hint_object_name: str,
        empty_kbd_object_name: str,
        empty_title: str,
        empty_hint: str,
        empty_kbd: str = (
            "← → ↑ ↓ navigate  ·  Space select  ·  Enter preview"
        ),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths: list[str] = []
        self._render_width_by_path: dict[str, int] = {}
        self._failed_paths: set[str] = set()
        self._cards: list[InternalReorderFileCard] = []
        self._grid_cols = 0
        self._thumbnail_width_px = DEFAULT_THUMBNAIL_WIDTH
        self._card_width = CARD_WIDTH
        self._generation = 0
        self._last_clicked_index: int | None = None
        self._focused_index: int | None = None
        self._drop_insertion_index: int | None = None
        # max 1 serializes this grid only; see core.thread_policy for cross-pool risk
        self._render_pool = QThreadPool(self)
        self._render_pool.setMaxThreadCount(1)
        self._zoom_render_timer = QTimer(self)
        self._zoom_render_timer.setSingleShot(True)
        self._zoom_render_timer.setInterval(ZOOM_RENDER_DEBOUNCE_MS)
        self._zoom_render_timer.timeout.connect(self._schedule_thumbnails)

        self.setObjectName(object_name)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)

        self._container = QWidget()
        self._container.setObjectName(container_object_name)
        self._layout = QGridLayout(self._container)
        self._layout.setSpacing(SPACE_3)
        self._layout.setContentsMargins(SPACE_4, SPACE_4, SPACE_4, SPACE_4)
        self._layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        self._empty_state = QWidget()
        self._empty_state.setObjectName(empty_object_name)
        self._empty_state.setAccessibleName(empty_title)
        self._empty_state.setAccessibleDescription(empty_hint)
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(SPACE_2)
        empty_layout.setContentsMargins(SPACE_6, SPACE_7, SPACE_6, SPACE_7)

        self._empty_logo = QLabel()
        self._empty_logo.setObjectName(empty_logo_object_name)
        self._empty_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_logo.setAccessibleName("PageDrop logo")
        self._empty_logo.setPixmap(empty_state_logo_pixmap())

        self._empty_title = QLabel(empty_title)
        self._empty_title.setObjectName(empty_title_object_name)
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_hint = QLabel(empty_hint)
        self._empty_hint.setObjectName(empty_hint_object_name)
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_kbd = QLabel(empty_kbd)
        self._empty_kbd.setObjectName(empty_kbd_object_name)
        self._empty_kbd.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_layout.addStretch(1)
        empty_layout.addWidget(self._empty_logo)
        empty_layout.addWidget(self._empty_title)
        empty_layout.addWidget(self._empty_hint)
        empty_layout.addWidget(self._empty_kbd)
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
        self._painted_selection: set[int] = set()

    def _create_card(self, index: int, path: str) -> InternalReorderFileCard:
        raise NotImplementedError

    def _external_paths_from_mime(self, mime) -> list[str]:
        raise NotImplementedError

    def _schedule_thumbnails(self) -> None:
        raise NotImplementedError

    def _on_thumbnail_failed(
        self, path: str, generation: int, _detail: str = ""
    ) -> None:
        """Shared failure path for merge/convert thumb workers (mirrors ThumbnailGrid)."""
        if generation != self._generation:
            return
        self._failed_paths.add(path)
        self.rendering_error.emit(
            f"Could not preview {Path(path).name} — "
            "file may be corrupt or unreadable"
        )

    @property
    def thumbnail_width_px(self) -> int:
        return self._thumbnail_width_px

    @property
    def ordered_paths(self) -> list[str]:
        return list(self._paths)

    def _set_file_paths(
        self,
        paths: list[str],
        *,
        selected_paths: set[str] | None = None,
    ) -> None:
        selected_indices: set[int] = set()
        if selected_paths:
            for index, path in enumerate(paths):
                if path in selected_paths:
                    selected_indices.add(index)

        self._paths = list(paths)
        self._generation += 1
        self._failed_paths.clear()
        self._clear_cards()
        self._last_clicked_index = None
        self._focused_index = 0 if paths else None

        for index, path in enumerate(paths):
            card = self._create_card(index, path)
            card.set_selection_manager(self.selection_manager)
            card.set_card_width(self._card_width, refresh_thumbnail=False)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._on_card_double_clicked)
            self._cards.append(card)

        self.selection_manager.set_page_count(len(paths))
        self.selection_manager.set_selection(selected_indices)

        self._reflow_grid(force=True)
        self._update_empty_state()
        self._update_focus_highlight()
        self._schedule_thumbnails()

    @property
    def focused_index(self) -> int | None:
        return self._focused_index

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
        if mime.hasFormat(INTERNAL_MERGE_FILE_MIME) or self._external_paths_from_mime(
            mime
        ):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        mime = event.mimeData()
        if mime.hasFormat(INTERNAL_MERGE_FILE_MIME) or self._external_paths_from_mime(
            mime
        ):
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

        paths = self._external_paths_from_mime(mime)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return

        super().dropEvent(event)

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
            self._on_card_double_clicked(idx)
            event.accept()
        else:
            super().keyPressEvent(event)

    def _on_selection_changed(self, selection: set[int]) -> None:
        self._sync_selection_chrome(selection)
        self.selection_changed.emit()

    def _sync_selection_chrome(self, selection: set[int]) -> None:
        n = len(self._cards)
        applicable = {i for i in selection if 0 <= i < n}
        for index in self._painted_selection ^ applicable:
            self._cards[index].set_selected(index in applicable)
        self._painted_selection = applicable

    def _resync_selection_chrome(self) -> None:
        """Full chrome pass after card list surgery (reorder)."""
        selection = self.selection_manager.selection
        n = len(self._cards)
        applicable = {i for i in selection if 0 <= i < n}
        for index, card in enumerate(self._cards):
            card.set_selected(index in applicable)
        self._painted_selection = applicable

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
        self._set_focused_index(index)
        self.setFocus()

    def _on_card_double_clicked(self, index: int) -> None:
        if 0 <= index < len(self._paths):
            self.preview_requested.emit(self._paths[index])

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

    def _clear_cards(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        self._painted_selection.clear()
        self._focused_index = None
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
        self._resync_selection_chrome()
        if self._focused_index is not None:
            self._focused_index = min(self._focused_index, len(self._cards) - 1)
            self._update_focus_highlight()
        self.files_reordered.emit(new_paths)
        return True

    def _find_card_pixmap(self, path: str) -> QPixmap | None:
        for card in self._cards:
            if card.path == path and card._source_pixmap is not None:
                return card._source_pixmap
        return None

    def _is_cancelled(self, generation: int) -> bool:
        return generation != self._generation

    def cancel_rendering(self) -> None:
        """Invalidate in-flight thumbnail workers (e.g. before teardown)."""
        self._zoom_render_timer.stop()
        self._generation += 1
        self._render_pool.waitForDone(RENDER_POOL_DRAIN_MS)
