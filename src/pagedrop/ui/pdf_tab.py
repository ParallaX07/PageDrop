from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.page_preview import PagePreviewWidget
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.utils.temp_manager import TempManager


class PdfTab(QWidget):
    """Per-tab document workspace: thumbnail grid, preview pane, and zoom state."""

    pdf_loaded = pyqtSignal()
    pdf_closed = pyqtSignal()
    dirty_changed = pyqtSignal(bool)

    def __init__(
        self,
        temp_manager: TempManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._temp_manager = temp_manager
        self._loader: PdfLoader | None = None
        self._pdf_path: str | None = None
        self._dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._content_stack = QStackedWidget()
        self._content_stack.setObjectName("TabContentStack")

        self._thumbnail_grid = ThumbnailGrid(temp_manager=self._temp_manager)
        self._thumbnail_grid.set_empty_state_message(
            "Open a PDF to begin",
            show_hint=False,
        )
        self._preview_widget = PagePreviewWidget()
        self._preview_widget.closed.connect(self.close_preview)

        self._content_stack.addWidget(self._thumbnail_grid)
        self._content_stack.addWidget(self._preview_widget)
        layout.addWidget(self._content_stack)

    @property
    def thumbnail_grid(self) -> ThumbnailGrid:
        return self._thumbnail_grid

    @property
    def preview_widget(self) -> PagePreviewWidget:
        return self._preview_widget

    @property
    def content_stack(self) -> QStackedWidget:
        return self._content_stack

    @property
    def loader(self) -> PdfLoader | None:
        return self._loader

    @property
    def pdf_path(self) -> str | None:
        return self._pdf_path

    @property
    def is_blank(self) -> bool:
        return self._loader is None

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def tab_title(self) -> str:
        if self._pdf_path is None:
            return "New Tab"
        filename = Path(self._pdf_path).name
        return f"{filename}*" if self._dirty else filename

    @property
    def zoom_level(self) -> int:
        return self._thumbnail_grid.thumbnail_width_px

    def set_zoom_level(self, thumbnail_width_px: int) -> None:
        self._thumbnail_grid.set_thumbnail_zoom(thumbnail_width_px)

    def is_preview_visible(self) -> bool:
        return self._content_stack.currentWidget() is self._preview_widget

    def show_preview_at(self, page_index: int) -> None:
        if self._loader is None:
            return
        self._preview_widget.reset_zoom_to_fit()
        self._preview_widget.show_page(page_index)
        self._content_stack.setCurrentWidget(self._preview_widget)

    def close_preview(self) -> None:
        if not self.is_preview_visible():
            return
        self._content_stack.setCurrentWidget(self._thumbnail_grid)

    def load_pdf(self, path: str) -> PdfLoader:
        """Open *path* in this tab. Raises PdfLoadError subclasses on failure."""
        self.close_preview()
        self._thumbnail_grid.cancel_rendering()
        if self._loader is not None:
            self._thumbnail_grid.clear()
            self._loader.close()
            self._loader = None
            self._pdf_path = None

        loader = PdfLoader(path)
        self._loader = loader
        self._pdf_path = path
        self._preview_widget.set_loader(loader)
        self._thumbnail_grid.load_pdf(loader)
        self.pdf_loaded.emit()
        return loader

    def close_loader(self) -> None:
        """Cancel rendering, release the loader, and reset to a blank tab."""
        self.close_preview()
        self._thumbnail_grid.cancel_rendering()
        self._thumbnail_grid.clear()
        if self._loader is not None:
            self._loader.close()
            self._loader = None
        self._pdf_path = None
        if self._dirty:
            self._dirty = False
            self.dirty_changed.emit(False)
        self._preview_widget.set_loader(None)
        self.pdf_closed.emit()
