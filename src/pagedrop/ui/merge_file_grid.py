from __future__ import annotations

import os
from collections.abc import Callable

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal
from PyQt6.QtGui import QPixmap

from pagedrop.core.supported_formats import pdf_paths_from_mime
from pagedrop.ui.base_file_grid import BaseFileGrid
from pagedrop.ui.merge_file_card import MergeFileCard
from pagedrop.ui.stacked_thumbnail import (
    build_stacked_pixmap,
    render_stacked_page_pngs,
    stack_thumbnail_layout,
)


class _MergeThumbnailWorker(QRunnable):
    class Signals(QObject):
        ready = pyqtSignal(str, int, int, object)  # path, width_px, generation, page_pngs

    def __init__(
        self,
        path: str,
        page_count: int,
        width_px: int,
        generation: int,
        is_cancelled: Callable[[int], bool],
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._path = path
        self._page_count = page_count
        self._width_px = width_px
        self._generation = generation
        self._is_cancelled = is_cancelled
        self.setAutoDelete(True)

    def run(self) -> None:
        if self._is_cancelled(self._generation):
            return
        try:
            _layers, _stack_offset, page_width = stack_thumbnail_layout(
                self._width_px,
                self._page_count,
            )
            page_pngs = render_stacked_page_pngs(
                self._path,
                self._page_count,
                width_px=page_width,
                should_cancel=lambda: self._is_cancelled(self._generation),
            )
        except Exception:
            return
        if self._is_cancelled(self._generation):
            return
        self.signals.ready.emit(self._path, self._width_px, self._generation, page_pngs)


class MergeFileGrid(BaseFileGrid):
    """Resizable grid of PDF files queued for merge."""

    def __init__(self, parent=None) -> None:
        self._page_counts: dict[str, int] = {}
        super().__init__(
            object_name="MergeFileGrid",
            container_object_name="MergeFileGridContainer",
            empty_object_name="MergeEmptyState",
            empty_logo_object_name="MergeEmptyLogo",
            empty_title_object_name="MergeEmptyTitle",
            empty_hint_object_name="MergeEmptyHint",
            empty_title="Add PDFs to merge",
            empty_hint="Use Add PDFs or drop files here",
            parent=parent,
        )

    def set_files(
        self,
        paths: list[str],
        page_counts: dict[str, int],
        *,
        selected_paths: set[str] | None = None,
    ) -> None:
        self._page_counts = dict(page_counts)
        self._set_file_paths(paths, selected_paths=selected_paths)

    def _create_card(self, index: int, path: str) -> MergeFileCard:
        return MergeFileCard(
            index,
            path,
            self._page_counts.get(path, 0),
        )

    def _external_paths_from_mime(self, mime) -> list[str]:
        return pdf_paths_from_mime(mime)

    def _schedule_thumbnails(self) -> None:
        self._generation += 1
        generation = self._generation
        target = self._thumbnail_width_px

        paths_to_render: list[tuple[str, int]] = []
        for path in self._paths:
            if self._render_width_by_path.get(path, 0) >= target:
                if self._find_card_pixmap(path) is not None:
                    continue
            page_count = self._page_counts.get(path, 0)
            paths_to_render.append((path, page_count))

        if not paths_to_render:
            return

        if os.environ.get("PAGEDROP_TESTING") == "1":
            for path, page_count in paths_to_render:
                if generation != self._generation:
                    return
                _layers, _stack_offset, page_width = stack_thumbnail_layout(
                    target,
                    page_count,
                )
                page_pngs = render_stacked_page_pngs(
                    path,
                    page_count,
                    width_px=page_width,
                )
                self._on_thumbnail_ready(path, target, generation, page_pngs)
            return

        for path, page_count in paths_to_render:
            worker = _MergeThumbnailWorker(
                path,
                page_count,
                target,
                generation,
                self._is_cancelled,
            )
            worker.signals.ready.connect(self._on_thumbnail_ready)
            self._render_pool.start(worker)

    def _on_thumbnail_ready(
        self, path: str, width_px: int, generation: int, page_pngs: list[bytes]
    ) -> None:
        if generation != self._generation or not page_pngs:
            return
        page_count = self._page_counts.get(path, len(page_pngs))
        _layers, stack_offset, _page_width = stack_thumbnail_layout(
            width_px,
            page_count,
        )
        pixmaps: list[QPixmap] = []
        for png in page_pngs:
            pixmap = QPixmap()
            pixmap.loadFromData(png, "PNG")
            pixmaps.append(pixmap)
        pixmap = build_stacked_pixmap(pixmaps, stack_offset=stack_offset)
        if pixmap.isNull():
            return
        self._render_width_by_path[path] = width_px
        for card in self._cards:
            if card.path == path:
                card.set_thumbnail(pixmap)
                break
