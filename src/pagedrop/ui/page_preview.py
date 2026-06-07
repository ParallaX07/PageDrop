from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QPixmap, QResizeEvent, QShowEvent, QWheelEvent
from PyQt6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX, PdfLoader
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    MIN_PREVIEW_RENDER_WIDTH,
    ZOOM_WHEEL_STEP,
)


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loader: PdfLoader | None = None
        self._current_page = 0
        self._render_width_px = 1200
        self._manual_zoom = False

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

        self._footer = QWidget()
        self._footer.setObjectName("PreviewFooter")
        footer_layout = QVBoxLayout(self._footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)

        self._hint_label = QLabel(
            "← → or ↑ ↓ change page  ·  Ctrl+scroll zoom  ·  Esc back to grid"
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

    def set_loader(self, loader: PdfLoader | None) -> None:
        self._loader = loader
        if loader is None:
            self._current_page = 0
            self._manual_zoom = False
            self._image_label.clear()

    def reset_zoom_to_fit(self) -> None:
        self._manual_zoom = False
        self._update_render_width()

    def show_page(self, page_index: int) -> None:
        if self._loader is None:
            return
        self._current_page = max(0, min(page_index, self._loader.page_count - 1))
        self._update_render_width()
        self._render_current_page()

    def zoom_by(self, step: int) -> None:
        if self._loader is None:
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
        self._render_current_page()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._loader is not None:
            self._update_render_width()
            self._render_current_page()
        self.setFocus()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.isVisible() and self._loader is not None:
            previous_width = self._render_width_px
            self._update_render_width()
            if self._render_width_px != previous_width:
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
        if self._loader is None:
            return
        clamped = max(0, min(page_index, self._loader.page_count - 1))
        if clamped == self._current_page:
            return
        self._current_page = clamped
        self._render_current_page()
        self.page_changed.emit(self._current_page)

    def _render_current_page(self) -> None:
        if self._loader is None:
            return
        png = self._loader.render_page(
            self._current_page,
            width_px=self._render_width_px,
        )
        pixmap = QPixmap()
        pixmap.loadFromData(png, "PNG")
        self._image_label.setPixmap(pixmap)
        self._image_label.adjustSize()


# Backward-compatible alias for older imports.
PagePreviewDialog = PagePreviewWidget
