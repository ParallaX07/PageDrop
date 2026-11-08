from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QResizeEvent, QShowEvent
from PyQt6.QtWidgets import (
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.jobs.credentials import RuntimeCredentials
from pagedrop.core.markup import MarkupSession
from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_loader import (
    PdfLoader,
    PdfPasswordError,
    PdfPasswordRequiredError,
)
from pagedrop.core.pdf_service import invalidate_doc_cache
from pagedrop.ui.dialogs import confirm_delete_pages
from pagedrop.ui.document_panel import DocumentPanel
from pagedrop.ui.pdf_viewer import PdfViewerWidget
from pagedrop.ui.section_index import SectionIndex
from pagedrop.ui.settings import (
    document_panel_visible,
    document_panel_width,
    sections_visible,
    sections_width,
    set_document_panel_visible,
    set_document_panel_width,
    set_sections_visible,
    set_sections_width,
    thumbnail_quality,
)
from pagedrop.ui.recovery import RecoveryError, read_draft, write_draft
from pagedrop.ui.start_screen import StartScreen
from pagedrop.ui.theme import DEFAULT_THUMBNAIL_WIDTH
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.utils.temp_manager import TempManager

_INVALID_TAB_TITLE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Unused source loaders kept for undo/re-drop; 0 = close as soon as unreferenced.
LOADER_CACHE_IDLE_MAX = 0

# Suggest smaller thumbnails when both thresholds are met — never silent-cap quality.
QUALITY_GUIDANCE_MIN_PAGES = 60
QUALITY_GUIDANCE_MIN_ZOOM_PX = DEFAULT_THUMBNAIL_WIDTH * 2

# Side panes of the editor. The grid keeps at least GRID_MIN_ROOM pixels: the
# Document panel gives way first, then the Sections pane.
SECTIONS_DEFAULT_WIDTH = 176
DOCUMENT_PANEL_DEFAULT_WIDTH = 300
GRID_MIN_ROOM = 400
SECTIONS_HIDE_BELOW = SECTIONS_DEFAULT_WIDTH + GRID_MIN_ROOM
DOCUMENT_PANEL_HIDE_BELOW = SECTIONS_DEFAULT_WIDTH + DOCUMENT_PANEL_DEFAULT_WIDTH + GRID_MIN_ROOM
SIDE_PANE_MIN_WIDTH = 120
SIDE_PANE_MAX_WIDTH = 600
SPLITTER_HANDLE_WIDTH = 5

PANE_SECTIONS = "sections"
PANE_DOCUMENT = "document"


class _PaneSpec(NamedTuple):
    slot: int  # position in the splitter
    default_width: int
    hide_below: int
    get_visible: Callable[[], bool]
    set_visible: Callable[[bool], None]
    get_width: Callable[[int], int]
    set_width: Callable[[int], None]


_PANES = {
    PANE_SECTIONS: _PaneSpec(
        0, SECTIONS_DEFAULT_WIDTH, SECTIONS_HIDE_BELOW,
        sections_visible, set_sections_visible, sections_width, set_sections_width,
    ),
    PANE_DOCUMENT: _PaneSpec(
        2, DOCUMENT_PANEL_DEFAULT_WIDTH, DOCUMENT_PANEL_HIDE_BELOW,
        document_panel_visible, set_document_panel_visible,
        document_panel_width, set_document_panel_width,
    ),
}

_UNSET = object()


def sanitize_tab_title_stem(title: str) -> str:
    """Return a filesystem-safe stem derived from a display tab title."""
    cleaned = _INVALID_TAB_TITLE_CHARS.sub("_", title.strip())
    if cleaned.lower().endswith(".pdf"):
        cleaned = cleaned[:-4].rstrip()
    return cleaned or "untitled"


class PdfTab(QWidget):
    """Per-tab document workspace: thumbnail grid, full viewer, and zoom state."""

    pdf_loaded = pyqtSignal()
    pdf_closed = pyqtSignal()
    dirty_changed = pyqtSignal(bool)
    tab_title_changed = pyqtSignal()
    recovery_failed = pyqtSignal(str)
    # A side pane was shown or hidden, or the tab became blank or got a document.
    workspace_panes_changed = pyqtSignal()

    def __init__(
        self,
        temp_manager: TempManager,
        parent: QWidget | None = None,
        recovery_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._temp_manager = temp_manager
        self._edit_model: PdfEditModel | None = None
        self._markup = MarkupSession()
        # Main-thread only — never pass these docs into QRunnable workers
        # (see core.thread_policy). Workers open by path themselves.
        self._loader_cache: dict[str, PdfLoader] = {}
        # ponytail: tab PdfLoader vs pdf_service interactive cache — dual owners
        # by design (see PdfLoader / pdf_service). Not a third MuPDF doc cache.
        # Runtime-only unlock secrets for open sources (Save As / extract /
        # get_loader cache miss). Dropped on tab close — never QSettings.
        # passwords stay as str; Python can't scrub interned strings.
        self._credentials = RuntimeCredentials()
        self._pdf_path: str | None = None
        self._dirty = False
        self._drop_initialized = False
        self._custom_tab_title: str | None = None
        # Name of the index colour token (e.g. "index_clay"); set by the first
        # tab strip that hosts the tab and kept when it moves or detaches.
        self.index_colour: str | None = None
        self._quality_guidance_shown = False
        self._recovery_path = (
            recovery_dir / f"{uuid4().hex}.json" if recovery_dir is not None else None
        )
        self._recovery_error_reported = False
        # Remembered preference per pane (app-wide), whether the tab is currently
        # narrower than the pane's threshold, and whether the user turned the pane
        # on anyway while it was.
        self._pane_pref = {name: spec.get_visible() for name, spec in _PANES.items()}
        self._narrow = dict.fromkeys(_PANES, False)
        self._forced = dict.fromkeys(_PANES, False)
        self._applying_panes = False
        self._last_pane_state: tuple[bool, bool, bool] | None = None
        self._outline_paths: frozenset[str] | None = None
        self._panel_path: object = _UNSET

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._section_index = SectionIndex()
        self._section_index.section_activated.connect(self._on_section_activated)
        self._content_stack = QStackedWidget()
        self._content_stack.setObjectName("TabContentStack")

        self._thumbnail_grid = ThumbnailGrid(temp_manager=self._temp_manager)
        self._thumbnail_grid.set_annotation_provider(
            self._pending_annotations_for_page
        )
        self._thumbnail_grid.pages_reordered.connect(self._on_pages_reordered)
        self._thumbnail_grid.pages_inserted.connect(self._on_pages_inserted)
        self._thumbnail_grid.selection_changed.connect(self._on_grid_selection_changed)
        # Preview / Enter / double-click opens the full viewer.
        self._preview_widget = PdfViewerWidget()
        self._preview_widget.closed.connect(self.close_preview)
        self._preview_widget.markup_changed.connect(self._on_markup_changed)
        # The stack sizes itself from every page, hidden ones included. Let the
        # viewer's side panels give way instead of setting the window's floor.
        self._preview_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored
        )

        # Shown instead of the grid while the tab has no document.
        self._start_screen = StartScreen()
        self._start_screen.set_drop_target(self._thumbnail_grid)

        self._content_stack.addWidget(self._thumbnail_grid)
        self._content_stack.addWidget(self._preview_widget)
        self._content_stack.addWidget(self._start_screen)
        self._content_stack.setCurrentWidget(self._start_screen)

        self._document_panel = DocumentPanel()
        # Side panes give way before the window floor does.
        for pane in (self._section_index, self._document_panel):
            pane.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("WorkspaceSplitter")
        self._splitter.setHandleWidth(SPLITTER_HANDLE_WIDTH)
        self._splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._splitter.addWidget(self._section_index)
        self._splitter.addWidget(self._content_stack)
        self._splitter.addWidget(self._document_panel)
        self._splitter.setCollapsible(0, True)
        self._splitter.setCollapsible(1, False)
        self._splitter.setCollapsible(2, True)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.splitterMoved.connect(self._on_splitter_moved)
        layout.addWidget(self._splitter)

        # Sections list, then the grid or viewer, then the document list.
        QWidget.setTabOrder(self._section_index, self._start_screen.open_button)
        QWidget.setTabOrder(self._start_screen.recent_list, self._thumbnail_grid)
        QWidget.setTabOrder(self._thumbnail_grid, self._preview_widget)
        QWidget.setTabOrder(self._preview_widget, self._document_panel)
        self._apply_panes()

    @property
    def thumbnail_grid(self) -> ThumbnailGrid:
        return self._thumbnail_grid

    @property
    def preview_widget(self) -> PdfViewerWidget:
        """Full viewer stack page (kept name for MainWindow / test wiring)."""
        return self._preview_widget

    @property
    def viewer_widget(self) -> PdfViewerWidget:
        return self._preview_widget

    @property
    def start_screen(self) -> StartScreen:
        return self._start_screen

    @property
    def content_stack(self) -> QStackedWidget:
        return self._content_stack

    @property
    def section_index(self) -> SectionIndex:
        return self._section_index

    @property
    def document_panel(self) -> DocumentPanel:
        return self._document_panel

    @property
    def workspace_splitter(self) -> QSplitter:
        return self._splitter

    def workspace_pane_visible(self, pane: str) -> bool:
        """Whether *pane* (``PANE_SECTIONS`` or ``PANE_DOCUMENT``) is showing."""
        return self._pane_wanted(pane)

    def set_workspace_pane_visible(self, pane: str, visible: bool) -> None:
        """Turn *pane* on or off for every tab; a pane turned on stays on while narrow."""
        if self._edit_model is None:
            return
        self._pane_pref[pane] = visible
        _PANES[pane].set_visible(visible)
        self._forced[pane] = visible and self._narrow[pane]
        self._apply_panes()

    def _pane_widget(self, pane: str) -> QWidget:
        return self._section_index if pane == PANE_SECTIONS else self._document_panel

    def _pane_wanted(self, pane: str) -> bool:
        return (
            self._edit_model is not None
            and self._pane_pref[pane]
            and (not self._narrow[pane] or self._forced[pane])
        )

    def _apply_panes(self, *, resize: bool = False) -> None:
        if self._applying_panes:
            return
        self._applying_panes = True
        try:
            width = self.width()
            for pane, spec in _PANES.items():
                narrow = width < spec.hide_below
                if narrow != self._narrow[pane]:
                    self._narrow[pane] = narrow
                    self._forced[pane] = False
            changed = resize
            for pane in _PANES:
                widget = self._pane_widget(pane)
                wanted = self._pane_wanted(pane)
                if widget.isHidden() == wanted:
                    widget.setVisible(wanted)
                    changed = True
            if changed:
                self._size_splitter()
        finally:
            self._applying_panes = False
        state = (
            self._edit_model is None,
            self._pane_wanted(PANE_SECTIONS),
            self._pane_wanted(PANE_DOCUMENT),
        )
        if state != self._last_pane_state:
            self._last_pane_state = state
            self.workspace_panes_changed.emit()

    def _size_splitter(self) -> None:
        sizes = [0, 0, 0]
        for pane, spec in _PANES.items():
            if self._pane_wanted(pane):
                width = spec.get_width(spec.default_width)
                sizes[spec.slot] = max(SIDE_PANE_MIN_WIDTH, min(SIDE_PANE_MAX_WIDTH, width))
        handles = sum(1 for size in sizes if size) * SPLITTER_HANDLE_WIDTH
        sizes[1] = max(self.width() - sizes[0] - sizes[2] - handles, 0)
        self._splitter.setSizes(sizes)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        if self._applying_panes:
            return
        sizes = self._splitter.sizes()
        for pane, spec in _PANES.items():
            if not self._pane_wanted(pane):
                continue
            if sizes[spec.slot] <= 0:
                # Dragged fully closed counts as hiding it.
                self.set_workspace_pane_visible(pane, False)
            else:
                spec.set_width(sizes[spec.slot])

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # Preferences are app-wide: pick up what another tab changed.
        self._pane_pref = {name: spec.get_visible() for name, spec in _PANES.items()}
        self._section_index.set_index_colour(self.index_colour or "index_slate")
        self._apply_panes(resize=True)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_panes()

    def _document_path(self) -> str | None:
        """The document's own file, or None when it only lives in temporary staging."""
        model = self._edit_model
        if model is None:
            return None
        if model.save_path:
            return model.save_path
        if self._drop_initialized:
            return None
        path = model.original_path
        try:
            if Path(path).resolve().is_relative_to(self._temp_manager.get_dir().resolve()):
                return None
        except OSError:
            return None
        return path

    def _sync_start_screen(self) -> None:
        """The start screen is the current page exactly while the tab is blank."""
        stack = self._content_stack
        if self._edit_model is None:
            stack.setCurrentWidget(self._start_screen)
        elif stack.currentWidget() is self._start_screen:
            stack.setCurrentWidget(self._thumbnail_grid)

    def _refresh_workspace_panes(self) -> None:
        """Bring both side panes in line with the edit model."""
        model = self._edit_model
        self._sync_start_screen()
        if model is None:
            self._outline_paths = None
            self._panel_path = _UNSET
            self._section_index.clear()
            self._document_panel.clear()
            self._apply_panes()
            return
        count = model.logical_count()
        paths = frozenset(model.current_reference_paths())
        if paths != self._outline_paths:
            self._outline_paths = paths
            self._section_index.set_index_colour(self.index_colour or "index_slate")
            self._section_index.load(sorted(paths), self._credentials.snapshot() or None)
        self._section_index.refresh(model.iter_pages())
        path = self._document_path()
        if self._panel_path is _UNSET or path != self._panel_path:
            self._panel_path = path
            self._document_panel.set_document(count, path)
        else:
            self._document_panel.set_page_count(count)
        self._document_panel.set_selection(
            len(self._thumbnail_grid.selection_manager.selection), count
        )
        self._apply_panes()

    def _on_grid_selection_changed(self, selection: set[int]) -> None:
        if self._edit_model is not None:
            self._document_panel.set_selection(
                len(selection), self._edit_model.logical_count()
            )

    def _on_section_activated(self, index: int) -> None:
        model = self._edit_model
        if model is None or not 0 <= index < model.logical_count():
            return
        if self.is_viewer_mode():
            self._preview_widget.go_to_page(index)
        else:
            self._thumbnail_grid.scroll_to_page(index)

    def attach_context_toolbar(self, toolbar: QToolBar) -> None:
        """Place the window-owned editor toolbar directly above this tab's content."""
        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)
        layout.insertWidget(0, toolbar)
        layout.setStretch(0, 1)
        toolbar.show()

    def detach_context_toolbar(self, toolbar: QToolBar) -> None:
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            layout.removeWidget(toolbar)
        toolbar.hide()

    @property
    def edit_model(self) -> PdfEditModel | None:
        return self._edit_model

    @property
    def markup_session(self) -> MarkupSession:
        return self._markup

    @property
    def credentials(self) -> RuntimeCredentials:
        return self._credentials

    def peek_markup_ops(self):
        return self._markup.ops(self._edit_model)

    def clear_markup_after_save(self) -> None:
        # Ordinary Save As applies annotation/form ops only. Pending redaction
        # marks stay until a verified redaction Save As clears them.
        self._markup.clear_non_redactions()
        self._preview_widget.refresh_markup_overlays()

    def clear_redactions_after_apply(self) -> None:
        """Drop redaction marks after verified Save As (output already written)."""
        self._markup.clear_redactions()
        self._preview_widget.refresh_markup_overlays()

    def commit_saved_output(self, path: str) -> None:
        """Rebase this tab after a staged output has been promoted successfully."""
        assert self._edit_model is not None
        # Open first: a failed reopen must leave the current tab untouched.
        saved_loader = PdfLoader(path)
        self.close_preview()
        self._thumbnail_grid.cancel_rendering()
        self._close_loader_cache()
        self._loader_cache[path] = saved_loader
        self._edit_model.rebase_saved_output(path)
        self._markup.clear()
        self._pdf_path = path
        self._drop_initialized = False
        self._custom_tab_title = None
        self._preview_widget.set_model(None, None)
        self._thumbnail_grid.load_model(self._edit_model, self.get_loader)
        self._sync_dirty_from_model()

    @property
    def recovery_path(self) -> Path | None:
        return self._recovery_path

    def restore_recovery_draft(
        self,
        path: Path,
        ask_password: Callable[[str, bool], str | None] | None = None,
    ) -> None:
        """Load one persisted draft into this blank tab.

        *ask_password(source, incorrect)* is asked for protected sources; None
        cancels, which raises the password error and leaves the draft file alone.
        """
        if self._edit_model is not None:
            raise RecoveryError("Recovery needs a blank tab")
        recovered = read_draft(path)
        entered: dict[str, str] = {}
        for source in recovered.model.current_reference_paths():
            password: str | None = None
            while True:
                try:
                    loader = PdfLoader(source, password=password)
                    break
                except (PdfPasswordRequiredError, PdfPasswordError) as exc:
                    if ask_password is None:
                        raise
                    password = ask_password(
                        source, isinstance(exc, PdfPasswordError)
                    )
                    if password is None:
                        raise
            if password is not None:
                entered[source] = password
            try:
                if any(
                    page.source_path == source
                    and not 0 <= page.source_index < loader.page_count
                    for page in recovered.model.iter_pages()
                ):
                    raise RecoveryError(f"Recovery refers to a missing page in {source}")
            finally:
                loader.close()
        for source, password in entered.items():
            self._credentials.set(source, password)
        self._edit_model = recovered.model
        self._markup.bind_model(self._edit_model)
        self._markup.restore(recovered.markup)
        self._pdf_path = self._edit_model.original_path
        self._drop_initialized = recovered.drop_initialized
        self._custom_tab_title = recovered.custom_title
        self._recovery_path = path
        self._preview_widget.set_model(None, None)
        self._thumbnail_grid.load_model(self._edit_model, self.get_loader)
        self._sync_dirty_from_model()
        self.pdf_loaded.emit()

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
    def is_editor_job_running(self) -> bool:
        return bool(self.property("editorJobRunning"))

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
    def display_name(self) -> str:
        """The single human-facing name for this document, without dirty state."""
        if self._edit_model is None:
            return self._custom_tab_title or "New tab"
        if self._edit_model.save_path is not None:
            return Path(self._edit_model.save_path).name
        if self._custom_tab_title is not None:
            return self._custom_tab_title
        return Path(self._edit_model.original_path).name

    @property
    def display_path(self) -> str | None:
        """Path represented by :attr:`display_name`, when the tab has one."""
        if self._edit_model is None:
            return None
        return self._edit_model.save_path or self._edit_model.original_path

    @property
    def identity_tooltip(self) -> str:
        """Full current and original identities, without duplicating chrome."""
        if self._edit_model is None:
            return self.display_name
        current = self.display_path or self.display_name
        original = self._edit_model.original_path
        detail = current if current == original else f"{current}\nOriginal: {original}"
        return f"{self.display_name}\n{detail}"

    @property
    def tab_title(self) -> str:
        return f"{self.display_name}*" if self._dirty else self.display_name

    def suggested_save_stem(self) -> str:
        if self._edit_model is None:
            return "untitled"
        if self._custom_tab_title is not None:
            return sanitize_tab_title_stem(self._custom_tab_title)
        if self._drop_initialized:
            return "untitled"
        stem = Path(self.display_name).stem
        return stem if self._edit_model.save_path is not None or self._custom_tab_title else f"{stem}_edited"

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
        self._sync_recovery()
        self.tab_title_changed.emit()
        return True

    def clear_custom_tab_title(self) -> None:
        if self._custom_tab_title is None:
            return
        self._custom_tab_title = None
        self._sync_recovery()
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

    def is_viewer_mode(self) -> bool:
        """True when the full PDF viewer is showing (grid is hidden)."""
        return self._content_stack.currentWidget() is self._preview_widget

    def is_preview_visible(self) -> bool:
        """Alias for shortcut guards — Preview entry opens viewer mode."""
        return self.is_viewer_mode()

    def show_preview_at(self, page_index: int) -> None:
        """Toggle into viewer at *page_index* (logical); honors model rotations."""
        if self._edit_model is None:
            return
        # Re-bind so rotate/reorder while in grid refreshes sizes + cache keys.
        self._preview_widget.set_model(
            self._edit_model,
            self.get_loader,
            markup=self._markup,
            credentials=self._credentials,
        )
        self._preview_widget.reset_zoom_to_fit()
        self._preview_widget.show_page(page_index)
        self._content_stack.setCurrentWidget(self._preview_widget)

    def close_preview(self) -> None:
        if not self.is_viewer_mode():
            return
        self._content_stack.setCurrentWidget(self._thumbnail_grid)
        self._thumbnail_grid.refresh_markup_thumbnails()
        self._preview_widget.clear_caches()

    def _pending_annotations_for_page(self, logical: int):
        if (
            self._edit_model is None
            or not 0 <= logical < self._edit_model.logical_count()
        ):
            return ()
        instance_id = self._edit_model.instance_id_at(logical)
        return tuple(
            entry.annotation
            for entry in self._markup.entries_for_instance(instance_id)
            if entry.annotation is not None
        )

    def set_temp_manager(self, temp_manager: TempManager) -> None:
        """Move this tab's temp files to another window's manager (tab move)."""
        self._temp_manager = temp_manager
        self._thumbnail_grid.set_temp_manager(temp_manager)

    def get_loader(self, path: str) -> PdfLoader:
        """Return a cached loader for *path* (UI / main thread only)."""
        cached = self._loader_cache.get(path)
        if cached is not None:
            return cached
        loader = self._loader_cache[path] = PdfLoader(
            path, password=self._credentials.get(path)
        )
        self._evict_idle_loaders(keep={path})
        return loader

    def load_pdf(
        self, path: str, password: str | None = None
    ) -> PdfLoader:
        """Open *path* in this tab. Raises PdfLoadError subclasses on failure."""
        # Open first: a cancelled password or a load error keeps the current document.
        loader = PdfLoader(path, password=password)
        try:
            self.close_preview()
            self._thumbnail_grid.cancel_rendering()
            if self._edit_model is not None:
                self._thumbnail_grid.clear()
                self._close_loader_cache()
            self._edit_model = None
            self._outline_paths = None
            self._panel_path = _UNSET
            self._pdf_path = None
            self._custom_tab_title = None
            self._quality_guidance_shown = False

            if password is not None:
                self._credentials.set(path, password)
            self._loader_cache[path] = loader
        except BaseException:
            loader.close()
            raise
        self._edit_model = PdfEditModel(path, loader.page_count)
        self._markup.bind_model(self._edit_model)
        self._markup.clear()
        self._pdf_path = path
        self._drop_initialized = False
        self._sync_dirty_from_model()

        # Viewer binds on show_preview_at — avoid background renders while on grid.
        self._preview_widget.set_model(None, None)
        self._thumbnail_grid.load_model(self._edit_model, self.get_loader)
        self.pdf_loaded.emit()
        return loader

    def delete_selected_pages(self) -> bool:
        """Delete the current thumbnail selection; no-op when nothing is selected."""
        if self._edit_model is None or self.is_editor_job_running:
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
        """Undo markup (in viewer) or the last page-list edit."""
        if self.is_viewer_mode() and self._markup.can_undo():
            if not self._markup.undo():
                return False
            self._preview_widget.refresh_markup_overlays()
            self._sync_dirty_from_model()
            return True
        if self._edit_model is None or not self._edit_model.can_undo():
            return False
        self.close_preview()
        if not self._edit_model.undo():
            return False
        self._thumbnail_grid.reload_from_model()
        self._sync_dirty_from_model()
        return True

    def redo_edit(self) -> bool:
        """Redo markup (in viewer) or the last undone page-list edit."""
        if self.is_viewer_mode() and self._markup.can_redo():
            if not self._markup.redo():
                return False
            self._preview_widget.refresh_markup_overlays()
            self._sync_dirty_from_model()
            return True
        if self._edit_model is None or not self._edit_model.can_redo():
            return False
        self.close_preview()
        if not self._edit_model.redo():
            return False
        self._thumbnail_grid.reload_from_model()
        self._sync_dirty_from_model()
        return True

    def can_undo_edit(self) -> bool:
        if self.is_viewer_mode() and self._markup.can_undo():
            return True
        return self._edit_model is not None and self._edit_model.can_undo()

    def can_redo_edit(self) -> bool:
        if self.is_viewer_mode() and self._markup.can_redo():
            return True
        return self._edit_model is not None and self._edit_model.can_redo()

    def _on_markup_changed(self) -> None:
        self._sync_dirty_from_model()
        # MainWindow listens via dirty_changed for title; undo enable needs a nudge.
        self.dirty_changed.emit(self._dirty)

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

    def move_selected_pages_to(self, dest: int) -> bool:
        """Move selection so the block starts at *dest* (0-based); no-op if unchanged."""
        if self._edit_model is None or self.is_preview_visible() or self.is_editor_job_running:
            return False
        if not self._thumbnail_grid.can_move_selection_to():
            return False
        self.close_preview()
        if not self._thumbnail_grid.move_selection_to(dest):
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
        if self._edit_model is None or self.is_preview_visible() or self.is_editor_job_running:
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

    def init_from_page_refs(
        self,
        refs: list[PageRef],
        *,
        credentials: RuntimeCredentials | None = None,
    ) -> None:
        """Initialize a blank tab from a cross-window page transfer."""
        if not refs or self._edit_model is not None:
            return

        if credentials is not None:
            self._credentials.adopt(
                credentials, {ref.source_path for ref in refs}
            )

        for ref in refs:
            self.get_loader(ref.source_path)

        primary = refs[0].source_path
        self._edit_model = PdfEditModel.with_pages(primary, refs)
        self._markup.bind_model(self._edit_model)
        self._markup.clear()
        self._pdf_path = primary
        self._drop_initialized = True
        self._quality_guidance_shown = False
        self._sync_dirty_from_model()

        self._preview_widget.set_model(None, None)
        self._thumbnail_grid.load_model(self._edit_model, self.get_loader)
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
        self._markup.clear()
        if self._dirty:
            self._dirty = False
            self.dirty_changed.emit(False)
        self._preview_widget.set_model(None, None)
        self._refresh_workspace_panes()
        self._clear_recovery()
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
                "Large document at high zoom. Try a smaller thumbnail size "
                "for smoother scrolling"
            )
        return (
            "Large document at high zoom. Try a smaller thumbnail size, "
            "or View → Thumbnail quality"
        )

    def _close_loader_cache(self) -> None:
        paths = list(self._loader_cache)
        for loader in self._loader_cache.values():
            loader.close()
        self._loader_cache.clear()
        self._credentials.clear()
        for path in paths:
            invalidate_doc_cache(path)

    def _evict_idle_loaders(self, *, keep: set[str] | None = None) -> None:
        """Close unreferenced source loaders beyond LOADER_CACHE_IDLE_MAX."""
        if not self._loader_cache:
            return
        live = (
            self._edit_model.current_reference_paths()
            if self._edit_model is not None
            else set()
        )
        if keep:
            live |= keep
        idle = [path for path in self._loader_cache if path not in live]
        # dict order ≈ insertion; good enough when IDLE_MAX > 0
        for path in idle[LOADER_CACHE_IDLE_MAX:]:
            loader = self._loader_cache.pop(path, None)
            if loader is not None:
                loader.close()
            invalidate_doc_cache(path)

    def _sync_dirty_from_model(self) -> None:
        model_dirty = self._edit_model.is_dirty() if self._edit_model is not None else False
        dirty = model_dirty or self._markup.is_dirty(self._edit_model)
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)
        self._sync_recovery()
        self._evict_idle_loaders()
        self._refresh_workspace_panes()

    def _sync_recovery(self) -> None:
        if self._recovery_path is None:
            return
        if not self._dirty or self._edit_model is None:
            self._clear_recovery()
            return
        try:
            write_draft(
                self._recovery_path,
                self._edit_model,
                self._markup.ops(self._edit_model),
                custom_title=self._custom_tab_title,
                drop_initialized=self._drop_initialized,
            )
            self._recovery_error_reported = False
        except RecoveryError as exc:
            if not self._recovery_error_reported:
                self._recovery_error_reported = True
                self.recovery_failed.emit(str(exc))

    def _clear_recovery(self) -> None:
        if self._recovery_path is None:
            return
        try:
            self._recovery_path.unlink(missing_ok=True)
            self._recovery_path.with_suffix(".tmp").unlink(missing_ok=True)
        except OSError as exc:
            if not self._recovery_error_reported:
                self._recovery_error_reported = True
                self.recovery_failed.emit(f"Could not remove the recovery draft: {exc}")
