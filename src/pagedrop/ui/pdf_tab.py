from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.dialogs import confirm_delete_pages
from pagedrop.ui.page_preview import PagePreviewWidget
from pagedrop.ui.settings import thumbnail_quality
from pagedrop.ui.theme import DEFAULT_THUMBNAIL_WIDTH
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.utils.temp_manager import TempManager

_INVALID_TAB_TITLE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Unused source loaders kept for undo/re-drop; 0 = close as soon as unreferenced.
LOADER_CACHE_IDLE_MAX = 0

# Suggest smaller thumbnails when both thresholds are met — never silent-cap quality.
QUALITY_GUIDANCE_MIN_PAGES = 60
QUALITY_GUIDANCE_MIN_ZOOM_PX = DEFAULT_THUMBNAIL_WIDTH * 2


def sanitize_tab_title_stem(title: str) -> str:
    """Return a filesystem-safe stem derived from a display tab title."""
    cleaned = _INVALID_TAB_TITLE_CHARS.sub("_", title.strip())
    if cleaned.lower().endswith(".pdf"):
        cleaned = cleaned[:-4].rstrip()
    return cleaned or "untitled"


class PdfTab(QWidget):
    """Per-tab document workspace: thumbnail grid, preview pane, and zoom state."""

    pdf_loaded = pyqtSignal()
    pdf_closed = pyqtSignal()
    dirty_changed = pyqtSignal(bool)
    tab_title_changed = pyqtSignal()

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
        self._drop_initialized = False
        self._custom_tab_title: str | None = None
        self._quality_guidance_shown = False

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
    def is_drop_initialized(self) -> bool:
        """True when this tab was created by dropping pages onto a blank tab."""
        return self._drop_initialized

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def can_rename_tab(self) -> bool:
        """True when the tab has no saved path yet (blank or unsaved document)."""
        if self._edit_model is None:
            return True
        return self._edit_model.save_path is None

    @property
    def custom_tab_title(self) -> str | None:
        return self._custom_tab_title

    @property
    def tab_title(self) -> str:
        if self._edit_model is None:
            return self._custom_tab_title or "New Tab"
        if self._edit_model.save_path is not None:
            filename = Path(self._edit_model.save_path).name
            return f"{filename}*" if self._dirty else filename
        if self._custom_tab_title is not None:
            title = self._custom_tab_title
            return f"{title}*" if self._dirty else title
        filename = Path(self._edit_model.original_path).name
        return f"{filename}*" if self._dirty else filename

    def suggested_save_stem(self) -> str:
        if self._custom_tab_title is not None:
            return sanitize_tab_title_stem(self._custom_tab_title)
        if self._edit_model is None:
            return "untitled"
        if self._edit_model.save_path is not None:
            return Path(self._edit_model.save_path).stem
        if self._drop_initialized:
            return "untitled"
        return f"{Path(self._edit_model.original_path).stem}_edited"

    def set_custom_tab_title(self, title: str | None) -> bool:
        """Set a display title for an unsaved tab. Returns True when changed."""
        if not self.can_rename_tab:
            return False

        cleaned = (title or "").strip()
        if cleaned.lower().endswith(".pdf"):
            cleaned = cleaned[:-4].rstrip()
        cleaned = cleaned or None
        if cleaned == self._custom_tab_title:
            return False

        self._custom_tab_title = cleaned
        self.tab_title_changed.emit()
        return True

    def clear_custom_tab_title(self) -> None:
        if self._custom_tab_title is None:
            return
        self._custom_tab_title = None
        self.tab_title_changed.emit()

    @property
    def zoom_level(self) -> int:
        return self._thumbnail_grid.thumbnail_width_px

    def set_zoom_level(
        self, thumbnail_width_px: int, *, manual: bool = False
    ) -> None:
        self._thumbnail_grid.set_thumbnail_zoom(
            thumbnail_width_px, manual=manual
        )

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
        self._evict_idle_loaders(keep={path})
        return self._loader_cache[path]

    def load_pdf(
        self, path: str, password: str | None = None
    ) -> PdfLoader:
        """Open *path* in this tab. Raises PdfLoadError subclasses on failure."""
        self.close_preview()
        self._thumbnail_grid.cancel_rendering()
        if self._edit_model is not None:
            self._thumbnail_grid.clear()
            self._close_loader_cache()
        self._edit_model = None
        self._pdf_path = None
        self._custom_tab_title = None
        self._quality_guidance_shown = False

        loader = PdfLoader(path, password=password)
        self._loader_cache[path] = loader
        self._edit_model = PdfEditModel(path, loader.page_count)
        self._pdf_path = path
        self._drop_initialized = False
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
        selection = self._thumbnail_grid.selection_manager.selection
        if not selection:
            return False
        if not confirm_delete_pages(self, len(selection)):
            return False
        self.close_preview()
        if not self._thumbnail_grid.delete_selected_pages():
            return False
        self._sync_dirty_from_model()
        return True

    def undo_edit(self) -> bool:
        """Undo the last page-list edit and refresh the grid."""
        if self._edit_model is None or not self._edit_model.can_undo():
            return False
        self.close_preview()
        if not self._edit_model.undo():
            return False
        self._thumbnail_grid.reload_from_model()
        self._sync_dirty_from_model()
        return True

    def redo_edit(self) -> bool:
        """Redo the last undone page-list edit and refresh the grid."""
        if self._edit_model is None or not self._edit_model.can_redo():
            return False
        self.close_preview()
        if not self._edit_model.redo():
            return False
        self._thumbnail_grid.reload_from_model()
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

    def duplicate_selected_pages(self) -> int:
        """Duplicate the current selection after the last selected page."""
        if self._edit_model is None or self.is_preview_visible():
            return 0
        self.close_preview()
        count = self._thumbnail_grid.duplicate_selected_pages()
        if count:
            self._sync_dirty_from_model()
        return count

    def rotate_selected_pages(self, delta_degrees: int) -> bool:
        """Rotate the current selection by *delta_degrees*."""
        if self._edit_model is None or self.is_preview_visible():
            return False
        if not self._thumbnail_grid.rotate_selected_pages(delta_degrees):
            return False
        self._sync_dirty_from_model()
        return True

    def selected_page_refs(self) -> list[PageRef]:
        """Return PageRefs for the current thumbnail selection (logical order)."""
        if self._edit_model is None:
            return []
        ordered = sorted(self._thumbnail_grid.selection_manager.selection)
        return [self._edit_model.page_at(index) for index in ordered]

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
        self._drop_initialized = True
        self._quality_guidance_shown = False
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
        self._drop_initialized = False
        self._custom_tab_title = None
        self._quality_guidance_shown = False
        if self._dirty:
            self._dirty = False
            self.dirty_changed.emit(False)
        self._preview_widget.set_model(None, None)
        self.pdf_closed.emit()

    def quality_scale_guidance(self) -> str | None:
        """Status tip when a large tab is at high zoom. Never changes quality."""
        if self._quality_guidance_shown or self._edit_model is None:
            return None
        if self._edit_model.logical_count() < QUALITY_GUIDANCE_MIN_PAGES:
            return None
        if self.zoom_level < QUALITY_GUIDANCE_MIN_ZOOM_PX:
            return None
        self._quality_guidance_shown = True
        if thumbnail_quality() == "low":
            return (
                "Large document at high zoom — try a smaller thumbnail size "
                "for smoother scrolling"
            )
        return (
            "Large document at high zoom — try a smaller thumbnail size, "
            "or View → Thumbnail quality"
        )

    def _close_loader_cache(self) -> None:
        for loader in self._loader_cache.values():
            loader.close()
        self._loader_cache.clear()

    def _evict_idle_loaders(self, *, keep: set[str] | None = None) -> None:
        """Close unreferenced source loaders beyond LOADER_CACHE_IDLE_MAX."""
        if not self._loader_cache:
            return
        live = self._edit_model.source_paths() if self._edit_model is not None else set()
        if keep:
            live |= keep
        idle = [path for path in self._loader_cache if path not in live]
        # ponytail: dict order ≈ insertion; good enough when IDLE_MAX > 0
        for path in idle[LOADER_CACHE_IDLE_MAX:]:
            loader = self._loader_cache.pop(path, None)
            if loader is not None:
                loader.close()

    def _sync_dirty_from_model(self) -> None:
        dirty = self._edit_model.is_dirty() if self._edit_model is not None else False
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)
        self._evict_idle_loaders()
