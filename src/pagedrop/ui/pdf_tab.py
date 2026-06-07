from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from pagedrop.core.pdf_editor import PageRef, PdfEditModel
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
        self._edit_model: PdfEditModel | None = None
        self._loader_cache: dict[str, PdfLoader] = {}
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
            hint="Choose a file or drop one onto the grid",
            show_hint=True,
        )
        self._thumbnail_grid.pages_reordered.connect(self._on_pages_reordered)
        self._thumbnail_grid.pages_inserted.connect(self._on_pages_inserted)
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
    def edit_model(self) -> PdfEditModel | None:
        return self._edit_model

    @property
    def loader(self) -> PdfLoader | None:
        if self._edit_model is None:
            return None
        return self.get_loader(self._edit_model.original_path)

    @property
    def pdf_path(self) -> str | None:
        return self._pdf_path

    @property
    def original_path(self) -> str | None:
        if self._edit_model is None:
            return None
        return self._edit_model.original_path

    @property
    def is_blank(self) -> bool:
        return self._edit_model is None

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def tab_title(self) -> str:
        if self._edit_model is None:
            return "New Tab"
        display_path = self._edit_model.save_path or self._edit_model.original_path
        filename = Path(display_path).name
        return f"{filename}*" if self._dirty else filename

    @property
    def zoom_level(self) -> int:
        return self._thumbnail_grid.thumbnail_width_px

    def set_zoom_level(self, thumbnail_width_px: int) -> None:
        self._thumbnail_grid.set_thumbnail_zoom(thumbnail_width_px)

    def is_preview_visible(self) -> bool:
        return self._content_stack.currentWidget() is self._preview_widget

    def show_preview_at(self, page_index: int) -> None:
        if self._edit_model is None:
            return
        self._preview_widget.reset_zoom_to_fit()
        self._preview_widget.show_page(page_index)
        self._content_stack.setCurrentWidget(self._preview_widget)

    def close_preview(self) -> None:
        if not self.is_preview_visible():
            return
        self._content_stack.setCurrentWidget(self._thumbnail_grid)

    def get_loader(self, path: str) -> PdfLoader:
        if path not in self._loader_cache:
            self._loader_cache[path] = PdfLoader(path)
        return self._loader_cache[path]

    def load_pdf(self, path: str) -> PdfLoader:
        """Open *path* in this tab. Raises PdfLoadError subclasses on failure."""
        self.close_preview()
        self._thumbnail_grid.cancel_rendering()
        if self._edit_model is not None:
            self._thumbnail_grid.clear()
            self._close_loader_cache()
            self._edit_model = None
            self._pdf_path = None

        loader = PdfLoader(path)
        self._loader_cache[path] = loader
        self._edit_model = PdfEditModel(path, loader.page_count)
        self._pdf_path = path
        self._sync_dirty_from_model()

        get_loader: Callable[[str], PdfLoader] = self.get_loader
        self._preview_widget.set_model(self._edit_model, get_loader)
        self._thumbnail_grid.load_model(self._edit_model, get_loader)
        self.pdf_loaded.emit()
        return loader

    def delete_selected_pages(self) -> bool:
        """Delete the current thumbnail selection; no-op when nothing is selected."""
        if self._edit_model is None:
            return False
        if not self._thumbnail_grid.selection_manager.selection:
            return False
        self.close_preview()
        if not self._thumbnail_grid.delete_selected_pages():
            return False
        self._sync_dirty_from_model()
        return True

    def move_selected_pages_up(self) -> bool:
        """Move the current thumbnail selection up; no-op when not movable."""
        if self._edit_model is None:
            return False
        if not self._thumbnail_grid.can_move_selection_up():
            return False
        self.close_preview()
        if not self._thumbnail_grid.move_selection_up():
            return False
        self._sync_dirty_from_model()
        return True

    def move_selected_pages_down(self) -> bool:
        """Move the current thumbnail selection down; no-op when not movable."""
        if self._edit_model is None:
            return False
        if not self._thumbnail_grid.can_move_selection_down():
            return False
        self.close_preview()
        if not self._thumbnail_grid.move_selection_down():
            return False
        self._sync_dirty_from_model()
        return True

    def _on_pages_reordered(self) -> None:
        self.close_preview()
        self._sync_dirty_from_model()

    def _on_pages_inserted(self) -> None:
        self.close_preview()
        self._sync_dirty_from_model()

    def init_from_page_refs(self, refs: list[PageRef]) -> None:
        """Initialize a blank tab from a cross-window page transfer."""
        if not refs or self._edit_model is not None:
            return

        for ref in refs:
            self.get_loader(ref.source_path)

        primary = refs[0].source_path
        self._edit_model = PdfEditModel.with_pages(primary, refs)
        self._pdf_path = primary
        self._sync_dirty_from_model()

        get_loader: Callable[[str], PdfLoader] = self.get_loader
        self._preview_widget.set_model(self._edit_model, get_loader)
        self._thumbnail_grid.load_model(self._edit_model, get_loader)
        self.pdf_loaded.emit()

    def close_loader(self) -> None:
        """Cancel rendering, release loaders, and reset to a blank tab."""
        self.close_preview()
        self._thumbnail_grid.cancel_rendering()
        self._thumbnail_grid.clear()
        self._close_loader_cache()
        self._edit_model = None
        self._pdf_path = None
        if self._dirty:
            self._dirty = False
            self.dirty_changed.emit(False)
        self._preview_widget.set_model(None, None)
        self.pdf_closed.emit()

    def _close_loader_cache(self) -> None:
        for loader in self._loader_cache.values():
            loader.close()
        self._loader_cache.clear()

    def _sync_dirty_from_model(self) -> None:
        dirty = self._edit_model.is_dirty() if self._edit_model is not None else False
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)
