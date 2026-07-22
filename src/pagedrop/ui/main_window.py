from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent, QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolBar,
    QToolButton,
    QWidget,
)

from pagedrop.core.pdf_loader import (
    PdfEmptyError,
    PdfLoadError,
    PdfPasswordError,
    PdfPasswordRequiredError,
)
from pagedrop.core.pdf_writer import write_pdf
from pagedrop.ui.busy_overlay import ToastOverlay
from pagedrop.ui.command_palette import CommandPalette, collect_actions
from pagedrop.ui.convert_window import ConvertWindow
from pagedrop.ui.dialogs import fit_message_box_buttons
from pagedrop.ui.keyboard_nav import (
    enable_toolbar_keyboard_navigation,
    set_content_tab_order,
)
from pagedrop.ui.merge_window import MergeWindow
from pagedrop.ui.onboarding import KeyboardShortcutsDialog, TipsOverlay
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.accessibility import refresh_themed_widgets
from pagedrop.ui.settings import (
    confirm_before_closing_dirty_tabs,
    confirm_before_deleting_multiple_pages,
    has_seen_tips,
    last_directory,
    light_theme,
    load_window_geometry,
    recent_files,
    remember_directory,
    remember_recent_file,
    remember_window_geometry,
    save_window_geometry,
    set_confirm_before_closing_dirty_tabs,
    set_confirm_before_deleting_multiple_pages,
    set_light_theme,
    set_remember_window_geometry,
    set_thumbnail_quality,
    set_thumbnail_zoom,
    thumbnail_quality,
    thumbnail_zoom,
)
from pagedrop.ui.tab_manager import TabManager
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_THUMBNAIL_WIDTH,
    MIN_THUMBNAIL_WIDTH,
    ZOOM_WHEEL_STEP,
)
from pagedrop.ui.zoom_controls import ZoomControls
from pagedrop.utils.page_jump import parse_page_jump
from pagedrop.utils.temp_manager import TempManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from pagedrop.ui.window_manager import WindowManager


MOVE_UNDO_TIMEOUT_MS = 8000
STATUS_TRANSIENT_MS = 5000


