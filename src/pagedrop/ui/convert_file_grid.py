from __future__ import annotations

import os
from collections.abc import Callable

import fitz
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal
from PyQt6.QtGui import QPixmap

from pagedrop.core.supported_formats import image_paths_from_mime
from pagedrop.ui.base_file_grid import BaseFileGrid
from pagedrop.ui.convert_file_card import ConvertFileCard


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
    """Image thumbs off the UI thread (see core.thread_policy)."""

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
        # Own fitz.open by path; pool max 1 (BaseFileGrid). Cross-pool → Phase 22/23.
        if self._is_cancelled(self._generation):
            return
        try:
            png = render_image_thumbnail_png(self._path, self._width_px)
        except Exception:
            return
        if self._is_cancelled(self._generation) or png is None:
            return
        self.signals.ready.emit(self._path, self._width_px, self._generation, png)


class ConvertFileGrid(BaseFileGrid):
    """Resizable grid of image files queued for PDF conversion."""

    def __init__(self, parent=None) -> None:
        self._dimensions: dict[str, tuple[int, int]] = {}
        super().__init__(
            object_name="ConvertFileGrid",
            container_object_name="ConvertFileGridContainer",
            empty_object_name="ConvertEmptyState",
            empty_logo_object_name="ConvertEmptyLogo",
            empty_title_object_name="ConvertEmptyTitle",
            empty_hint_object_name="ConvertEmptyHint",
            empty_kbd_object_name="ConvertEmptyKbd",
            empty_title="Add images to create PDF",
            empty_hint="Use Add images or drop files here",
            parent=parent,
        )

    def set_files(
        self,
        paths: list[str],
        dimensions: dict[str, tuple[int, int]],
        *,
        selected_paths: set[str] | None = None,
    ) -> None:
        self._dimensions = dict(dimensions)
        self._set_file_paths(paths, selected_paths=selected_paths)

    def _create_card(self, index: int, path: str) -> ConvertFileCard:
        return ConvertFileCard(
            index,
            path,
            self._dimensions.get(path, (0, 0)),
        )

    def _external_paths_from_mime(self, mime) -> list[str]:
        return image_paths_from_mime(mime)

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
