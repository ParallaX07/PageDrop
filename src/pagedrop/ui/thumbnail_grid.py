from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QResizeEvent
from PyQt6.QtWidgets import QGridLayout, QScrollArea, QWidget

import fitz

from pagedrop.core.pdf_loader import PdfLoader, render_page_png
from pagedrop.ui.page_card import PageCard


class ThumbnailWorker(QRunnable):
    class Signals(QObject):
        page_ready = pyqtSignal(int, int, QPixmap)  # generation, page_index, pixmap
        finished = pyqtSignal(int)  # generation

    def __init__(
        self,
        path: str,
        total_pages: int,
        generation: int,
        is_cancelled: Callable[[int], bool],
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._path = path
        self._total_pages = total_pages
        self._generation = generation
        self._is_cancelled = is_cancelled
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            doc = fitz.open(self._path)
        except fitz.FileDataError:
            return
        try:
            for i in range(self._total_pages):
                if self._is_cancelled(self._generation):
                    return
                try:
                    png = render_page_png(doc, i, width_px=160)
                except ValueError:
                    return
                if self._is_cancelled(self._generation):
                    return
                pix = QPixmap()
                pix.loadFromData(png, "PNG")
                self.signals.page_ready.emit(self._generation, i, pix)
            self.signals.finished.emit(self._generation)
        finally:
            doc.close()


class ThumbnailGrid(QScrollArea):
    rendering_started = pyqtSignal(int)
    rendering_progress = pyqtSignal(int, int)
    rendering_finished = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._container = QWidget()
        self._layout = QGridLayout(self._container)
        self._layout.setSpacing(8)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.setWidget(self._container)

        self._cards: list[PageCard] = []
        self._loader: PdfLoader | None = None
        self._generation = 0
        self._thread_pool = QThreadPool.globalInstance()

    def load_pdf(self, loader: PdfLoader) -> None:
        self._cancel_rendering()
        self._clear_cards()
        self._loader = loader

        total = loader.page_count
        self._cards = [PageCard(i, self._container) for i in range(total)]
        self._reflow_grid()

        self._generation += 1
        generation = self._generation
        worker = ThumbnailWorker(
            loader.path,
            total,
            generation,
            self._is_cancelled,
        )
        worker.signals.page_ready.connect(self._on_page_ready)
        worker.signals.finished.connect(self._on_rendering_finished)
        self.rendering_started.emit(total)
        self._thread_pool.start(worker)

    def clear(self) -> None:
        self._cancel_rendering()
        self._clear_cards()
        self._loader = None

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reflow_grid()

    def _cancel_rendering(self) -> None:
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

    def _reflow_grid(self) -> None:
        if not self._cards:
            return

        spacing = self._layout.spacing()
        cols = max(
            1,
            (self.viewport().width() - 16) // (PageCard.CARD_WIDTH + spacing),
        )

        while self._layout.count():
            self._layout.takeAt(0)

        for index, card in enumerate(self._cards):
            self._layout.addWidget(card, index // cols, index % cols)

    def _on_page_ready(
        self, generation: int, page_index: int, pixmap: QPixmap
    ) -> None:
        if self._is_cancelled(generation):
            return
        self._cards[page_index].set_thumbnail(pixmap)
        self.rendering_progress.emit(page_index + 1, len(self._cards))

    def _on_rendering_finished(self, generation: int) -> None:
        if self._is_cancelled(generation):
            return
        self.rendering_finished.emit()