class MainWindow(QMainWindow):
    APP_TITLE = "PageDrop"

    def __init__(
        self,
        *,
        window_manager: WindowManager | None = None,
        initial_tab: PdfTab | None = None,
    ) -> None:
        super().__init__()
        self._window_manager = window_manager
        self._initial_tab = initial_tab
        self._temp_manager = TempManager()
        self._merge_window: MergeWindow | None = None
        self._convert_window: ConvertWindow | None = None
        self._previous_tab_index: int | None = None
        self._last_tab_index: int = 0
        self._pending_move_undo: Callable[[], bool] | None = None

        self.setWindowTitle(self.APP_TITLE)
        self.setMinimumSize(720, 480)
        self.resize(960, 680)

        self._build_menu()
        self._build_toolbar()
        self._build_status_widgets()
        self._build_selection_shortcuts()
        self._build_tab_shortcuts()
        self._build_navigation_shortcuts()
        self._build_central_widget()
        QApplication.instance().installEventFilter(self)
        self._persistent_status("Ready")
        self._sync_toolbar_from_active_tab()
        self._tips_overlay = TipsOverlay(self)
        QTimer.singleShot(0, self._maybe_show_first_run_tips)

    @property
    def current_pdf_path(self) -> str | None:
        tab = self._tab_manager.active_tab
        return tab.pdf_path if tab is not None else None

    @property
    def _loader(self):
        tab = self._tab_manager.active_tab
        return tab.loader if tab is not None else None

    @property
    def _thumbnail_grid(self):
        tab = self._tab_manager.active_tab
        return tab.thumbnail_grid if tab is not None else None

    @property
    def _preview_widget(self):
        tab = self._tab_manager.active_tab
        return tab.preview_widget if tab is not None else None

    @property
    def _central_stack(self):
        tab = self._tab_manager.active_tab
        return tab.content_stack if tab is not None else None

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")

        open_action = file_menu.addAction("&Open PDF")
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_pdf)

        self._open_recent_menu = file_menu.addMenu("Open &Recent")
        self._open_recent_menu.aboutToShow.connect(self._populate_open_recent_menu)

        self._close_action = file_menu.addAction("&Close Tab")
        self._close_action.triggered.connect(self._close_tab)
        self._close_action.setEnabled(False)

        self._save_as_action = file_menu.addAction("Save &As")
        self._save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._save_as_action.triggered.connect(self._save_as)
        self._save_as_action.setEnabled(False)

        self._export_all_action = file_menu.addAction("Export All &Pages…")
        self._export_all_action.triggered.connect(self._export_all_pages)
        self._export_all_action.setEnabled(False)

        file_menu.addSeparator()

        self._new_window_action = file_menu.addAction("New &Window")
        self._new_window_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self._new_window_action.triggered.connect(self._new_window)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        edit_menu = menubar.addMenu("&Edit")

        self._undo_action = edit_menu.addAction("&Undo")
        self._undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self._undo_action.triggered.connect(self._undo)
        self._undo_action.setEnabled(False)

        self._redo_action = edit_menu.addAction("&Redo")
        self._redo_action.setShortcuts(
            [
                QKeySequence("Ctrl+Shift+Z"),
                QKeySequence.StandardKey.Redo,
            ]
        )
        self._redo_action.triggered.connect(self._redo)
        self._redo_action.setEnabled(False)

        edit_menu.addSeparator()

        self._confirm_delete_action = edit_menu.addAction(
            "Confirm before &deleting multiple pages"
        )
        self._confirm_delete_action.setCheckable(True)
        self._confirm_delete_action.setChecked(
            confirm_before_deleting_multiple_pages()
        )
        self._confirm_delete_action.toggled.connect(
            set_confirm_before_deleting_multiple_pages
        )

        self._confirm_close_dirty_action = edit_menu.addAction(
            "Confirm before closing dirty &tabs"
        )
        self._confirm_close_dirty_action.setCheckable(True)
        self._confirm_close_dirty_action.setChecked(
            confirm_before_closing_dirty_tabs()
        )
        self._confirm_close_dirty_action.toggled.connect(
            set_confirm_before_closing_dirty_tabs
        )

        self._remember_geometry_action = edit_menu.addAction(
            "Remember window &size and position"
        )
        self._remember_geometry_action.setCheckable(True)
        self._remember_geometry_action.setChecked(remember_window_geometry())
        self._remember_geometry_action.toggled.connect(
            set_remember_window_geometry
        )

        view_menu = menubar.addMenu("&View")

        self._light_theme_action = view_menu.addAction("Toggle &Light Theme")
        self._light_theme_action.setCheckable(True)
        self._light_theme_action.setChecked(light_theme())
        self._light_theme_action.toggled.connect(self._on_light_theme_toggled)

        quality_menu = view_menu.addMenu("Thumbnail &quality")
        self._quality_action_group = QActionGroup(self)
        self._quality_action_group.setExclusive(True)
        current_quality = thumbnail_quality()
        for value, label in (
            ("low", "&Low"),
            ("medium", "&Medium"),
            ("high", "&High"),
        ):
            action = quality_menu.addAction(label)
            action.setCheckable(True)
            action.setData(value)
            action.setChecked(value == current_quality)
            self._quality_action_group.addAction(action)
        self._quality_action_group.triggered.connect(
            self._on_thumbnail_quality_triggered
        )

        view_menu.addSeparator()

        self._command_palette_action = view_menu.addAction("Command &palette…")
        self._command_palette_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self._command_palette_action.triggered.connect(self._open_command_palette)

        merge_action = menubar.addAction("&Merge PDFs")
        merge_action.triggered.connect(self._open_merge_window)

        create_pdf_action = menubar.addAction("&Create PDF")
        create_pdf_action.triggered.connect(self._open_convert_window)

        help_menu = menubar.addMenu("&Help")
        shortcuts_action = help_menu.addAction("&Keyboard Shortcuts")
        shortcuts_action.setShortcut(QKeySequence("Ctrl+/"))
        shortcuts_action.triggered.connect(self._show_keyboard_shortcuts)
        tips_action = help_menu.addAction("Show &Tips")
        tips_action.triggered.connect(self._show_tips_overlay)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self._toolbar = toolbar

        open_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Open",
        )
        open_action.triggered.connect(self._open_pdf)
        self._set_action_hint(open_action, "Open a PDF (Ctrl+O)")
        open_button = toolbar.widgetForAction(open_action)
        if open_button is not None:
            open_button.setObjectName("ToolbarPrimary")

        self._preview_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Preview",
        )
        self._set_action_hint(
            self._preview_action,
            "Preview selected page (Enter or double-click a card)",
        )
        self._preview_action.triggered.connect(self._open_preview)
        self._preview_action.setEnabled(False)

        toolbar.addSeparator()

        self._select_all_action = toolbar.addAction("Select All")
        self._set_action_hint(self._select_all_action, "Select all pages (Ctrl+A)")
        self._select_all_action.triggered.connect(self._select_all_pages)
        self._select_all_action.setEnabled(False)

        self._deselect_all_action = toolbar.addAction("Deselect All")
        self._set_action_hint(self._deselect_all_action, "Clear selection (Esc)")
        self._deselect_all_action.triggered.connect(self._clear_selection)
        self._deselect_all_action.setEnabled(False)

        self._move_up_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp),
            "Move up",
        )
        self._set_action_hint(
            self._move_up_action, "Move selected pages up (Ctrl+↑)"
        )
        self._move_up_action.triggered.connect(self._move_selected_pages_up)
        self._move_up_action.setEnabled(False)

        self._move_down_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown),
            "Move down",
        )
        self._set_action_hint(
            self._move_down_action, "Move selected pages down (Ctrl+↓)"
        )
        self._move_down_action.triggered.connect(self._move_selected_pages_down)
        self._move_down_action.setEnabled(False)

        self._delete_pages_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon),
            "Delete page(s)",
        )
        self._set_action_hint(
            self._delete_pages_action, "Delete selected pages (Delete)"
        )
        self._delete_pages_action.triggered.connect(self._delete_selected_pages)
        self._delete_pages_action.setEnabled(False)

        self._duplicate_pages_action = toolbar.addAction("Duplicate")
        self._set_action_hint(
            self._duplicate_pages_action, "Duplicate selected pages (Ctrl+D)"
        )
        self._duplicate_pages_action.triggered.connect(self._duplicate_selected_pages)
        self._duplicate_pages_action.setEnabled(False)

        self._rotate_cw_action = toolbar.addAction("Rotate CW")
        self._set_action_hint(
            self._rotate_cw_action, "Rotate selected pages clockwise"
        )
        self._rotate_cw_action.triggered.connect(
            lambda: self._rotate_selected_pages(90)
        )
        self._rotate_cw_action.setEnabled(False)

        self._rotate_ccw_action = toolbar.addAction("Rotate CCW")
        self._set_action_hint(
            self._rotate_ccw_action, "Rotate selected pages counter-clockwise"
        )
        self._rotate_ccw_action.triggered.connect(
            lambda: self._rotate_selected_pages(-90)
        )
        self._rotate_ccw_action.setEnabled(False)

        toolbar.addSeparator()

        self._filename_label = QLabel("No file open")
        self._filename_label.setObjectName("ToolbarFilename")
        self._filename_label.setProperty("active", False)
        self._filename_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        toolbar.addWidget(self._filename_label)

        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        toolbar.addWidget(spacer)

        self._zoom_controls = ZoomControls(
            min_width=MIN_THUMBNAIL_WIDTH,
            max_width=MAX_THUMBNAIL_WIDTH,
            step=ZOOM_WHEEL_STEP,
            initial=thumbnail_zoom(),
        )
        toolbar.addWidget(self._zoom_controls)
        self._zoom_controls.zoom_requested.connect(self._on_zoom_requested)
        self._zoom_controls.reset_requested.connect(self._reset_thumbnail_zoom)
        zoom_hint = "Thumbnail size (Ctrl+scroll · Ctrl+0 reset)"
        self._zoom_controls.setToolTip(zoom_hint)
        self._zoom_controls.setStatusTip(zoom_hint)

        enable_toolbar_keyboard_navigation(toolbar)

    def _build_central_widget(self) -> None:
        self._tab_manager = TabManager(temp_manager=self._temp_manager)
        self._tab_manager.active_tab_changed.connect(self._on_active_tab_changed)
        self._tab_manager.currentChanged.connect(self._on_tab_index_changed)
        self._tab_manager.tab_added.connect(self._connect_tab_signals)
        self._tab_manager.tab_closed.connect(self._on_tab_closed)
        self._tab_manager.tabCloseRequested.disconnect(self._tab_manager.close_tab)
        self._tab_manager.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tab_manager.tab_detach_requested.connect(self._detach_tab_to_new_window)
        self._tab_manager.move_to_new_window_requested.connect(
            self._detach_tab_to_new_window
        )
        self._tab_manager.tab_rename_requested.connect(self._rename_tab)

        new_tab_button = QToolButton()
        new_tab_button.setObjectName("NewTabButton")
        new_tab_button.setText("+")
        new_tab_button.setToolTip("New tab (Ctrl+T)")
        new_tab_button.setAccessibleName("New tab")
        new_tab_button.clicked.connect(self._new_blank_tab)
        self._tab_manager.setCornerWidget(
            new_tab_button,
            Qt.Corner.TopRightCorner,
        )

        if self._initial_tab is not None:
            self._adopt_tab(self._initial_tab)
        else:
            self._tab_manager.add_blank_tab()
            tab = self._tab_manager.active_tab
            if tab is not None:
                tab.set_zoom_level(thumbnail_zoom())
        self.setCentralWidget(self._tab_manager)
        self._toast = ToastOverlay(self._tab_manager)
        self._last_tab_index = self._tab_manager.currentIndex()
        set_content_tab_order(
            self._toolbar,
            self._tab_manager,
            status_bar=self.statusBar(),
        )

    def _transient_status(self, message: str) -> None:
        self.statusBar().showMessage(message, STATUS_TRANSIENT_MS)

    def _persistent_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _show_toast(self, message: str) -> None:
        self._toast.show_toast(message)

    def _restore_document_status(self) -> None:
        """Restore sticky document status after a drag hint."""
        tab = self._active_tab()
        if tab is None:
            self._persistent_status("Ready")
            return
        if tab.is_preview_visible() and tab.edit_model is not None:
            self._update_preview_status()
            return
        if tab.edit_model is not None:
            count = tab.edit_model.logical_count()
            noun = "page" if count == 1 else "pages"
            self._persistent_status(f"Loaded {count} {noun}")
            return
        self._persistent_status("Ready")

    def _update_selection_status(self, selection: set[int]) -> None:
        tab = self._active_tab()
        if tab is None or tab.loader is None:
            self._selection_status.clear()
            self._selection_status.hide()
            return
        if selection:
            count = len(selection)
            noun = "page" if count == 1 else "pages"
            self._selection_status.setText(f"{count} {noun} selected")
            self._selection_status.show()
        else:
            self._selection_status.setText("No selection")
            self._selection_status.show()

    def _build_status_widgets(self) -> None:
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._progress_bar.setAccessibleName("Page rendering progress")
        self._progress_bar.hide()

        self._selection_status = QLabel()
        self._selection_status.setObjectName("SelectionStatusLabel")
        self._selection_status.setAccessibleName("Selection count")
        self._selection_status.hide()

        self._move_undo_widget = QWidget()
        self._move_undo_widget.setObjectName("MoveUndoToast")
        move_undo_layout = QHBoxLayout(self._move_undo_widget)
        move_undo_layout.setContentsMargins(0, 0, 8, 0)
        move_undo_layout.setSpacing(6)
        self._move_undo_label = QLabel()
        self._move_undo_button = QPushButton("Undo")
        self._move_undo_button.setObjectName("MoveUndoButton")
        self._move_undo_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._move_undo_button.setAccessibleName("Undo page move")
        self._move_undo_button.clicked.connect(self._on_transient_move_undo)
        move_undo_layout.addWidget(self._move_undo_label)
        move_undo_layout.addWidget(self._move_undo_button)
        self._move_undo_widget.hide()
        self._move_undo_timer = QTimer(self)
        self._move_undo_timer.setSingleShot(True)
        self._move_undo_timer.timeout.connect(self._dismiss_move_undo)

        self.statusBar().addPermanentWidget(self._selection_status)
        self.statusBar().addPermanentWidget(self._move_undo_widget)
        self.statusBar().addPermanentWidget(self._progress_bar)
        self.statusBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _build_selection_shortcuts(self) -> None:
        # WindowShortcut, not ApplicationShortcut: with multiple windows open,
        # app-wide contexts collide ("Ambiguous shortcut overload") and Qt
        # fires neither action. Handlers act on this window's tab anyway.
        select_all = QAction(self)
        select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        select_all.triggered.connect(self._select_all_pages)
        self.addAction(select_all)

        self._clear_selection_action = QAction(self)
        self._clear_selection_action.setShortcut(QKeySequence.StandardKey.Cancel)
        self._clear_selection_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self._clear_selection_action.triggered.connect(self._on_escape)
        self.addAction(self._clear_selection_action)

        delete_pages = QAction(self)
        delete_pages.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        delete_pages.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        delete_pages.triggered.connect(self._delete_selected_pages)
        self.addAction(delete_pages)

        move_up = QAction(self)
        move_up.setShortcut(QKeySequence("Ctrl+Up"))
        move_up.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        move_up.triggered.connect(self._move_selected_pages_up)
        self.addAction(move_up)

        move_down = QAction(self)
        move_down.setShortcut(QKeySequence("Ctrl+Down"))
        move_down.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        move_down.triggered.connect(self._move_selected_pages_down)
        self.addAction(move_down)

        duplicate_pages = QAction(self)
        duplicate_pages.setShortcut(QKeySequence("Ctrl+D"))
        duplicate_pages.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        duplicate_pages.triggered.connect(self._duplicate_selected_pages)
        self.addAction(duplicate_pages)

    def _build_tab_shortcuts(self) -> None:
        next_tab = QAction(self)
        next_tab.setShortcut(QKeySequence("Ctrl+Tab"))
        next_tab.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        next_tab.triggered.connect(self._switch_to_next_tab)
        self.addAction(next_tab)

        prev_tab = QAction(self)
        prev_tab.setShortcut(QKeySequence("Ctrl+Shift+Tab"))
        prev_tab.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        prev_tab.triggered.connect(self._switch_to_previous_tab)
        self.addAction(prev_tab)

        close_tab = QAction(self)
        close_tab.setShortcut(QKeySequence("Ctrl+W"))
        close_tab.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        close_tab.triggered.connect(self._close_tab)
        self.addAction(close_tab)

        new_tab = QAction(self)
        new_tab.setShortcut(QKeySequence("Ctrl+T"))
        new_tab.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        new_tab.triggered.connect(self._new_blank_tab)
        self.addAction(new_tab)

    def _build_navigation_shortcuts(self) -> None:
        go_to_page = QAction(self)
        go_to_page.setShortcut(QKeySequence("Ctrl+G"))
        go_to_page.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        go_to_page.triggered.connect(self._go_to_page_dialog)
        self.addAction(go_to_page)

        page_jump = QAction(self)
        page_jump.setShortcut(QKeySequence("Ctrl+F"))
        page_jump.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        page_jump.triggered.connect(self._page_range_jump_dialog)
        self.addAction(page_jump)

        reset_zoom = QAction(self)
        reset_zoom.setShortcut(QKeySequence("Ctrl+0"))
        reset_zoom.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        reset_zoom.triggered.connect(self._reset_zoom)
        self.addAction(reset_zoom)

    def _connect_tab_signals(self, tab: PdfTab) -> None:
        grid = tab.thumbnail_grid
        grid.rendering_started.connect(self._on_rendering_started)
        grid.rendering_progress.connect(self._on_rendering_progress)
        grid.rendering_finished.connect(self._on_rendering_finished)
        grid.rendering_error.connect(self._on_rendering_error)
        grid.busy_changed.connect(self._on_grid_busy_changed)
        grid.selection_changed.connect(self._on_selection_changed)
        grid.preview_requested.connect(self._open_preview_at)
        grid.zoom_changed.connect(self._on_zoom_changed)
        grid.pages_inserted.connect(self._on_pages_inserted)
        grid.cross_window_pages_inserted.connect(self._on_cross_window_pages_inserted)
        grid.pages_moved_out.connect(self._on_pages_moved_out)
        grid.pages_transferred_via_tab_bar.connect(
            self._on_pages_transferred_via_tab_bar
        )
        grid.pages_reordered.connect(self._on_pages_reordered)
        grid.page_transfer_failed.connect(self._on_page_transfer_failed)
        grid.pdf_drop_failed.connect(self._on_pdf_drop_failed)
        grid.extract_to_folder_requested.connect(self._extract_selected_to_folder)
        grid.extract_to_new_tab_requested.connect(self._extract_selected_to_new_tab)
        grid.extract_to_new_window_requested.connect(
            self._extract_selected_to_new_window
        )
        grid.open_pdfs_requested.connect(self._on_open_pdfs_requested)
        tab.pdf_loaded.connect(self._on_tab_pdf_loaded)
        tab.preview_widget.page_changed.connect(self._on_preview_page_changed)
        tab.preview_widget.busy_changed.connect(self._on_preview_busy_changed)
        tab.preview_widget.render_error.connect(self._on_preview_render_error)
        tab.dirty_changed.connect(self._on_tab_dirty_changed)

    def _disconnect_tab_signals(self, tab: PdfTab) -> None:
        grid = tab.thumbnail_grid
        preview = tab.preview_widget
        for signal, slot in (
            (grid.rendering_started, self._on_rendering_started),
            (grid.rendering_progress, self._on_rendering_progress),
            (grid.rendering_finished, self._on_rendering_finished),
            (grid.rendering_error, self._on_rendering_error),
            (grid.busy_changed, self._on_grid_busy_changed),
            (grid.selection_changed, self._on_selection_changed),
            (grid.preview_requested, self._open_preview_at),
            (grid.zoom_changed, self._on_zoom_changed),
            (grid.pages_inserted, self._on_pages_inserted),
            (grid.cross_window_pages_inserted, self._on_cross_window_pages_inserted),
            (grid.pages_moved_out, self._on_pages_moved_out),
            (
                grid.pages_transferred_via_tab_bar,
                self._on_pages_transferred_via_tab_bar,
            ),
            (grid.pages_reordered, self._on_pages_reordered),
            (grid.page_transfer_failed, self._on_page_transfer_failed),
            (grid.pdf_drop_failed, self._on_pdf_drop_failed),
            (grid.extract_to_folder_requested, self._extract_selected_to_folder),
            (grid.extract_to_new_tab_requested, self._extract_selected_to_new_tab),
            (
                grid.extract_to_new_window_requested,
                self._extract_selected_to_new_window,
            ),
            (grid.open_pdfs_requested, self._on_open_pdfs_requested),
            (tab.pdf_loaded, self._on_tab_pdf_loaded),
            (preview.page_changed, self._on_preview_page_changed),
            (preview.busy_changed, self._on_preview_busy_changed),
            (preview.render_error, self._on_preview_render_error),
            (tab.dirty_changed, self._on_tab_dirty_changed),
        ):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass

    def _on_tab_dirty_changed(self, _dirty: bool = False) -> None:
        self._update_save_as_action()
        if self.sender() is self._active_tab():
            self._update_window_title()

    def _active_tab(self) -> PdfTab | None:
        return self._tab_manager.active_tab

    def _grid_belongs_to_active_tab(self, grid) -> bool:
        tab = self._active_tab()
        return tab is not None and grid is tab.thumbnail_grid

    def _grid_belongs_to_window(self, grid) -> bool:
        for index in range(self._tab_manager.count()):
            tab = self._tab_manager.widget(index)
            if isinstance(tab, PdfTab) and grid is tab.thumbnail_grid:
                return True
        return False

    def _new_blank_tab(self) -> None:
        tab = self._tab_manager.add_blank_tab()
        tab.set_zoom_level(thumbnail_zoom())
        self._tab_manager.setCurrentWidget(tab)
        self._update_close_tab_action()

    def _new_window(self) -> None:
        if self._window_manager is None:
            return
        self._window_manager.open_new_window()

    def _adopt_tab(self, tab: PdfTab) -> None:
        preserve_preview = tab.is_preview_visible()
        preview_page = tab.preview_widget.current_page if preserve_preview else None
        source_window = None
        source_manager = self._tab_manager_for_tab(tab)
        if source_manager is not None and source_manager is not self._tab_manager:
            source_window = self._window_for_widget(source_manager)
            index = source_manager.indexOf(tab)
            if index >= 0:
                source_manager.tab_closed.emit(index)
                source_manager.removeTab(index)
                if source_manager.count() == 0:
                    source_manager.all_tabs_closed.emit()
                    source_manager.add_blank_tab()
        self._tab_manager.add_tab(tab)
        self._tab_manager.setCurrentWidget(tab)
        if preserve_preview and preview_page is not None:
            tab.show_preview_at(preview_page)
        self._update_close_tab_action()
        if source_window is not None and source_window is not self:
            source_window._sync_toolbar_from_active_tab()

    def _tab_manager_for_tab(self, tab: PdfTab) -> TabManager | None:
        current: QWidget | None = tab
        while current is not None:
            if isinstance(current, TabManager):
                return current
            current = current.parentWidget()
        return None

    def _window_for_widget(self, widget: QWidget) -> MainWindow | None:
        if self._window_manager is not None:
            window = self._window_manager.window_for_widget(widget)
            if window is not None:
                return window
        current: QWidget | None = widget
        while current is not None:
            if isinstance(current, MainWindow):
                return current
            current = current.parentWidget()
        return None

    def _detach_tab_to_new_window(self, index: int) -> None:
        tab = self._tab_manager.widget(index)
        if not isinstance(tab, PdfTab):
            return

        self._disconnect_tab_signals(tab)

        if self._window_manager is not None:
            new_window = self._window_manager.open_new_window(tab)
        else:
            new_window = MainWindow(initial_tab=tab)
            new_window.show()

        new_window.raise_()
        new_window.activateWindow()
        self._sync_toolbar_from_active_tab()

    def _on_tab_index_changed(self, index: int) -> None:
        if index < 0:
            return
        count = self._tab_manager.count()
        if count <= 1:
            self._previous_tab_index = None
            self._last_tab_index = index
            return
        if self._last_tab_index < 0:
            self._last_tab_index = index
            return
        if self._last_tab_index != index:
            self._previous_tab_index = self._last_tab_index
        self._last_tab_index = index

    @staticmethod
    def _remap_tab_index_after_close(
        closed_index: int,
        tab_index: int | None,
    ) -> int | None:
        if tab_index is None:
            return None
        if tab_index == closed_index:
            return None
        if tab_index > closed_index:
            return tab_index - 1
        return tab_index

    def _on_tab_closed(self, closed_index: int) -> None:
        self._previous_tab_index = self._remap_tab_index_after_close(
            closed_index,
            self._previous_tab_index,
        )
        if self._last_tab_index == closed_index:
            self._last_tab_index = -1
        else:
            remapped = self._remap_tab_index_after_close(
                closed_index,
                self._last_tab_index,
            )
            if remapped is not None:
                self._last_tab_index = remapped
        self._update_close_tab_action()

    def _switch_to_next_tab(self) -> None:
        count = self._tab_manager.count()
        if count <= 1:
            return
        current = self._tab_manager.currentIndex()
        previous = self._previous_tab_index
        if (
            previous is None
            or previous == current
            or previous < 0
            or previous >= count
        ):
            return
        self._tab_manager.setCurrentIndex(previous)

    def _switch_to_previous_tab(self) -> None:
        count = self._tab_manager.count()
        if count <= 1:
            return
        self._tab_manager.setCurrentIndex(
            (self._tab_manager.currentIndex() - 1) % count
        )

    def _is_only_blank_tab(self) -> bool:
        return (
            self._tab_manager.count() == 1
            and self._active_tab() is not None
            and self._active_tab().is_blank
        )

    def _update_close_tab_action(self) -> None:
        self._close_action.setEnabled(not self._is_only_blank_tab())

    def _on_active_tab_changed(self, tab: PdfTab) -> None:
        if tab.is_preview_visible():
            tab.close_preview()
        self._sync_toolbar_from_active_tab()

    def _sync_toolbar_from_active_tab(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.is_blank:
            self._reset_toolbar_for_blank_tab()
            return

        filename = Path(tab.pdf_path).name if tab.pdf_path else "No file open"
        self._update_window_title()
        self._filename_label.setText(filename)
        self._filename_label.setProperty("active", True)
        self._filename_label.style().unpolish(self._filename_label)
        self._filename_label.style().polish(self._filename_label)
        self._preview_action.setEnabled(True)
        self._select_all_action.setEnabled(not tab.is_preview_visible())
        self._deselect_all_action.setEnabled(
            not tab.is_preview_visible()
            and bool(tab.thumbnail_grid.selection_manager.selection)
        )
        self._update_delete_pages_action()
        self._update_move_pages_actions()
        self._update_page_op_actions()
        self._update_undo_redo_actions()
        self._zoom_controls.setEnabled(not tab.is_preview_visible())
        self._zoom_controls.set_value(tab.zoom_level)
        self._update_preview_mode_ui()
        self._update_close_tab_action()
        self._update_save_as_action()
        self._update_selection_status(tab.thumbnail_grid.selection_manager.selection)

    def _reset_toolbar_for_blank_tab(self) -> None:
        tab = self._active_tab()
        self._update_window_title()
        self._filename_label.setText("No file open")
        self._filename_label.setProperty("active", False)
        self._filename_label.style().unpolish(self._filename_label)
        self._filename_label.style().polish(self._filename_label)
        self._preview_action.setEnabled(False)
        self._select_all_action.setEnabled(False)
        self._deselect_all_action.setEnabled(False)
        self._delete_pages_action.setEnabled(False)
        self._duplicate_pages_action.setEnabled(False)
        self._rotate_cw_action.setEnabled(False)
        self._rotate_ccw_action.setEnabled(False)
        self._move_up_action.setEnabled(False)
        self._move_down_action.setEnabled(False)
        self._undo_action.setEnabled(False)
        self._redo_action.setEnabled(False)
        self._zoom_controls.setEnabled(False)
        self._zoom_controls.set_value(
            tab.zoom_level if tab is not None else thumbnail_zoom()
        )
        self._progress_bar.hide()
        self._update_close_tab_action()
        self._update_save_as_action()
        self._update_selection_status(set())

    def _update_save_as_action(self) -> None:
        tab = self._active_tab()
        has_pages = (
            tab is not None
            and tab.edit_model is not None
            and tab.edit_model.logical_count() > 0
        )
        self._save_as_action.setEnabled(has_pages)
        self._export_all_action.setEnabled(has_pages)

    def _update_delete_pages_action(self) -> None:
        tab = self._active_tab()
        self._delete_pages_action.setEnabled(
            tab is not None
            and tab.edit_model is not None
            and not tab.is_preview_visible()
            and bool(tab.thumbnail_grid.selection_manager.selection)
        )

    def _update_page_op_actions(self) -> None:
        tab = self._active_tab()
        enabled = (
            tab is not None
            and tab.edit_model is not None
            and not tab.is_preview_visible()
            and bool(tab.thumbnail_grid.selection_manager.selection)
        )
        self._duplicate_pages_action.setEnabled(enabled)
        self._rotate_cw_action.setEnabled(enabled)
        self._rotate_ccw_action.setEnabled(enabled)

    def _update_move_pages_actions(self) -> None:
        tab = self._active_tab()
        grid = tab.thumbnail_grid if tab is not None else None
        enabled = (
            tab is not None
            and tab.edit_model is not None
            and not tab.is_preview_visible()
        )
        self._move_up_action.setEnabled(
            enabled and grid is not None and grid.can_move_selection_up()
        )
        self._move_down_action.setEnabled(
            enabled and grid is not None and grid.can_move_selection_down()
        )

    def _delete_selected_pages(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.is_preview_visible():
            return
        selection = tab.thumbnail_grid.selection_manager.selection
        if not selection:
            return
        count = len(selection)
        if not tab.delete_selected_pages():
            return
        self._tab_manager.update_tab_title(tab)
        self._update_window_title()
        self._update_delete_pages_action()
        self._update_move_pages_actions()
        self._update_undo_redo_actions()
        self._deselect_all_action.setEnabled(False)
        self._update_save_as_action()
        if tab.edit_model.logical_count() == 0:
            self._transient_status("All pages deleted")
        else:
            noun = "page" if count == 1 else "pages"
            self._transient_status(f"Deleted {count} {noun}")

    def _duplicate_selected_pages(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.is_preview_visible():
            return
        count = tab.duplicate_selected_pages()
        if not count:
            return
        self._tab_manager.update_tab_title(tab)
        self._update_window_title()
        self._update_delete_pages_action()
        self._update_move_pages_actions()
        self._update_page_op_actions()
        self._update_undo_redo_actions()
        self._update_save_as_action()
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Duplicated {count} {noun}")
        self._show_toast(f"Duplicated {count} {noun}")

    def _rotate_selected_pages(self, delta_degrees: int) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.is_preview_visible():
            return
        count = len(tab.thumbnail_grid.selection_manager.selection)
        if not count:
            return
        if not tab.rotate_selected_pages(delta_degrees):
            return
        self._tab_manager.update_tab_title(tab)
        self._update_undo_redo_actions()
        self._update_save_as_action()
        direction = "clockwise" if delta_degrees > 0 else "counter-clockwise"
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Rotated {count} {noun} {direction}")

    def _move_selected_pages_up(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.is_preview_visible():
            return
        if not tab.thumbnail_grid.can_move_selection_up():
            return
        if not tab.move_selected_pages_up():
            return
        self._tab_manager.update_tab_title(tab)
        self._update_move_pages_actions()
        self._update_undo_redo_actions()
        count = len(tab.thumbnail_grid.selection_manager.selection)
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Moved {count} {noun} up")

    def _move_selected_pages_down(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.is_preview_visible():
            return
        if not tab.thumbnail_grid.can_move_selection_down():
            return
        if not tab.move_selected_pages_down():
            return
        self._tab_manager.update_tab_title(tab)
        self._update_move_pages_actions()
        self._update_undo_redo_actions()
        count = len(tab.thumbnail_grid.selection_manager.selection)
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Moved {count} {noun} down")

    def _undo(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.is_preview_visible():
            return
        if not tab.undo_edit():
            return
        self._dismiss_move_undo()
        self._tab_manager.update_tab_title(tab)
        self._update_window_title()
        self._sync_toolbar_from_active_tab()
        self._transient_status("Undo")

    def _redo(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.is_preview_visible():
            return
        if not tab.redo_edit():
            return
        self._dismiss_move_undo()
        self._tab_manager.update_tab_title(tab)
        self._update_window_title()
        self._sync_toolbar_from_active_tab()
        self._transient_status("Redo")

    def _update_undo_redo_actions(self) -> None:
        tab = self._active_tab()
        model = tab.edit_model if tab is not None else None
        preview_blocking = tab is not None and tab.is_preview_visible()
        self._undo_action.setEnabled(
            model is not None and model.can_undo() and not preview_blocking
        )
        self._redo_action.setEnabled(
            model is not None and model.can_redo() and not preview_blocking
        )

    def _offer_move_undo(self, count: int, undo: Callable[[], bool]) -> None:
        self._pending_move_undo = undo
        noun = "page" if count == 1 else "pages"
        self._move_undo_label.setText(f"{count} {noun} moved ·")
        self._move_undo_widget.show()
        self.statusBar().clearMessage()
        self._move_undo_timer.start(MOVE_UNDO_TIMEOUT_MS)

    def _dismiss_move_undo(self) -> None:
        self._move_undo_timer.stop()
        self._pending_move_undo = None
        self._move_undo_widget.hide()

    def _on_transient_move_undo(self) -> None:
        undo = self._pending_move_undo
        self._dismiss_move_undo()
        if undo is None:
            return
        if not undo():
            self._transient_status("Move undo is no longer available")
            return
        self._sync_toolbar_from_active_tab()
        if self._window_manager is not None:
            for window in self._window_manager.windows:
                if window is not self:
                    window._sync_toolbar_from_active_tab()
        self._transient_status("Move undone")

    def _select_all_pages(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.loader is None or tab.is_preview_visible():
            return
        tab.thumbnail_grid.selection_manager.select_all()

    def _clear_selection(self) -> None:
        tab = self._active_tab()
        if tab is None:
            return
        tab.thumbnail_grid.selection_manager.clear()

    def _on_escape(self) -> None:
        tab = self._active_tab()
        if tab is None:
            return
        if tab.is_preview_visible():
            tab.close_preview()
            self._update_preview_mode_ui()
            return
        if tab.thumbnail_grid.selection_manager.selection:
            self._clear_selection()

    def _preview_start_page(self) -> int:
        tab = self._active_tab()
        if tab is None:
            return 0
        selection = tab.thumbnail_grid.selection_manager.selection
        if selection:
            return min(selection)
        return 0

    def _is_preview_visible(self) -> bool:
        tab = self._active_tab()
        return tab is not None and tab.is_preview_visible()

    def _close_preview(self) -> None:
        tab = self._active_tab()
        if tab is None or not tab.is_preview_visible():
            return
        tab.close_preview()
        self._update_preview_mode_ui()
        if tab.edit_model is not None:
            selection = tab.thumbnail_grid.selection_manager.selection
            self._update_selection_status(selection)
            count = tab.edit_model.logical_count()
            noun = "page" if count == 1 else "pages"
            self._persistent_status(f"Loaded {count} {noun}")

    def _open_preview(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.loader is None:
            return
        if tab.is_preview_visible():
            self._close_preview()
            return
        self._open_preview_at(self._preview_start_page())

    def _open_preview_at(self, page_index: int) -> None:
        tab = self._active_tab()
        if tab is None or tab.loader is None:
            return

        tab.show_preview_at(page_index)
        self._update_preview_mode_ui()
        self._update_preview_status()

    def _update_preview_mode_ui(self) -> None:
        tab = self._active_tab()
        in_preview = tab is not None and tab.is_preview_visible()
        self._preview_action.setText("Back to grid" if in_preview else "Preview")
        if in_preview:
            self._set_action_hint(self._preview_action, "Return to the thumbnail grid")
        else:
            self._set_action_hint(
                self._preview_action,
                "Preview selected page (Enter or double-click a card)",
            )
        has_pdf = tab is not None and tab.loader is not None
        self._zoom_controls.setVisible(not in_preview)
        self._clear_selection_action.setEnabled(not in_preview)
        self._select_all_action.setEnabled(has_pdf and not in_preview)
        self._deselect_all_action.setEnabled(
            has_pdf
            and not in_preview
            and bool(tab.thumbnail_grid.selection_manager.selection)
        )
        self._update_delete_pages_action()
        self._update_move_pages_actions()
        self._update_page_op_actions()

    def _update_preview_status(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or not tab.is_preview_visible():
            return
        page = tab.preview_widget.current_page + 1
        total = tab.edit_model.logical_count()
        self._persistent_status(f"Preview · page {page} of {total}")

    def _on_preview_page_changed(self, page_index: int) -> None:
        tab = self._active_tab()
        if tab is None or tab.preview_widget is not self.sender():
            return
        tab.thumbnail_grid.selection_manager.select_single(page_index)
        self._update_preview_status()

    def _on_tab_pdf_loaded(self) -> None:
        """Auto-fit thumbnail columns after open unless the user already zoomed."""
        tab = self.sender()
        if not isinstance(tab, PdfTab):
            return
        if not tab.thumbnail_grid.autofit_thumbnails_if_allowed():
            return
        if tab is self._active_tab():
            self._zoom_controls.set_value(tab.zoom_level)

    def _on_zoom_requested(self, thumbnail_width_px: int) -> None:
        tab = self._active_tab()
        if tab is None:
            return
        tab.set_zoom_level(thumbnail_width_px, manual=True)

    def _reset_thumbnail_zoom(self) -> None:
        self._on_zoom_requested(DEFAULT_THUMBNAIL_WIDTH)

    def _reset_zoom(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.loader is None:
            return
        if tab.is_preview_visible():
            tab.preview_widget.reset_zoom_to_fit()
            return
        self._reset_thumbnail_zoom()

    def _go_to_page_dialog(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None:
            return
        count = tab.edit_model.logical_count()
        if count <= 0:
            return
        current = 1
        if tab.is_preview_visible():
            current = tab.preview_widget.current_page + 1
        elif tab.thumbnail_grid.selection_manager.selection:
            current = min(tab.thumbnail_grid.selection_manager.selection) + 1
        page, ok = QInputDialog.getInt(
            self,
            "Go to Page",
            f"Page number (1–{count}):",
            current,
            1,
            count,
        )
        if not ok:
            return
        index = page - 1
        if tab.is_preview_visible():
            tab.preview_widget.show_page(index)
            tab.thumbnail_grid.selection_manager.select_single(index)
            self._update_preview_status()
            return
        tab.thumbnail_grid.jump_to_pages([index])

    def _page_range_jump_dialog(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None:
            return
        count = tab.edit_model.logical_count()
        if count <= 0:
            return
        text, ok = QInputDialog.getText(
            self,
            "Jump to Pages",
            f"Page or range (e.g. 12 or 1-5), 1–{count}:",
        )
        if not ok:
            return
        indices = parse_page_jump(text, count)
        if not indices:
            self._transient_status("Enter a page number or range like 12 or 1-5")
            return
        if tab.is_preview_visible():
            tab.close_preview()
        tab.thumbnail_grid.jump_to_pages(indices)
        if len(indices) == 1:
            self._transient_status(f"Jumped to page {indices[0] + 1}")
        else:
            self._transient_status(
                f"Selected pages {indices[0] + 1}–{indices[-1] + 1}"
            )

    def _on_zoom_changed(self, thumbnail_width_px: int) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        # Auto-fit must not overwrite the user's remembered zoom preference.
        grid = self.sender()
        if getattr(grid, "manual_zoom", True):
            set_thumbnail_zoom(thumbnail_width_px)
        tab = self._active_tab()
        if tab is not None and tab.loader is not None:
            self._zoom_controls.set_value(thumbnail_width_px)
            self._transient_status(
                f"Thumbnail size: {thumbnail_width_px} px"
            )

    def _on_light_theme_toggled(self, enabled: bool) -> None:
        set_light_theme(enabled)
        refresh_themed_widgets()
        # Keep other windows' checkboxes in sync.
        if self._window_manager is not None:
            for window in self._window_manager.windows:
                action = getattr(window, "_light_theme_action", None)
                if action is not None and action.isChecked() != enabled:
                    action.blockSignals(True)
                    action.setChecked(enabled)
                    action.blockSignals(False)

    def _on_thumbnail_quality_triggered(self, action: QAction) -> None:
        value = action.data()
        if not isinstance(value, str):
            return
        set_thumbnail_quality(value)
        if self._window_manager is not None:
            for window in self._window_manager.windows:
                window._sync_quality_menu(value)
                window._refresh_all_thumbnail_quality()
        else:
            self._refresh_all_thumbnail_quality()

    def _sync_quality_menu(self, value: str) -> None:
        for action in self._quality_action_group.actions():
            checked = action.data() == value
            if action.isChecked() != checked:
                action.blockSignals(True)
                action.setChecked(checked)
                action.blockSignals(False)

    def _refresh_all_thumbnail_quality(self) -> None:
        for index in range(self._tab_manager.count()):
            tab = self._tab_manager.widget(index)
            if isinstance(tab, PdfTab):
                tab.thumbnail_grid.refresh_thumbnail_quality()

    def _open_command_palette(self) -> None:
        dialog = CommandPalette(collect_actions(self), self)
        dialog.exec()

    @staticmethod
    def _set_action_hint(action: QAction, text: str) -> None:
        """Tooltip + status-bar hint (shown while hovering toolbar buttons)."""
        action.setToolTip(text)
        action.setStatusTip(text)

    def _maybe_show_first_run_tips(self) -> None:
        if os.environ.get("PAGEDROP_TESTING") == "1":
            return
        if has_seen_tips():
            return
        self._show_tips_overlay()

    def _show_tips_overlay(self) -> None:
        self._tips_overlay.show_tips()

    def _show_keyboard_shortcuts(self) -> None:
        KeyboardShortcutsDialog(self).exec()

    def eventFilter(self, obj, event) -> bool:
        if (
            event.type() != QEvent.Type.KeyPress
            or not isinstance(event, QKeyEvent)
            or QApplication.activeModalWidget() is not None
        ):
            return super().eventFilter(obj, event)

        tab = self._active_tab()
        if tab is None or tab.loader is None or tab.is_preview_visible():
            return super().eventFilter(obj, event)

        if event.matches(QKeySequence.StandardKey.SelectAll):
            self._select_all_pages()
            return True
        if event.text() in {"+", "="}:
            tab.thumbnail_grid.zoom_by(ZOOM_WHEEL_STEP)
            return True
        if event.text() == "-":
            tab.thumbnail_grid.zoom_by(-ZOOM_WHEEL_STEP)
            return True

        return super().eventFilter(obj, event)

    def _update_window_title(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.pdf_path is None:
            self.setWindowTitle(self.APP_TITLE)
            return
        # tab.tab_title already includes dirty * and save-path / custom names.
        count = tab.edit_model.logical_count()
        noun = "page" if count == 1 else "pages"
        self.setWindowTitle(
            f"{self.APP_TITLE} — {tab.tab_title} ({count} {noun})"
        )

    def _extract_selected_to_folder(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.loader is None:
            return
        selection = tab.thumbnail_grid.selection_manager.selection
        if not selection:
            return

        start_dir = last_directory()
        folder = QFileDialog.getExistingDirectory(
            self,
            "Extract selected pages to folder",
            start_dir,
        )
        if not folder:
            return

        remember_directory(folder)
        try:
            paths = tab.thumbnail_grid.extract_selected_to_folder(Path(folder))
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Extract Pages",
                f"Could not write PDFs to the chosen folder:\n{exc}",
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Extract Pages",
                f"Could not extract pages:\n{exc}",
            )
            return

        count = len(paths)
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Extracted {count} {noun} to {folder}")
        self._show_toast(f"Extracted {count} {noun}")

    def _export_all_pages(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.edit_model.logical_count() == 0:
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Export All Pages",
            last_directory(),
        )
        if not folder:
            return

        remember_directory(folder)
        try:
            paths = tab.thumbnail_grid.extract_all_to_folder(Path(folder))
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Export All Pages",
                f"Could not write PDFs to the chosen folder:\n{exc}",
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export All Pages",
                f"Could not export pages:\n{exc}",
            )
            return

        count = len(paths)
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Exported {count} {noun} to {folder}")
        self._show_toast(f"Exported {count} {noun}")

    def _extract_selected_to_new_tab(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.is_preview_visible():
            return
        refs = tab.selected_page_refs()
        if not refs:
            return

        new_tab = self._tab_manager.add_blank_tab()
        new_tab.init_from_page_refs(list(refs))
        self._tab_manager.setCurrentWidget(new_tab)
        self._tab_manager.update_tab_title(new_tab)
        self._sync_toolbar_from_active_tab()
        count = len(refs)
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Extracted {count} {noun} to new tab")
        self._show_toast(f"Extracted {count} {noun} to new tab")

    def _extract_selected_to_new_window(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.is_preview_visible():
            return
        refs = tab.selected_page_refs()
        if not refs:
            return

        if self._window_manager is not None:
            new_window = self._window_manager.open_new_window()
        else:
            new_window = MainWindow()
            new_window.show()

        target = new_window._active_tab()
        if target is None or not target.is_blank:
            target = new_window._tab_manager.add_blank_tab()
        target.init_from_page_refs(list(refs))
        new_window._tab_manager.setCurrentWidget(target)
        new_window._tab_manager.update_tab_title(target)
        new_window._sync_toolbar_from_active_tab()
        new_window.raise_()
        new_window.activateWindow()

        count = len(refs)
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Extracted {count} {noun} to new window")
        self._show_toast(f"Extracted {count} {noun} to new window")

    def _open_merge_window(self) -> None:
        if self._merge_window is None:
            self._merge_window = MergeWindow(parent=self)
        self._merge_window.show()
        self._merge_window.raise_()
        self._merge_window.activateWindow()

    def _open_convert_window(self) -> None:
        if self._convert_window is None:
            self._convert_window = ConvertWindow(parent=self)
        self._convert_window.show()
        self._convert_window.raise_()
        self._convert_window.activateWindow()

    def _open_pdf(self) -> None:
        start_dir = last_directory()
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open PDF",
            start_dir,
            "PDF Files (*.pdf);;All Files (*)",
        )
        if not paths:
            return

        remember_directory(paths[0])

        if len(paths) == 1:
            self._open_single_pdf(paths[0])
            return

        active = self._active_tab()
        # Blank tab: each file into its own tab, no prompt (first reuses the blank).
        if active is not None and active.is_blank:
            self._open_paths_as_tabs(paths, first_tab=active)
            return

        choice = self._ask_multi_open_target(len(paths))
        if choice is None:
            return
        if choice == "tabs":
            self._open_paths_as_tabs(paths)
        else:
            for path in paths:
                self._open_in_new_window(path)

    def _open_paths_as_tabs(
        self, paths: list[str], *, first_tab: PdfTab | None = None
    ) -> None:
        """Load each path into its own tab. Reuses *first_tab* when given."""
        if not paths:
            return
        if first_tab is not None:
            self._load_pdf(paths[0], tab=first_tab)
            rest = paths[1:]
        else:
            rest = paths
        for path in rest:
            tab = self._tab_manager.add_blank_tab()
            tab.set_zoom_level(thumbnail_zoom())
            self._load_pdf(path, tab=tab)
        self._tab_manager.setCurrentIndex(self._tab_manager.count() - 1)

    def _populate_open_recent_menu(self) -> None:
        menu = self._open_recent_menu
        menu.clear()
        paths = recent_files()
        if not paths:
            empty = menu.addAction("No recent files")
            empty.setEnabled(False)
            return
        for index, path in enumerate(paths):
            name = Path(path).name
            if index < 9:
                label = f"&{index + 1} {name}"
            elif index == 9:
                label = f"1&0 {name}"
            else:
                label = name
            action = menu.addAction(label)
            action.setData(path)
            action.setToolTip(path)
            action.triggered.connect(self._open_recent_file)

    def _open_recent_file(self) -> None:
        action = self.sender()
        if not isinstance(action, QAction):
            return
        path = action.data()
        if not isinstance(path, str) or not path:
            return
        if not Path(path).is_file():
            QMessageBox.warning(
                self,
                "Open Recent",
                f"File not found:\n{path}",
            )
            return
        remember_directory(path)
        self._open_recent_path(path)

    def _open_recent_path(self, path: str) -> None:
        """Open a recent PDF: current blank tab, else a new tab."""
        active = self._active_tab()
        if active is None:
            active = self._tab_manager.add_blank_tab()
        if active.is_blank:
            self._load_pdf(path, tab=active)
            return
        tab = self._tab_manager.add_blank_tab()
        self._tab_manager.setCurrentWidget(tab)
        self._load_pdf(path, tab=tab)

    def _open_single_pdf(self, path: str) -> None:
        active = self._active_tab()
        if active is None:
            active = self._tab_manager.add_blank_tab()

        if active.is_blank:
            choice = self._ask_open_target(path)
            if choice == "current":
                self._load_pdf(path, tab=active)
            elif choice == "new":
                tab = self._tab_manager.add_blank_tab()
                self._tab_manager.setCurrentWidget(tab)
                self._load_pdf(path, tab=tab)
            elif choice == "window":
                self._open_in_new_window(path)
            return

        choice = self._ask_open_target(path)
        if choice == "current":
            self._load_pdf(path, tab=active)
        elif choice == "new":
            tab = self._tab_manager.add_blank_tab()
            self._tab_manager.setCurrentWidget(tab)
            self._load_pdf(path, tab=tab)
        elif choice == "window":
            self._open_in_new_window(path)

    def _open_in_new_window(self, path: str) -> None:
        if self._window_manager is not None:
            new_window = self._window_manager.open_new_window()
        else:
            new_window = MainWindow()
            new_window.show()

        tab = new_window._active_tab()
        if tab is None or not tab.is_blank:
            tab = new_window._tab_manager.add_blank_tab()
        new_window._load_pdf(path, tab=tab)
        new_window.raise_()
        new_window.activateWindow()

    def _ask_open_target(self, path: str) -> str | None:
        filename = Path(path).name
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Question)
        message.setWindowTitle("Open PDF")
        message.setText(f"Where should {filename} be opened?")
        current_button = message.addButton(
            "Open in current tab",
            QMessageBox.ButtonRole.AcceptRole,
        )
        new_button = message.addButton(
            "Open in new tab",
            QMessageBox.ButtonRole.AcceptRole,
        )
        window_button = message.addButton(
            "Open in new window",
            QMessageBox.ButtonRole.AcceptRole,
        )
        cancel_button = message.addButton(
            QMessageBox.StandardButton.Cancel,
        )
        fit_message_box_buttons(message)
        message.exec()
        clicked = message.clickedButton()
        if clicked is cancel_button:
            return None
        if clicked is current_button:
            return "current"
        if clicked is new_button:
            return "new"
        if clicked is window_button:
            return "window"
        return None

    def _ask_multi_open_target(self, count: int) -> str | None:
        noun = "PDF" if count == 1 else "PDFs"
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Question)
        message.setWindowTitle("Open PDFs")
        message.setText(f"Where should {count} {noun} be opened?")
        tabs_button = message.addButton(
            "Each in new tab",
            QMessageBox.ButtonRole.AcceptRole,
        )
        windows_button = message.addButton(
            "Each in new window",
            QMessageBox.ButtonRole.AcceptRole,
        )
        cancel_button = message.addButton(
            QMessageBox.StandardButton.Cancel,
        )
        fit_message_box_buttons(message)
        message.exec()
        clicked = message.clickedButton()
        if clicked is cancel_button:
            return None
        if clicked is tabs_button:
            return "tabs"
        if clicked is windows_button:
            return "windows"
        return None

    def _prompt_pdf_password(
        self, filename: str, *, incorrect: bool = False
    ) -> str | None:
        """Ask for a PDF password. Returns None if the user cancels."""
        if incorrect:
            label = f'Incorrect password for "{filename}". Try again:'
        else:
            label = f'"{filename}" is password-protected.\nEnter password:'
        text, ok = QInputDialog.getText(
            self,
            "Password Required",
            label,
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return None
        return text

    def _load_pdf(self, path: str, *, tab: PdfTab | None = None) -> None:
        target = tab or self._active_tab()
        if target is None:
            target = self._tab_manager.add_blank_tab()

        filename = Path(path).name
        password: str | None = None
        cancelled_previous = target.thumbnail_grid.has_pending_work()

        while True:
            try:
                loader = target.load_pdf(path, password=password)
                break
            except PdfPasswordRequiredError:
                password = self._prompt_pdf_password(filename)
                if password is None:
                    if target is self._active_tab():
                        self._sync_toolbar_from_active_tab()
                        self._persistent_status("Ready")
                    return
            except PdfPasswordError:
                password = self._prompt_pdf_password(filename, incorrect=True)
                if password is None:
                    if target is self._active_tab():
                        self._sync_toolbar_from_active_tab()
                        self._persistent_status("Ready")
                    return
            except PdfEmptyError:
                QMessageBox.warning(
                    self,
                    "Open PDF",
                    f"{filename} has no pages.",
                )
                if target is self._active_tab():
                    self._sync_toolbar_from_active_tab()
                    self._persistent_status("Ready")
                return
            except PdfLoadError as exc:
                QMessageBox.critical(
                    self,
                    "Open PDF",
                    f"Could not open {filename}:\n{exc}",
                )
                if target is self._active_tab():
                    self._sync_toolbar_from_active_tab()
                    self._persistent_status("Ready")
                return

        self._tab_manager.update_tab_title(target)
        remember_recent_file(path)
        if target is self._active_tab():
            self._sync_toolbar_from_active_tab()
            count = (
                target.edit_model.logical_count()
                if target.edit_model is not None
                else loader.page_count
            )
            noun = "page" if count == 1 else "pages"
            if cancelled_previous:
                self._show_toast("Cancelled previous load")
            self._persistent_status(f"Loading {count} {noun}…")

    def _on_open_pdfs_requested(self, paths: list) -> None:
        """Open PDFs dropped onto a blank tab (first into that tab, rest as new tabs)."""
        if not paths or not self._grid_belongs_to_active_tab(self.sender()):
            return
        tab = self._active_tab()
        if tab is None or not tab.is_blank:
            return

        remember_directory(paths[0])
        self._open_paths_as_tabs(paths, first_tab=tab)

    def _same_path(self, left: str, right: str) -> bool:
        try:
            return Path(left).resolve().samefile(Path(right).resolve())
        except OSError:
            return Path(left).resolve() == Path(right).resolve()

    def _default_save_as_path(self, tab: PdfTab) -> str:
        model = tab.edit_model
        assert model is not None
        stem = tab.suggested_save_stem()
        if model.save_path is not None:
            start_dir = Path(model.save_path).parent
        elif tab.is_drop_initialized:
            last_dir = last_directory()
            start_dir = Path(last_dir) if last_dir else Path.home()
        else:
            start_dir = Path(model.original_path).parent
        return str(start_dir / f"{stem}.pdf")

    def _save_as(self, tab: PdfTab | None = None) -> bool:
        """Save the active tab (or *tab*) to a new path. Returns True on success."""
        target = tab or self._active_tab()
        if target is None or target.edit_model is None:
            return False

        model = target.edit_model
        if model.logical_count() == 0:
            return False

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save As",
            self._default_save_as_path(target),
            "PDF Files (*.pdf);;All Files (*)",
        )
        if not path:
            return False

        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"

        if self._same_path(path, model.original_path):
            QMessageBox.warning(
                self,
                "Save As",
                "Cannot save over the original file.\n"
                "Choose a different path.",
            )
            return False

        try:
            write_pdf(model, path)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Save As",
                f"Could not write PDF:\n{exc}",
            )
            return False
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Save As",
                f"Could not save PDF:\n{exc}",
            )
            return False

        remember_directory(path)
        model.mark_saved(path)
        target.clear_custom_tab_title()
        target._sync_dirty_from_model()
        self._tab_manager.update_tab_title(target)
        if target is self._active_tab():
            self._sync_toolbar_from_active_tab()
            self._transient_status(f"Saved to {Path(path).name}")
            self._show_toast(f"Saved to {Path(path).name}")
        return True

    def _rename_tab(self, index: int) -> None:
        if index < 0 or index >= self._tab_manager.count():
            return

        tab = self._tab_manager.widget(index)
        if not isinstance(tab, PdfTab) or not tab.can_rename_tab:
            return

        current = tab.tab_title.rstrip("*")
        if current == "New Tab":
            current = ""

        name, ok = QInputDialog.getText(
            self,
            "Rename Tab",
            "Tab name:",
            text=current,
        )
        if not ok:
            return

        if not tab.set_custom_tab_title(name):
            return

        self._tab_manager.update_tab_title(tab)
        if tab is self._active_tab():
            self._transient_status(f"Tab renamed to {tab.tab_title}")

    def _prompt_unsaved_changes(self, tab: PdfTab) -> str:
        """Return ``save``, ``discard``, or ``cancel``."""
        if os.environ.get("PAGEDROP_TESTING") == "1":
            return "discard"

        display_title = tab.tab_title.rstrip("*") or "document"
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Unsaved Changes")
        message.setText(f'"{display_title}" has unsaved changes.')
        message.setInformativeText("Save your changes before closing?")
        save_button = message.addButton(
            "Save As",
            QMessageBox.ButtonRole.AcceptRole,
        )
        discard_button = message.addButton(
            "Discard",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        cancel_button = message.addButton(QMessageBox.StandardButton.Cancel)
        fit_message_box_buttons(message)
        message.exec()
        clicked = message.clickedButton()
        if clicked is save_button:
            return "save"
        if clicked is discard_button:
            return "discard"
        return "cancel"

    def _try_close_tab(self, index: int) -> bool:
        if index < 0 or index >= self._tab_manager.count():
            return False

        tab = self._tab_manager.widget(index)
        if not isinstance(tab, PdfTab):
            return False

        if tab.is_blank:
            if self._is_only_blank_tab():
                return False
        elif tab.is_dirty and confirm_before_closing_dirty_tabs():
            choice = self._prompt_unsaved_changes(tab)
            if choice == "cancel":
                return False
            if choice == "save" and not self._save_as(tab):
                return False

        self._tab_manager.close_tab(index)
        return True

    def _close_tab(self) -> None:
        if self._is_only_blank_tab():
            self._transient_status("Cannot close the last blank tab")
            return
        index = self._tab_manager.currentIndex()
        if index >= 0 and self._try_close_tab(index):
            self._sync_toolbar_from_active_tab()
            self._transient_status("Tab closed")

    def _on_tab_close_requested(self, index: int) -> None:
        tab = self._tab_manager.widget(index)
        if isinstance(tab, PdfTab) and tab.is_blank and self._is_only_blank_tab():
            self._transient_status("Cannot close the last blank tab")
            return
        if self._try_close_tab(index):
            self._sync_toolbar_from_active_tab()
            self._transient_status("Tab closed")

    def _on_rendering_started(self, total_pages: int) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self._progress_bar.setRange(0, total_pages)
        self._progress_bar.setValue(0)
        self._progress_bar.setAccessibleDescription(f"0 of {total_pages} pages")
        self._progress_bar.show()

    def _on_rendering_progress(self, current: int, total: int) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self._progress_bar.setValue(current)
        self._progress_bar.setAccessibleDescription(f"{current} of {total} pages")
        # Preparing status comes from busy_changed; don't overwrite it.
        busy_reasons = getattr(self.sender(), "_busy_reasons", None)
        if busy_reasons is not None and "loading" in busy_reasons:
            return
        self._persistent_status(f"Rendering page {current} of {total}…")

    def _on_rendering_finished(self) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        tab = self._active_tab()
        self._progress_bar.hide()
        if tab is not None and tab.edit_model is not None:
            self._update_selection_status(
                tab.thumbnail_grid.selection_manager.selection
            )
            count = tab.edit_model.logical_count()
            noun = "page" if count == 1 else "pages"
            self._persistent_status(f"Loaded {count} {noun}")

    def _on_pages_inserted(
        self, count: int, filename: str, position: int
    ) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self._update_window_title()
        self._update_undo_redo_actions()
        noun = "page" if count == 1 else "pages"
        self._transient_status(
            f"Inserted {count} {noun} from {filename} at position {position}"
        )
        self._show_toast(f"Inserted {count} {noun}")

    def _on_pages_reordered(self) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self._update_undo_redo_actions()
        self._update_move_pages_actions()

    def _on_cross_window_pages_inserted(
        self, count: int, filename: str
    ) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Inserted {count} {noun} from {filename}")
        self._show_toast(f"Inserted {count} {noun}")
        self._sync_toolbar_from_active_tab()

    def _on_pages_moved_out(
        self, count: int, target_filename: str, undo=None
    ) -> None:
        sender = self.sender()
        if sender is not None and not self._grid_belongs_to_window(sender):
            return
        self._sync_toolbar_from_active_tab()
        if callable(undo):
            self._offer_move_undo(count, undo)
            return
        if sender is None or not self._grid_belongs_to_active_tab(sender):
            return
        noun = "page" if count == 1 else "pages"
        suffix = f" to {target_filename}" if target_filename else ""
        self._transient_status(f"Moved {count} {noun}{suffix}")

    def _on_pages_transferred_via_tab_bar(
        self, count: int, target_filename: str, moved: bool, undo=None
    ) -> None:
        sender = self.sender()
        if sender is not None and not self._grid_belongs_to_window(sender):
            return
        if moved and callable(undo):
            self._sync_toolbar_from_active_tab()
            self._offer_move_undo(count, undo)
            return
        noun = "page" if count == 1 else "pages"
        verb = "Moved" if moved else "Appended"
        suffix = f" to {target_filename}" if target_filename else ""
        self._transient_status(f"{verb} {count} {noun}{suffix}")
        self._sync_toolbar_from_active_tab()

    def _on_page_transfer_failed(self, message: str) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        QMessageBox.warning(self, "Page Transfer", message)
        self._transient_status(message)

    def _on_pdf_drop_failed(self, exc: object) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        if isinstance(exc, PdfEmptyError):
            QMessageBox.warning(
                self,
                "Insert PDF",
                f"{exc}",
            )
        elif isinstance(exc, PdfLoadError):
            QMessageBox.critical(
                self,
                "Insert PDF",
                f"Could not open PDF:\n{exc}",
            )
        else:
            QMessageBox.critical(
                self,
                "Insert PDF",
                f"Could not insert PDF:\n{exc}",
            )
        self._persistent_status("Ready")

    def _on_rendering_error(self, message: str) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self._progress_bar.hide()
        QMessageBox.critical(
            self,
            "Render Thumbnails",
            f"Could not render thumbnails:\n{message}",
        )
        self._transient_status("Rendering failed")

    def _on_preview_render_error(self, message: str) -> None:
        tab = self._active_tab()
        if tab is None or self.sender() is not tab.preview_widget:
            return
        QMessageBox.critical(
            self,
            "Preview",
            f"Could not render preview:\n{message}",
        )
        self._transient_status("Preview rendering failed")

    def _on_grid_busy_changed(self, busy: bool, message: str) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        tab = self._active_tab()
        if tab is None or tab.is_preview_visible():
            return
        if busy and message:
            self._persistent_status(message)
        elif tab.edit_model is not None and not self._progress_bar.isVisible():
            count = tab.edit_model.logical_count()
            noun = "page" if count == 1 else "pages"
            self._persistent_status(f"Loaded {count} {noun}")

    def _on_preview_busy_changed(self, busy: bool, message: str) -> None:
        tab = self._active_tab()
        if tab is None or self.sender() is not tab.preview_widget:
            return
        if busy and message:
            self._persistent_status(message)
        elif tab.edit_model is not None:
            page = tab.preview_widget.current_page + 1
            total = tab.edit_model.logical_count()
            self._persistent_status(f"Preview · page {page} of {total}")

    def _on_selection_changed(self, selection: set[int]) -> None:
        sender = self.sender()
        if sender is not None and not self._grid_belongs_to_active_tab(sender):
            return
        tab = self._active_tab()
        has_selection = bool(selection)
        self._deselect_all_action.setEnabled(
            tab is not None
            and tab.loader is not None
            and has_selection
            and not tab.is_preview_visible()
        )
        self._update_delete_pages_action()
        self._update_move_pages_actions()
        self._update_page_op_actions()
        self._update_selection_status(selection)

    def closeEvent(self, event: QCloseEvent) -> None:
        dirty_tabs: list[PdfTab] = []
        for index in range(self._tab_manager.count()):
            widget = self._tab_manager.widget(index)
            if (
                isinstance(widget, PdfTab)
                and not widget.is_blank
                and widget.is_dirty
            ):
                dirty_tabs.append(widget)

        if confirm_before_closing_dirty_tabs():
            for tab in dirty_tabs:
                choice = self._prompt_unsaved_changes(tab)
                if choice == "cancel":
                    event.ignore()
                    return
                if choice == "save" and not self._save_as(tab):
                    event.ignore()
                    return

        QApplication.instance().removeEventFilter(self)
        for index in range(self._tab_manager.count()):
            widget = self._tab_manager.widget(index)
            if isinstance(widget, PdfTab):
                widget.close_loader()
        self._temp_manager.cleanup()
        save_window_geometry(self.saveGeometry())
        super().closeEvent(event)
        if event.isAccepted() and self._window_manager is not None:
            self._window_manager.notify_window_closed(self)

    def restore_saved_geometry(self) -> bool:
        """Apply persisted geometry when the preference is on. Returns True if applied."""
        geometry = load_window_geometry()
        if geometry is None:
            return False
        return self.restoreGeometry(geometry)
