from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QPixmap, QResizeEvent
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX, PdfLoader


class PagePreviewDialog(QDialog):
    """Maximized single-page preview with arrow-key navigation."""

    def __init__(
        self,
        loader: PdfLoader,
        start_page: int = 0,
        on_page_changed: Callable[[int], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._loader = loader
        self._current_page = max(0, min(start_page, loader.page_count - 1))
        self._on_page_changed = on_page_changed
        self._render_width_px = 1200

        self.setObjectName("PagePreviewDialog")
        self.setWindowTitle(self._title_text())
        self.setMinimumSize(640, 480)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("PagePreviewScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._image_label = QLabel()
        self._image_label.setObjectName("PagePreviewImage")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidget(self._image_label)
        layout.addWidget(self._scroll, stretch=1)

        self._hint_label = QLabel(
            "← → or ↑ ↓ to change pages  ·  Esc to close"
        )
        self._hint_label.setObjectName("PagePreviewHint")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint_label)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_render_width()
        self._render_current_page()
        self.setFocus()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self._update_render_width()
            self._render_current_page()

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
        if key == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def _title_text(self) -> str:
        return (
            f"Preview — Page {self._current_page + 1} of {self._loader.page_count}"
        )

    def _update_render_width(self) -> None:
        viewport = self._scroll.viewport()
        available = max(viewport.width() - 32, 400)
        self._render_width_px = min(MAX_RENDER_WIDTH_PX, available)

    def _go_to_page(self, page_index: int) -> None:
        clamped = max(0, min(page_index, self._loader.page_count - 1))
        if clamped == self._current_page:
            return
        self._current_page = clamped
        self.setWindowTitle(self._title_text())
        self._render_current_page()
        if self._on_page_changed is not None:
            self._on_page_changed(self._current_page)

    def _render_current_page(self) -> None:
        png = self._loader.render_page(
            self._current_page,
            width_px=self._render_width_px,
        )
        pixmap = QPixmap()
        pixmap.loadFromData(png, "PNG")
        self._image_label.setPixmap(pixmap)
        self._image_label.adjustSize()
