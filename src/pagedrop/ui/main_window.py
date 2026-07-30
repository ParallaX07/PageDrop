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
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

from pagedrop.core.jobs.paths import paths_refer_to_same_file
from pagedrop.core.pdf_loader import (
    PdfEmptyError,
    PdfLoadError,
    PdfPasswordError,
    PdfPasswordRequiredError,
)
from pagedrop.core.pdf_writer import write_pdf
from pagedrop.ui.actions import ActionRegistry
from pagedrop.ui.busy_overlay import ToastOverlay
from pagedrop.ui.command_palette import CommandPalette, action_label
from pagedrop.ui.dialogs import (
    fit_message_box_buttons,
    prompt_pdf_password,
    prompt_unsaved_changes,
)
from pagedrop.ui.keyboard_nav import (
    enable_toolbar_keyboard_navigation,
    set_content_tab_order,
)
from pagedrop.ui.onboarding import KeyboardShortcutsDialog, TipsOverlay
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.accessibility import refresh_themed_widgets
from pagedrop.ui import icons
from pagedrop.ui.settings import (
    chrome_visible,
    confirm_before_closing_dirty_tabs,
    has_seen_tips,
    last_directory,
    light_theme,
    load_window_geometry,
    recent_files,
    remember_directory,
    remember_recent_file,
    save_window_geometry,
    set_chrome_visible,
    set_light_theme,
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
    TOOLBAR_FILENAME_MAX_WIDTH,
    ZOOM_WHEEL_STEP,
)
from pagedrop.ui.zoom_controls import ZoomControls
from pagedrop.utils.page_jump import parse_page_jump
from pagedrop.utils.temp_manager import TempManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from pagedrop.ui.convert_window import ConvertWindow
    from pagedrop.ui.merge_window import MergeWindow
    from pagedrop.ui.tools_window import ToolsWindow
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
        self._tools_window: ToolsWindow | None = None
        self._tool_pages: dict[str, QWidget] = {}
        self._tool_shells: dict[str, QWidget] = {}
        self._previous_tab_index: int | None = None
        self._last_tab_index: int = 0
        self._pending_move_undo: Callable[[], bool] | None = None
        self._pending_selection: set[int] | None = None
        self._last_selection_toolbar_snap: tuple | None = None
        self._selection_coalesce_timer = QTimer(self)
        self._selection_coalesce_timer.setSingleShot(True)
        self._selection_coalesce_timer.setInterval(0)
        self._selection_coalesce_timer.timeout.connect(self._flush_selection_toolbar)

        self.setWindowTitle(self.APP_TITLE)
        self.setMinimumSize(720, 480)
        self.resize(960, 680)

        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_status_widgets()
        self._build_central_widget()
        self._set_chrome_visible(chrome_visible(), persist=False)
        refresh_cb = self._refresh_action_icons
        icons.register_refresh(refresh_cb)
        self.destroyed.connect(lambda *_: icons.unregister_refresh(refresh_cb))
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

    def _build_actions(self) -> None:
        """Create the single action catalogue used by menu, toolbar, and shortcuts."""
        actions = ActionRegistry(self)
        self._actions = actions

        actions.register(
            "open",
            "&Open PDF",
            slot=self._open_pdf,
            shortcut=QKeySequence.StandardKey.Open,
            icon=icons.icon("folder-open"),
            tip="Open a PDF (Ctrl+O)",
        )
        self._close_action = actions.register(
            "close_tab",
            "&Close tab",
            slot=self._close_tab,
            shortcut="Ctrl+W",
            add_to_window=True,
        )
        self._save_as_action = actions.register(
            "save_as",
            "Save &as",
            slot=self._save_as,
            shortcut="Ctrl+Shift+S",
            enabled=False,
        )
        self._export_all_action = actions.register(
            "export_all",
            "Export all &pages…",
            slot=self._export_all_pages,
            enabled=False,
        )
        self._new_window_action = actions.register(
            "new_window",
            "New &window",
            slot=self._new_window,
            shortcut="Ctrl+Shift+N",
        )
        actions.register("exit", "E&xit", slot=self.close)

        self._undo_action = actions.register(
            "undo",
            "&Undo",
            slot=self._undo,
            shortcut=QKeySequence.StandardKey.Undo,
            enabled=False,
        )
        self._redo_action = actions.register(
            "redo",
            "&Redo",
            slot=self._redo,
            shortcuts=["Ctrl+Shift+Z", QKeySequence.StandardKey.Redo],
            enabled=False,
        )
        self._light_theme_action = actions.register(
            "light_theme",
            "Toggle &light theme",
            slot=self._on_light_theme_toggled,
            checkable=True,
            checked=light_theme(),
        )
        self._chrome_visible_action = actions.register(
            "chrome_visible",
            "Show &menu and toolbar",
            slot=self._on_chrome_visible_toggled,
            shortcut="Ctrl+Shift+H",
            checkable=True,
            checked=chrome_visible(),
            tip="Show or hide the menu and toolbar (Ctrl+Shift+H)",
            add_to_window=True,
        )
        self._quality_action_group = QActionGroup(self)
        self._quality_action_group.setExclusive(True)
        current_quality = thumbnail_quality()
        for value, label in (
            ("low", "&Low"),
            ("medium", "&Medium"),
            ("high", "&High"),
        ):
            action = actions.register(
                f"quality_{value}",
                label,
                checkable=True,
                checked=value == current_quality,
                data=value,
            )
            self._quality_action_group.addAction(action)
        self._quality_action_group.triggered.connect(
            self._on_thumbnail_quality_triggered
        )
        self._command_palette_action = actions.register(
            "command_palette",
            "Command &palette…",
            slot=self._open_command_palette,
            shortcut="Ctrl+Shift+P",
        )

        actions.register("merge", "&Merge PDFs", slot=self._open_merge_window)
        actions.register(
            "create_pdf", "&Create PDF", slot=self._open_convert_window
        )
        actions.register(
            "tools",
            "&Tools",
            slot=self._open_tools_window,
            # Ctrl+T is New tab — use a dedicated chord for Tools.
            shortcut="Ctrl+Shift+O",
            tip="Open Tools (Ctrl+Shift+O)",
        )
        actions.register(
            "keyboard_shortcuts",
            "&Keyboard shortcuts",
            slot=self._show_keyboard_shortcuts,
            shortcut="Ctrl+/",
        )
        actions.register("tips", "Show &tips", slot=self._show_tips_overlay)
        actions.register(
            "preferences",
            "&Preferences…",
            slot=self._open_preferences,
            shortcut="Ctrl+,",
        )

        self._preview_action = actions.register(
            "preview",
            "Preview",
            slot=self._open_preview,
            icon=icons.icon("list"),
            tip="Preview selected page (Enter or double-click a card)",
            enabled=False,
        )
        self._select_all_action = actions.register(
            "select_all",
            "Select all",
            slot=self._select_all_pages,
            shortcut=QKeySequence.StandardKey.SelectAll,
            icon=icons.icon("selection-all"),
            tip="Select all pages (Ctrl+A)",
            enabled=False,
        )
        self._deselect_all_action = actions.register(
            "deselect_all",
            "Deselect all",
            slot=self._clear_selection,
            icon=icons.icon("selection-slash"),
            tip="Clear selection (Esc)",
            enabled=False,
        )
        # Esc closes preview or clears selection — not the same as Deselect All.
        # Empty text keeps it out of the command palette.
        self._clear_selection_action = actions.register(
            "escape",
            "",
            slot=self._on_escape,
            shortcut=QKeySequence.StandardKey.Cancel,
            add_to_window=True,
        )
        self._move_up_action = actions.register(
            "move_up",
            "Move up",
            slot=self._move_selected_pages_up,
            shortcut="Ctrl+Up",
            icon=icons.icon("arrow-up"),
            tip="Move selected pages up (Ctrl+↑)",
            enabled=False,
        )
        self._move_down_action = actions.register(
            "move_down",
            "Move down",
            slot=self._move_selected_pages_down,
            shortcut="Ctrl+Down",
            icon=icons.icon("arrow-down"),
            tip="Move selected pages down (Ctrl+↓)",
            enabled=False,
        )
        self._move_to_action = actions.register(
            "move_to",
            "Move to…",
            slot=self._move_selected_pages_to,
            shortcut="Ctrl+Shift+M",
            icon=icons.icon("arrows-down-up"),
            tip="Move selected pages to a page number (Ctrl+Shift+M)",
            enabled=False,
        )
        self._delete_pages_action = actions.register(
            "delete_pages",
            "Delete page(s)",
            slot=self._delete_selected_pages,
            shortcut=QKeySequence(Qt.Key.Key_Delete),
            icon=icons.icon("trash"),
            tip="Delete selected pages (Delete)",
            enabled=False,
        )
        self._duplicate_pages_action = actions.register(
            "duplicate_pages",
            "Duplicate",
            slot=self._duplicate_selected_pages,
            shortcut="Ctrl+D",
            icon=icons.icon("copy"),
            tip="Duplicate selected pages (Ctrl+D)",
            enabled=False,
        )
        self._rotate_cw_action = actions.register(
            "rotate_cw",
            "Rotate CW",
            slot=lambda: self._rotate_selected_pages(90),
            icon=icons.icon("arrow-clockwise"),
            tip="Rotate selected pages clockwise",
            enabled=False,
        )
        self._rotate_ccw_action = actions.register(
            "rotate_ccw",
            "Rotate CCW",
            slot=lambda: self._rotate_selected_pages(-90),
            icon=icons.icon("arrow-counter-clockwise"),
            tip="Rotate selected pages counter-clockwise",
            enabled=False,
        )

        actions.register(
            "next_tab",
            "Previous tab (MRU)",
            slot=self._switch_to_next_tab,
            shortcut="Ctrl+Tab",
            add_to_window=True,
        )
        actions.register(
            "prev_tab",
            "Cycle tabs backward",
            slot=self._switch_to_previous_tab,
            shortcut="Ctrl+Shift+Tab",
            add_to_window=True,
        )
        actions.register(
            "new_tab",
            "New tab",
            slot=self._new_blank_tab,
            shortcut="Ctrl+T",
            add_to_window=True,
        )
        self._go_to_page_action = actions.register(
            "go_to_page",
            "Go to page",
            slot=self._go_to_page_dialog,
            shortcut="Ctrl+G",
            add_to_window=True,
        )
        self._page_jump_action = actions.register(
            "page_jump",
            "Select page range",
            slot=self._page_range_jump_dialog,
            shortcut="Ctrl+F",
            add_to_window=True,
        )
        actions.register(
            "reset_zoom",
            "Reset zoom",
            slot=self._reset_zoom,
            shortcut="Ctrl+0",
            add_to_window=True,
        )

    def _refresh_action_icons(self) -> None:
        """Re-tint Phosphor toolbar icons after a light/dark swap."""
        a = self._actions
        a["open"].setIcon(icons.icon("folder-open"))
        a["preview"].setIcon(icons.icon("list"))
        a["select_all"].setIcon(icons.icon("selection-all"))
        a["deselect_all"].setIcon(icons.icon("selection-slash"))
        a["move_up"].setIcon(icons.icon("arrow-up"))
        a["move_down"].setIcon(icons.icon("arrow-down"))
        a["move_to"].setIcon(icons.icon("arrows-down-up"))
        a["delete_pages"].setIcon(icons.icon("trash"))
        a["duplicate_pages"].setIcon(icons.icon("copy"))
        a["rotate_cw"].setIcon(icons.icon("arrow-clockwise"))
        a["rotate_ccw"].setIcon(icons.icon("arrow-counter-clockwise"))

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        a = self._actions

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(a["open"])
        self._open_recent_menu = file_menu.addMenu("Open &recent")
        self._open_recent_menu.aboutToShow.connect(self._populate_open_recent_menu)
        file_menu.addAction(a["close_tab"])
        file_menu.addAction(a["save_as"])
        file_menu.addAction(a["export_all"])
        file_menu.addSeparator()
        file_menu.addAction(a["new_window"])
        file_menu.addSeparator()
        file_menu.addAction(a["exit"])

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(a["undo"])
        edit_menu.addAction(a["redo"])
        edit_menu.addSeparator()
        edit_menu.addAction(a["preferences"])

        view_menu = menubar.addMenu("&View")
        view_menu.addAction(a["light_theme"])
        view_menu.addAction(a["chrome_visible"])
        quality_menu = view_menu.addMenu("Thumbnail &quality")
        for key in ("quality_low", "quality_medium", "quality_high"):
            quality_menu.addAction(a[key])
        view_menu.addSeparator()
        view_menu.addAction(a["command_palette"])

        menubar.addAction(a["merge"])
        menubar.addAction(a["create_pdf"])
        menubar.addAction(a["tools"])

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(a["keyboard_shortcuts"])
        help_menu.addAction(a["tips"])

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self._toolbar = toolbar
        a = self._actions

        toolbar.addAction(a["open"])
        open_button = toolbar.widgetForAction(a["open"])
        if open_button is not None:
            open_button.setObjectName("ToolbarPrimary")

        toolbar.addAction(a["preview"])
        toolbar.addSeparator()
        toolbar.addAction(a["select_all"])
        toolbar.addAction(a["deselect_all"])
        toolbar.addAction(a["move_up"])
        toolbar.addAction(a["move_down"])
        toolbar.addAction(a["move_to"])
        toolbar.addAction(a["delete_pages"])
        toolbar.addAction(a["duplicate_pages"])
        toolbar.addAction(a["rotate_cw"])
        toolbar.addAction(a["rotate_ccw"])
        # QAction has no setAccessibleName — expand CW/CCW on the toolbar buttons.
        for action, name in (
            (a["rotate_cw"], "Rotate clockwise"),
            (a["rotate_ccw"], "Rotate counter-clockwise"),
        ):
            btn = toolbar.widgetForAction(action)
            if btn is not None:
                btn.setAccessibleName(name)
        toolbar.addSeparator()

        self._filename_label = QLabel("No file open")
        self._filename_label.setObjectName("ToolbarFilename")
        self._filename_label.setProperty("active", False)
        self._filename_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._filename_label.setWordWrap(False)
        self._filename_label.setMaximumWidth(TOOLBAR_FILENAME_MAX_WIDTH)
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

        self._chrome_toggle_btn = QToolButton()
        self._chrome_toggle_btn.setObjectName("ChromeToggleButton")
        self._chrome_toggle_btn.clicked.connect(self._toggle_chrome_visible)
        self._tab_manager.setCornerWidget(
            self._chrome_toggle_btn,
            Qt.Corner.TopLeftCorner,
        )

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

    def _show_toast(
        self,
        message: str,
        *,
        kind: str = "info",
        on_undo=None,
    ) -> None:
        self._toast.show_toast(message, kind=kind, on_undo=on_undo)

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
        grid.zoom_render_pending.connect(self._on_zoom_render_pending)
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
        tab.preview_widget.closed.connect(self._on_viewer_closed)
        tab.preview_widget.status_message.connect(self._transient_status)
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
            (grid.zoom_render_pending, self._on_zoom_render_pending),
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
            (preview.closed, self._on_viewer_closed),
            (preview.status_message, self._transient_status),
            (tab.dirty_changed, self._on_tab_dirty_changed),
        ):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass

    def _on_tab_dirty_changed(self, _dirty: bool = False) -> None:
        self._update_save_as_action()
        self._update_undo_redo_actions()
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
            self._transient_status("Cannot open a new window")
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

        if self._window_manager is None:
            self._transient_status("Cannot open a new window")
            return

        self._disconnect_tab_signals(tab)
        new_window = self._window_manager.open_new_window(tab)
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
        # Always enabled: `_close_tab` reports why the last blank tab cannot close.
        # Disabling here would also mute Ctrl+W (same QAction as the menu item).
        self._close_action.setEnabled(True)

    def _on_active_tab_changed(self, tab: PdfTab) -> None:
        if tab.is_preview_visible():
            tab.close_preview()
        self._sync_toolbar_from_active_tab()

    def _sync_toolbar_from_active_tab(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.is_blank:
            self._reset_toolbar_for_blank_tab()
            return

        pdf_path = tab.pdf_path or ""
        filename = Path(pdf_path).name if pdf_path else "No file open"
        self._update_window_title()
        self._set_toolbar_filename(filename, tooltip=pdf_path)
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
        self._zoom_controls.set_rendering(False)
        self._update_preview_mode_ui()
        self._update_close_tab_action()
        self._update_save_as_action()
        selection = tab.thumbnail_grid.selection_manager.selection
        self._pending_selection = selection
        self._last_selection_toolbar_snap = self._selection_toolbar_snapshot(
            selection
        )
        self._update_selection_status(selection)

    def _set_toolbar_filename(self, filename: str, *, tooltip: str = "") -> None:
        """Show a single-line elided name; full path stays on the tooltip (R14)."""
        metrics = self._filename_label.fontMetrics()
        self._filename_label.setText(
            metrics.elidedText(
                filename,
                Qt.TextElideMode.ElideRight,
                TOOLBAR_FILENAME_MAX_WIDTH,
            )
        )
        self._filename_label.setToolTip(tooltip)

    def _reset_toolbar_for_blank_tab(self) -> None:
        tab = self._active_tab()
        self._update_window_title()
        self._set_toolbar_filename("No file open")
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
        self._move_to_action.setEnabled(False)
        self._undo_action.setEnabled(False)
        self._redo_action.setEnabled(False)
        self._go_to_page_action.setEnabled(False)
        self._page_jump_action.setEnabled(False)
        self._zoom_controls.setEnabled(False)
        self._zoom_controls.set_value(
            tab.zoom_level if tab is not None else thumbnail_zoom()
        )
        self._zoom_controls.set_rendering(False)
        self._progress_bar.hide()
        self._update_close_tab_action()
        self._update_save_as_action()
        self._pending_selection = set()
        self._last_selection_toolbar_snap = self._selection_toolbar_snapshot(set())
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
        self._move_to_action.setEnabled(
            enabled and grid is not None and grid.can_move_selection_to()
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
        self._show_toast(f"Duplicated {count} {noun}", kind="success")

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

    def _move_selected_pages_to(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.is_preview_visible():
            return
        if not tab.thumbnail_grid.can_move_selection_to():
            return
        ordered = sorted(tab.thumbnail_grid.selection_manager.selection)
        count = tab.edit_model.logical_count()
        k = len(ordered)
        max_page = max(1, count - k + 1)
        default = min(ordered[0] + 1, max_page)
        page, ok = QInputDialog.getInt(
            self,
            "Move to page",
            f"Move selection to page (1–{max_page}):",
            default,
            1,
            max_page,
        )
        if not ok:
            return
        dest = page - 1
        if not tab.move_selected_pages_to(dest):
            self._transient_status(f"Already at page {page}")
            return
        self._tab_manager.update_tab_title(tab)
        self._update_move_pages_actions()
        self._update_undo_redo_actions()
        noun = "page" if k == 1 else "pages"
        landed = min(tab.thumbnail_grid.selection_manager.selection) + 1
        self._transient_status(f"Moved {k} {noun} to page {landed}")

    def _undo(self) -> None:
        tab = self._active_tab()
        if tab is None:
            return
        # Grid-edit undo stays blocked while preview is up; viewer markup undo is allowed.
        if tab.is_preview_visible() and not (
            tab.is_viewer_mode() and tab.markup_session.can_undo()
        ):
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
        if tab is None:
            return
        if tab.is_preview_visible() and not (
            tab.is_viewer_mode() and tab.markup_session.can_redo()
        ):
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
        markup_undo = tab is not None and tab.is_viewer_mode() and tab.markup_session.can_undo()
        markup_redo = tab is not None and tab.is_viewer_mode() and tab.markup_session.can_redo()
        self._undo_action.setEnabled(
            (markup_undo or (model is not None and model.can_undo() and not preview_blocking))
        )
        self._redo_action.setEnabled(
            (markup_redo or (model is not None and model.can_redo() and not preview_blocking))
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
        self._after_viewer_closed(tab)

    def _on_viewer_closed(self) -> None:
        """Esc from the viewer widget — PdfTab already switched the stack."""
        tab = self._active_tab()
        if tab is None or self.sender() is not tab.preview_widget:
            return
        self._after_viewer_closed(tab)

    def _after_viewer_closed(self, tab: PdfTab) -> None:
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
        # Viewer Find (Ctrl+F / Ctrl+G) lives on PdfViewerWidget.keyPressEvent —
        # disable WindowShortcut actions so they do not steal those keys.
        self._go_to_page_action.setEnabled(has_pdf and not in_preview)
        self._page_jump_action.setEnabled(has_pdf and not in_preview)
        self._update_delete_pages_action()
        self._update_move_pages_actions()
        self._update_page_op_actions()

    def _update_preview_status(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or not tab.is_preview_visible():
            return
        page = tab.preview_widget.current_page + 1
        total = tab.edit_model.logical_count()
        self._persistent_status(f"Page {page} of {total}")

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
        if tab.thumbnail_grid.autofit_thumbnails_if_allowed():
            if tab is self._active_tab():
                self._zoom_controls.set_value(tab.zoom_level)
        if tab is self._active_tab():
            self._maybe_quality_scale_guidance(tab)

    def _maybe_quality_scale_guidance(self, tab: PdfTab) -> None:
        tip = tab.quality_scale_guidance()
        if tip is not None:
            self._transient_status(tip)

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
            "Go to page",
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
        # Grid-only: in viewer mode Ctrl+F focuses Find (action disabled above).
        if tab.is_viewer_mode():
            return
        count = tab.edit_model.logical_count()
        if count <= 0:
            return
        text, ok = QInputDialog.getText(
            self,
            "Jump to pages",
            f"Page or range (e.g. 12 or 1-5), 1–{count}:",
        )
        if not ok:
            return
        indices = parse_page_jump(text, count)
        if not indices:
            self._transient_status("Enter a page number or range like 12 or 1-5")
            return
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
            tip = tab.quality_scale_guidance()
            if tip is not None:
                self._transient_status(tip)
            else:
                self._transient_status(
                    f"Thumbnail size: {thumbnail_width_px} px"
                )

    def _on_zoom_render_pending(self, pending: bool) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self._zoom_controls.set_rendering(pending)

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

    def _toggle_chrome_visible(self) -> None:
        action = getattr(self, "_chrome_visible_action", None)
        visible = True if action is None else action.isChecked()
        self._set_chrome_visible(not visible)

    def _on_chrome_visible_toggled(self, visible: bool) -> None:
        self._set_chrome_visible(visible)

    def _set_chrome_visible(self, visible: bool, *, persist: bool = True) -> None:
        self.menuBar().setVisible(visible)
        self._toolbar.setVisible(visible)
        action = getattr(self, "_chrome_visible_action", None)
        if action is not None and action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        btn = getattr(self, "_chrome_toggle_btn", None)
        if btn is not None:
            if visible:
                btn.setText("⌃")
                tip = "Hide menu and toolbar"
            else:
                btn.setText("⌄")
                tip = "Show menu and toolbar"
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)
        if persist:
            set_chrome_visible(visible)

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
        labeled = [a for a in self._actions.values() if action_label(a)]
        dialog = CommandPalette(labeled, self)
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

    def _open_preferences(self) -> None:
        from pagedrop.ui.preferences_dialog import open_preferences

        open_preferences(self)

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
        except (PdfPasswordRequiredError, PdfPasswordError) as exc:
            QMessageBox.critical(
                self,
                "Extract pages",
                f"Could not extract pages:\n{exc}",
            )
            return
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Extract pages",
                f"Could not write PDFs to the chosen folder:\n{exc}",
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Extract pages",
                f"Could not extract pages:\n{exc}",
            )
            return

        count = len(paths)
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Extracted {count} {noun} to {folder}")
        self._show_toast(f"Extracted {count} {noun}", kind="success")

    def _export_all_pages(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.edit_model.logical_count() == 0:
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Export all pages",
            last_directory(),
        )
        if not folder:
            return

        remember_directory(folder)
        try:
            paths = tab.thumbnail_grid.extract_all_to_folder(Path(folder))
        except (PdfPasswordRequiredError, PdfPasswordError) as exc:
            QMessageBox.critical(
                self,
                "Export all pages",
                f"Could not export pages:\n{exc}",
            )
            return
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Export all pages",
                f"Could not write PDFs to the chosen folder:\n{exc}",
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export all pages",
                f"Could not export pages:\n{exc}",
            )
            return

        count = len(paths)
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Exported {count} {noun} to {folder}")
        self._show_toast(f"Exported {count} {noun}", kind="success")

    def _extract_selected_to_new_tab(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.is_preview_visible():
            return
        refs = tab.selected_page_refs()
        if not refs:
            return

        new_tab = self._tab_manager.add_blank_tab()
        new_tab.init_from_page_refs(list(refs), credentials=tab.credentials)
        self._tab_manager.setCurrentWidget(new_tab)
        self._tab_manager.update_tab_title(new_tab)
        self._sync_toolbar_from_active_tab()
        count = len(refs)
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Extracted {count} {noun} to new tab")
        self._show_toast(f"Extracted {count} {noun} to new tab", kind="success")

    def _extract_selected_to_new_window(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or tab.is_preview_visible():
            return
        refs = tab.selected_page_refs()
        if not refs:
            return

        if self._window_manager is None:
            self._transient_status("Cannot open a new window")
            return

        new_window = self._window_manager.open_new_window()
        target = new_window._active_tab()
        if target is None or not target.is_blank:
            target = new_window._tab_manager.add_blank_tab()
        target.init_from_page_refs(list(refs), credentials=tab.credentials)
        new_window._tab_manager.setCurrentWidget(target)
        new_window._tab_manager.update_tab_title(target)
        new_window._sync_toolbar_from_active_tab()
        new_window.raise_()
        new_window.activateWindow()

        count = len(refs)
        noun = "page" if count == 1 else "pages"
        self._transient_status(f"Extracted {count} {noun} to new window")
        self._show_toast(f"Extracted {count} {noun} to new window", kind="success")

    def open_tool_page(self, page: QWidget, *, page_id: str) -> None:
        """Focus an existing tool tab or add *page* as a new tab."""
        page.tool_page_id = page_id  # type: ignore[attr-defined]
        existing = self._tool_pages.get(page_id)
        if existing is not None:
            index = self._tab_manager.indexOf(existing)
            if index >= 0:
                self._tab_manager.setCurrentIndex(index)
                self._sync_toolbar_from_active_tab()
                return
        title = getattr(page, "tab_title", None) or getattr(
            page, "WINDOW_TITLE", "Tool"
        )
        self._tool_pages[page_id] = page
        # PAGE_ID string literals match MergeWindow / ConvertWindow / ToolsWindow.
        if page_id == "tools":
            self._tools_window = page  # type: ignore[assignment]
        elif page_id == "merge":
            self._merge_window = page  # type: ignore[assignment]
        elif page_id == "create_pdf":
            self._convert_window = page  # type: ignore[assignment]
        self._tab_manager.add_page(page, str(title))
        self._sync_toolbar_from_active_tab()

    def _forget_tool_page(self, page: QWidget | None) -> None:
        if page is None:
            return
        page_id = getattr(page, "tool_page_id", None)
        if isinstance(page_id, str):
            self._tool_pages.pop(page_id, None)
            if page_id.startswith("tool:"):
                self._tool_shells.pop(page_id.removeprefix("tool:"), None)
            if self._tools_window is not None:
                if page_id.startswith("tool:"):
                    store = getattr(self._tools_window, "_tool_shells", None)
                    if isinstance(store, dict):
                        store.pop(page_id.removeprefix("tool:"), None)
                if page_id == "compare" and (
                    getattr(self._tools_window, "_compare_window", None) is page
                ):
                    self._tools_window._compare_window = None  # type: ignore[attr-defined]
        if page is self._tools_window:
            self._tools_window = None
        if page is self._merge_window:
            self._merge_window = None
        if page is self._convert_window:
            self._convert_window = None

    def _tool_page_open(self, page: QWidget | None) -> bool:
        if page is None:
            return False
        try:
            return self._tab_manager.indexOf(page) >= 0
        except RuntimeError:
            return False

    def _open_merge_window(self) -> None:
        from pagedrop.ui.merge_window import MergeWindow

        if not self._tool_page_open(self._merge_window):
            self._merge_window = MergeWindow(editor=self)
        else:
            assert self._merge_window is not None
            self._merge_window.set_editor(self)
        assert self._merge_window is not None
        self.open_tool_page(self._merge_window, page_id=MergeWindow.PAGE_ID)

    def _open_convert_window(self) -> None:
        from pagedrop.ui.convert_window import ConvertWindow

        if not self._tool_page_open(self._convert_window):
            self._convert_window = ConvertWindow(editor=self)
        else:
            assert self._convert_window is not None
            self._convert_window.set_editor(self)
        assert self._convert_window is not None
        self.open_tool_page(self._convert_window, page_id=ConvertWindow.PAGE_ID)

    def _open_tools_window(self) -> None:
        from pagedrop.ui.tools_window import ToolsWindow

        if not self._tool_page_open(self._tools_window):
            self._tools_window = ToolsWindow(
                editor=self,
                window_manager=self._window_manager,
            )
        else:
            assert self._tools_window is not None
            self._tools_window.set_editor(self)
        assert self._tools_window is not None
        self.open_tool_page(self._tools_window, page_id=ToolsWindow.PAGE_ID)

    def _open_pdf(self) -> None:
        start_dir = last_directory()
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open PDF",
            start_dir,
            "PDF files (*.pdf);;All files (*)",
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
                "Open recent",
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
        if self._window_manager is None:
            self._transient_status("Cannot open a new window")
            return

        new_window = self._window_manager.open_new_window()
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
        return prompt_pdf_password(self, filename, incorrect=incorrect)

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
                self._show_toast("Cancelled previous load", kind="info")
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
        return paths_refer_to_same_file(left, right)

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
            "Save as",
            self._default_save_as_path(target),
            "PDF files (*.pdf);;All files (*)",
        )
        if not path:
            return False

        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"

        if self._same_path(path, model.original_path):
            QMessageBox.warning(
                self,
                "Save as",
                "Cannot save over the original file.\n"
                "Choose a different path.",
            )
            return False

        try:
            write_pdf(
                model,
                path,
                markup=target.markup_session.non_redaction_ops() or None,
                passwords=target.credentials.snapshot(),
            )
        except (PdfPasswordRequiredError, PdfPasswordError) as exc:
            QMessageBox.critical(
                self,
                "Save as",
                f"Could not save PDF:\n{exc}",
            )
            return False
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Save as",
                f"Could not write PDF:\n{exc}",
            )
            return False
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Save as",
                f"Could not save PDF:\n{exc}",
            )
            return False

        remember_directory(path)
        model.mark_saved(path)
        had_redactions = bool(target.markup_session.redaction_regions())
        target.clear_markup_after_save()
        target.clear_custom_tab_title()
        target._sync_dirty_from_model()
        self._tab_manager.update_tab_title(target)
        if target is self._active_tab():
            self._sync_toolbar_from_active_tab()
            if had_redactions:
                self._transient_status(
                    f"Saved to {Path(path).name} — redaction marks kept; use Apply redaction"
                )
            else:
                self._transient_status(f"Saved to {Path(path).name}")
            self._show_toast(f"Saved to {Path(path).name}", kind="success")
        return True

    def _rename_tab(self, index: int) -> None:
        if index < 0 or index >= self._tab_manager.count():
            return

        tab = self._tab_manager.widget(index)
        if not isinstance(tab, PdfTab) or not tab.can_rename_tab:
            return

        current = tab.tab_title.rstrip("*")
        if current == "New tab":
            current = ""

        name, ok = QInputDialog.getText(
            self,
            "Rename tab",
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
        return prompt_unsaved_changes(self, tab.tab_title)

    def _try_close_tab(self, index: int) -> bool:
        if index < 0 or index >= self._tab_manager.count():
            return False

        tab = self._tab_manager.widget(index)
        if isinstance(tab, PdfTab):
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

        if tab is None:
            return False
        request_close = getattr(tab, "request_close", None)
        if callable(request_close) and not request_close():
            return False
        self._forget_tool_page(tab)
        self._tab_manager.close_tab(index)
        return True

    def _close_tab(self) -> None:
        index = self._tab_manager.currentIndex()
        widget = self._tab_manager.widget(index) if index >= 0 else None
        if isinstance(widget, PdfTab) and self._is_only_blank_tab():
            self._transient_status("Cannot close the last blank tab")
            return
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
        self._show_toast(f"Inserted {count} {noun}", kind="success")

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
        self._show_toast(f"Inserted {count} {noun}", kind="success")
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
        QMessageBox.warning(self, "Page transfer", message)
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
            "Render thumbnails",
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
        elif tab.is_viewer_mode() and tab.edit_model is not None:
            page = tab.preview_widget.current_page + 1
            total = tab.edit_model.logical_count()
            self._persistent_status(f"Page {page} of {total}")

    def _selection_toolbar_snapshot(self, selection: set[int]) -> tuple:
        """Toolbar-relevant view of selection — skip redundant coalesced flushes."""
        tab = self._active_tab()
        if tab is None:
            return (None, frozenset())
        if selection:
            lo, hi = min(selection), max(selection)
        else:
            lo = hi = -1
        return (
            id(tab),
            tab.is_preview_visible(),
            bool(selection),
            len(selection),
            lo,
            hi,
        )

    def _on_selection_changed(self, selection: set[int]) -> None:
        sender = self.sender()
        if sender is not None and not self._grid_belongs_to_active_tab(sender):
            return
        self._pending_selection = selection
        # First update in a turn applies immediately (snappy); further emits in
        # the same turn only refresh pending and ride the 0ms coalesce timer.
        if self._selection_coalesce_timer.isActive():
            return
        self._flush_selection_toolbar()
        self._selection_coalesce_timer.start()

    def _flush_selection_toolbar(self) -> None:
        selection = self._pending_selection
        if selection is None:
            return
        snap = self._selection_toolbar_snapshot(selection)
        if snap == self._last_selection_toolbar_snap:
            return
        self._last_selection_toolbar_snap = snap
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
        if self._should_persist_geometry():
            save_window_geometry(self.saveGeometry())
        super().closeEvent(event)
        if event.isAccepted() and self._window_manager is not None:
            self._window_manager.notify_window_closed(self)

    def _should_persist_geometry(self) -> bool:
        """Only the primary editor (or unmanaged solo window) saves geometry."""
        if self._window_manager is None:
            return True
        return self._window_manager.is_primary(self)

    def restore_saved_geometry(self) -> bool:
        """Apply persisted geometry when the preference is on. Returns True if applied."""
        geometry = load_window_geometry()
        if geometry is None:
            return False
        return self.restoreGeometry(geometry)
