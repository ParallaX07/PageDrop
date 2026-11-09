from __future__ import annotations

import copy
import ctypes
import os
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QEventLoop, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QKeySequence,
    QWindow,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolBar,
    QToolButton,
    QWidget,
)

from pagedrop.core.editor_jobs import register_editor_handlers
from pagedrop.core.jobs import (
    CancelToken,
    JobSpec,
    RuntimeCredentials,
    SerializedJobRunner,
)
from pagedrop.core.jobs.errors import SourceOverwriteError
from pagedrop.core.jobs.paths import paths_refer_to_same_file, reject_source_overwrite
from pagedrop.core.pdf_loader import (
    PdfEmptyError,
    PdfLoadError,
    PdfPasswordError,
    PdfPasswordRequiredError,
)
from pagedrop.ui.actions import ActionRegistry
from pagedrop.ui.busy_overlay import BusyOverlay, ToastOverlay
from pagedrop.ui.editor_jobs import (
    EditorJobWorker,
    release_editor_signals,
    start_editor_worker,
)
from pagedrop.ui.command_palette import CommandPalette, action_label
from pagedrop.utils.page_jump import format_indices_as_ranges
from pagedrop.ui.dialogs import (
    ask_named_confirmation,
    fit_message_box_buttons,
    prompt_pdf_password,
    prompt_redaction_scope,
    prompt_unsaved_changes,
)
from pagedrop.ui.keyboard_nav import (
    enable_toolbar_keyboard_navigation,
    set_content_tab_order,
    text_input_has_focus,
)
from pagedrop.ui.onboarding import (
    KeyboardShortcutsDialog,
    TipsOverlay,
    show_context_hint,
)
from pagedrop.ui.pdf_tab import PANE_DOCUMENT, PANE_SECTIONS, PdfTab
from pagedrop.ui.recovery import RecoveryError, draft_owner_pid, recovery_directory
from pagedrop.ui.accessibility import apply_appearance
from pagedrop.ui import icons, native_frame
from pagedrop.ui.settings import (
    chrome_visible,
    confirm_before_closing_dirty_tabs,
    document_panel_visible,
    has_seen_tips,
    last_directory,
    appearance,
    load_window_geometry,
    recent_files,
    remember_directory,
    remember_recent_file,
    save_window_geometry,
    sections_visible,
    settings_file_path,
    set_thumbnail_quality,
    set_thumbnail_zoom,
    KEY_CONTEXT_HINT_BACK_TO_GRID,
    KEY_CONTEXT_HINT_SELECTION_EXPORT,
    KEY_CONTEXT_HINT_TRANSFER,
    thumbnail_quality,
    thumbnail_zoom,
)
from pagedrop.ui.tab_manager import TabManager
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    ICON_SIZE,
    MAX_THUMBNAIL_WIDTH,
    MIN_THUMBNAIL_WIDTH,
    ZOOM_WHEEL_STEP,
    current_theme,
    tabular_font,
)
from pagedrop.ui.view_switch import ViewSwitch
from pagedrop.ui.window_chrome import (  # noqa: F401
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    RESIZE_MARGIN,
    WindowChromeMixin,
    cursor_for_edges,
    resize_edges_at,
)
from pagedrop.ui.zoom_controls import ZoomControls
from pagedrop.utils.page_jump import parse_page_ranges
from pagedrop.utils.temp_manager import TempManager, process_is_alive

if TYPE_CHECKING:
    from collections.abc import Callable

    from pagedrop.ui.convert_window import ConvertWindow
    from pagedrop.ui.merge_window import MergeWindow
    from pagedrop.ui.tools_window import ToolsWindow
    from pagedrop.ui.window_manager import WindowManager

from pagedrop.utils.diagnostics import log_failure


MOVE_UNDO_TIMEOUT_MS = 8000
STATUS_TRANSIENT_MS = 5000
COMPACT_STATUS_WIDTH = 640


def _is_file(path: Path) -> bool:
    """Whether *path* is a file; a path that cannot be read counts as missing."""
    try:
        return path.is_file()
    except (OSError, RuntimeError, ValueError):
        return False


class MainWindow(WindowChromeMixin, QMainWindow):
    APP_TITLE = "PageDrop"
    editor_job_finished = pyqtSignal(object)

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
        self._previous_tab: QWidget | None = None
        self._last_tab: QWidget | None = None
        self._pending_move_undo: Callable[[], bool] | None = None
        self._pending_selection: set[int] | None = None
        self._last_selection_toolbar_snap: tuple | None = None
        self._selection_coalesce_timer = QTimer(self)
        self._selection_coalesce_timer.setSingleShot(True)
        self._selection_coalesce_timer.setInterval(0)
        self._selection_coalesce_timer.timeout.connect(self._flush_selection_toolbar)
        self._status_by_page: dict[QWidget | None, str] = {}
        self._transient_status_timer = QTimer(self)
        self._transient_status_timer.setSingleShot(True)
        self._transient_status_timer.timeout.connect(self._restore_active_status)
        self._updating_responsive_shell = False
        self._title_press_pos: QPoint | None = None
        self._window_drag_offset: QPoint | None = None
        self._edge_cursor_active = False
        self._edge_resize: tuple[Qt.Edge, QPoint, QRect] | None = None
        self._native_frame_checked = False
        self._native_frame_failed = False
        self._native_event_error_logged = False
        self._key_filter_widget: QWidget | None = None

        self.setWindowTitle(self.APP_TITLE)
        # Offscreen Qt has no window manager and does not support custom chrome.
        # Desktop Windows/Linux use the frameless title bar below.
        if QApplication.platformName() == "offscreen":
            # Direct test windows otherwise survive until SIP interpreter teardown.
            QApplication.instance().aboutToQuit.connect(self.deleteLater)
        else:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(960, 680)
        # The whole window takes a drop while the active tab is on its start screen.
        self.setAcceptDrops(True)

        self._tab_order_applied = False
        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_status_widgets()
        self._build_central_widget()
        self._set_chrome_visible(chrome_visible(), persist=False)
        refresh_cb = self._refresh_action_icons
        icons.register_refresh(refresh_cb)
        self._install_scoped_event_filters()
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
            icon=icons.icon("floppy-disk"),
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
        self._appearance_group = QActionGroup(self)
        self._appearance_group.setExclusive(True)
        self._appearance_actions: dict[str, QAction] = {}
        for choice, label in (
            ("system", "&System appearance"),
            ("light", "&Light appearance"),
            ("dark", "&Dark appearance"),
        ):
            action = actions.register(
                f"appearance_{choice}",
                label,
                checkable=True,
                checked=appearance() == choice,
                data=choice,
            )
            self._appearance_group.addAction(action)
            self._appearance_actions[choice] = action
        self._appearance_group.triggered.connect(
            lambda action: apply_appearance(str(action.data()))
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
        self._pane_actions = {
            PANE_SECTIONS: actions.register(
                "toggle_sections",
                "Show &sections",
                slot=lambda visible: self._on_pane_toggled(PANE_SECTIONS, visible),
                shortcut="Ctrl+Shift+B",
                checkable=True,
                checked=sections_visible(),
                icon=icons.icon(
                    "sidebar-left-fill" if sections_visible() else "sidebar-left"
                ),
                tip="Show or hide sections (Ctrl+Shift+B)",
                enabled=False,
                add_to_window=True,
            ),
            PANE_DOCUMENT: actions.register(
                "toggle_document_panel",
                "Show &document panel",
                slot=lambda visible: self._on_pane_toggled(PANE_DOCUMENT, visible),
                shortcut="Ctrl+Shift+I",
                checkable=True,
                checked=document_panel_visible(),
                icon=icons.icon(
                    "sidebar-right-fill" if document_panel_visible() else "sidebar-right"
                ),
                tip="Show or hide the document panel (Ctrl+Shift+I)",
                enabled=False,
                add_to_window=True,
            ),
        }
        # Accessible name of each sidebar toggle's toolbar button, kept by _sync_pane_actions.
        self._pane_names: dict[str, str] = {}
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
            "All &tools",
            slot=self._open_tools_window,
            # Ctrl+T is New tab — use a dedicated chord for Tools.
            shortcut="Ctrl+Shift+O",
            icon=icons.icon("wrench"),
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
            "check_for_updates",
            "Check for &updates…",
            slot=self._check_for_updates,
        )
        actions.register("about", "&About PageDrop", slot=self._show_about)
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
            "Clear selection",
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
            "Delete selected pages",
            slot=self._delete_selected_pages,
            shortcut=QKeySequence(Qt.Key.Key_Delete),
            icon=icons.icon("trash"),
            tip="Delete selected pages (Delete)",
            enabled=False,
        )
        self._duplicate_pages_action = actions.register(
            "duplicate_pages",
            "Duplicate selected pages",
            slot=self._duplicate_selected_pages,
            shortcut="Ctrl+D",
            icon=icons.icon("copy"),
            tip="Duplicate selected pages (Ctrl+D)",
            enabled=False,
        )
        self._rotate_cw_action = actions.register(
            "rotate_cw",
            "Rotate right",
            slot=lambda: self._rotate_selected_pages(90),
            icon=icons.icon("arrow-clockwise"),
            tip="Rotate selected pages clockwise",
            enabled=False,
        )
        self._rotate_ccw_action = actions.register(
            "rotate_ccw",
            "Rotate left",
            slot=lambda: self._rotate_selected_pages(-90),
            icon=icons.icon("arrow-counter-clockwise"),
            tip="Rotate selected pages counter-clockwise",
            enabled=False,
        )
        self._extract_selected_action = actions.register(
            "extract_selected",
            "Extract",
            slot=self._extract_selected_to_folder,
            icon=icons.icon("export"),
            tip="Extract selected pages to a folder",
            enabled=False,
        )
        self._extract_selected_to_tab_action = actions.register(
            "extract_selected_to_tab",
            "Extract selected pages to new tab",
            slot=self._extract_selected_to_new_tab,
            enabled=False,
        )
        self._extract_selected_to_window_action = actions.register(
            "extract_selected_to_window",
            "Extract selected pages to new window",
            slot=self._extract_selected_to_new_window,
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
            "Select pages",
            slot=self._page_range_jump_dialog,
            tip="Select pages by number or range",
            add_to_window=True,
        )
        actions.register(
            "reset_zoom",
            "Reset zoom",
            slot=self._reset_zoom,
            shortcut="Ctrl+0",
            add_to_window=True,
        )
        # The command bar shows these short names; menus and the palette keep the
        # full text, and each button's accessible name is that full text, which
        # contains the visible label.
        for key, short in (
            ("open", "Open"),
            ("save_as", "Save as"),
            ("duplicate_pages", "Duplicate"),
            ("extract_selected", "Extract"),
            ("delete_pages", "Delete"),
            ("tools", "Tools"),
        ):
            actions[key].setIconText(short)
        categories = {
            "Pages": {
                "undo", "redo", "preview", "select_all", "deselect_all",
                "move_up", "move_down", "move_to", "delete_pages",
                "duplicate_pages", "rotate_cw", "rotate_ccw", "extract_selected",
                "extract_selected_to_tab", "extract_selected_to_window", "go_to_page",
                "page_jump",
            },
            "View": {
                "appearance_system", "appearance_light", "appearance_dark",
                "chrome_visible", "toggle_sections", "toggle_document_panel",
                "quality_low", "quality_medium",
                "quality_high", "command_palette", "reset_zoom",
            },
            "Tools": {"merge", "create_pdf", "tools"},
        }
        synonyms = {
            "merge": ["combine"],
            "create_pdf": ["images to pdf"],
            "rotate_ccw": ["counterclockwise"],
            "rotate_cw": ["clockwise"],
        }
        for key, action in actions.items():
            action.setProperty(
                "commandCategory",
                next((name for name, keys in categories.items() if key in keys), "Document"),
            )
            if key in synonyms:
                action.setProperty("commandSynonyms", synonyms[key])

    def _refresh_action_icons(self) -> None:
        """Re-tint Phosphor toolbar icons after a light/dark swap."""
        a = self._actions
        a["open"].setIcon(icons.icon("folder-open"))
        a["save_as"].setIcon(icons.icon("floppy-disk"))
        a["preview"].setIcon(icons.icon("list"))
        a["tools"].setIcon(icons.icon("wrench"))
        a["select_all"].setIcon(icons.icon("selection-all"))
        a["deselect_all"].setIcon(icons.icon("selection-slash"))
        a["move_up"].setIcon(icons.icon("arrow-up"))
        a["move_down"].setIcon(icons.icon("arrow-down"))
        a["move_to"].setIcon(icons.icon("arrows-down-up"))
        a["delete_pages"].setIcon(icons.icon("trash"))
        a["duplicate_pages"].setIcon(icons.icon("copy"))
        a["rotate_cw"].setIcon(icons.icon("arrow-clockwise"))
        a["rotate_ccw"].setIcon(icons.icon("arrow-counter-clockwise"))
        a["extract_selected"].setIcon(icons.icon("export"))
        self._sync_pane_actions()
        self._set_toolbar_primary()
        self._refresh_window_control_icons()

    def menuBar(self) -> QMenuBar:  # noqa: N802
        # The menu bar lives inside the title bar; the base implementation
        # would install a second, empty menu bar over it.
        return self._menu_bar

    def _build_menu(self) -> None:
        self._build_title_bar()
        menubar = self._menu_bar
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
        edit_menu.addAction(a["page_jump"])
        edit_menu.addSeparator()
        edit_menu.addAction(a["preferences"])

        view_menu = menubar.addMenu("&View")
        view_menu.addAction(a["preview"])
        view_menu.addSeparator()
        appearance_menu = view_menu.addMenu("&Appearance")
        for key in ("appearance_system", "appearance_light", "appearance_dark"):
            appearance_menu.addAction(a[key])
        view_menu.addAction(a["chrome_visible"])
        view_menu.addAction(a["toggle_sections"])
        view_menu.addAction(a["toggle_document_panel"])
        quality_menu = view_menu.addMenu("Thumbnail &quality")
        for key in ("quality_low", "quality_medium", "quality_high"):
            quality_menu.addAction(a[key])
        view_menu.addSeparator()
        view_menu.addAction(a["command_palette"])

        pages_menu = menubar.addMenu("&Pages")
        for key in (
            "select_all",
            "deselect_all",
            None,
            "rotate_ccw",
            "rotate_cw",
            "duplicate_pages",
            "extract_selected",
            "extract_selected_to_tab",
            "extract_selected_to_window",
            "delete_pages",
            None,
            "move_up",
            "move_down",
            "move_to",
        ):
            if key is None:
                pages_menu.addSeparator()
            else:
                pages_menu.addAction(a[key])
        self._pages_menu_action = pages_menu.menuAction()

        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction(a["merge"])
        tools_menu.addAction(a["create_pdf"])
        tools_menu.addSeparator()
        tools_menu.addAction(a["tools"])
        self._tools_menu_action = tools_menu.menuAction()

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(a["keyboard_shortcuts"])
        help_menu.addAction(a["tips"])
        help_menu.addSeparator()
        help_menu.addAction(a["check_for_updates"])
        help_menu.addAction(a["about"])
        self._help_menu_action = help_menu.menuAction()

        self._application_overflow_menu = menubar.addMenu("M&ore")
        self._application_overflow_menu.setToolTip("More application actions")
        self._application_overflow_menu.setAccessibleName("More application actions")
        self._responsive_menu_actions = (
            # Keep File direct; at large fonts even File/Edit/View/More plus
            # the window controls may not fit. Move View and Edit last.
            edit_menu.menuAction(),
            view_menu.menuAction(),
            self._pages_menu_action,
            self._tools_menu_action,
            self._help_menu_action,
        )
        self._application_overflow_menu.menuAction().setVisible(False)

        for menu in (
            file_menu,
            self._open_recent_menu,
            edit_menu,
            view_menu,
            quality_menu,
            pages_menu,
            tools_menu,
            help_menu,
            self._application_overflow_menu,
        ):
            self._install_menu_focus_restore(menu)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._toolbar = toolbar
        self._toolbar_host_tab: PdfTab | None = None
        a = self._actions

        toolbar.addAction(a["toggle_sections"])
        toolbar.addAction(a["open"])
        # Offscreen Qt needs a widget action here to tear down this reparented
        # toolbar safely. It is intentionally zero-width, not document chrome.
        self._toolbar_layout_anchor = QWidget(toolbar)
        self._toolbar_layout_anchor.setFixedWidth(0)
        self._toolbar_anchor_action = toolbar.addWidget(self._toolbar_layout_anchor)
        # Hidden, so it costs no spacing gap: it only has to exist as an action.
        self._toolbar_anchor_action.setVisible(False)
        toolbar.addAction(a["save_as"])
        separators = [toolbar.addSeparator()]
        self._selection_toolbar_label = QLabel()
        self._selection_toolbar_label.setObjectName("ToolbarSelectionCount")
        self._selection_toolbar_label.setFont(tabular_font())
        self._selection_toolbar_label.setFixedWidth(180)
        self._selection_toolbar_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._selection_toolbar_action = toolbar.addWidget(self._selection_toolbar_label)
        toolbar.addAction(a["rotate_ccw"])
        toolbar.addAction(a["rotate_cw"])
        toolbar.addAction(a["duplicate_pages"])
        toolbar.addAction(a["extract_selected"])
        separators.append(toolbar.addSeparator())
        toolbar.addAction(a["delete_pages"])

        # Takes the slack, so the view group sits at the right edge.
        self._toolbar_spacer = QWidget(toolbar)
        self._toolbar_spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._toolbar_spacer_action = toolbar.addWidget(self._toolbar_spacer)
        self._view_switch = ViewSwitch(a["preview"], toolbar)
        self._view_switch_action = toolbar.addWidget(self._view_switch)
        toolbar.addAction(a["tools"])

        self._zoom_controls = ZoomControls(
            min_width=MIN_THUMBNAIL_WIDTH,
            max_width=MAX_THUMBNAIL_WIDTH,
            step=ZOOM_WHEEL_STEP,
            initial=thumbnail_zoom(),
        )
        self._zoom_controls.zoom_requested.connect(self._on_zoom_requested)
        self._zoom_controls.reset_requested.connect(self._reset_thumbnail_zoom)
        zoom_hint = "Thumbnail size (Ctrl+scroll · Ctrl+0 reset)"
        self._zoom_controls.setToolTip(zoom_hint)
        self._zoom_controls.setStatusTip(zoom_hint)

        self._toolbar_overflow = QToolButton(toolbar)
        self._toolbar_overflow.setObjectName("ToolbarOverflow")
        self._toolbar_overflow.setText("More")
        self._toolbar_overflow.setToolTip("More page actions")
        self._toolbar_overflow.setAccessibleName("More page actions")
        self._toolbar_overflow.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._toolbar_overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._toolbar_overflow_menu = QMenu(self._toolbar_overflow)
        self._install_menu_focus_restore(self._toolbar_overflow_menu)
        self._toolbar_overflow.setMenu(self._toolbar_overflow_menu)
        self._toolbar_overflow_action = toolbar.addWidget(self._toolbar_overflow)
        toolbar.addAction(a["toggle_document_panel"])

        # Toolbar order, the separators this toolbar alone owns, and the commands
        # that give way to More (last to go first) when the bar is narrow.
        self._toolbar_order = tuple(toolbar.actions())
        self._toolbar_separators = tuple(separators)
        self._toolbar_displaceable = tuple(
            a[key]
            for key in (
                "rotate_ccw",
                "rotate_cw",
                "duplicate_pages",
                "extract_selected",
                "delete_pages",
                "preview",
                "tools",
            )
        )
        # The view switch stands in the bar for the registered preview action,
        # which is what More lists when the switch has no room.
        self._toolbar_slot = {a["preview"]: self._view_switch_action}
        # Labelled buttons, left to right. When the bar is narrow the labels go
        # from the right; Save as is primary, so it keeps its own.
        self._toolbar_label_actions = tuple(
            a[key]
            for key in (
                "open",
                "save_as",
                "rotate_ccw",
                "rotate_cw",
                "duplicate_pages",
                "extract_selected",
                "delete_pages",
                "tools",
            )
        )
        self._toolbar_label_droppable = tuple(
            action for action in self._toolbar_label_actions if action is not a["save_as"]
        )
        self._toolbar_icon_only: frozenset[QAction] = frozenset()
        self._toolbar_hint_widths: dict[QAction, int] = {}
        self._toolbar_icon_widths: dict[QAction, int] = {}
        self._fitting_toolbar = False
        self._style_toolbar_buttons()
        # A changed action makes its button reload the action's own icon.
        a["save_as"].changed.connect(self._set_toolbar_primary)

    def _style_toolbar_buttons(self) -> None:
        """Apply per-button presentation; run again for any re-created button."""
        self._apply_toolbar_label_style()
        self._style_sidebar_toggles()
        enable_toolbar_keyboard_navigation(self._toolbar)

    def _style_sidebar_toggles(self) -> None:
        """Mark the sidebar toggle buttons (state is the icon) and name them for screen readers."""
        for pane, action in self._pane_actions.items():
            button = self._toolbar.widgetForAction(action)
            if not isinstance(button, QToolButton):
                continue
            if button.objectName() != "ToolbarSidebarToggle":
                button.setObjectName("ToolbarSidebarToggle")
                button.style().unpolish(button)
                button.style().polish(button)
            if name := self._pane_names.get(pane):
                button.setAccessibleName(name)

    def _name_viewer_sidebar_toggles(self, tab: PdfTab) -> None:
        tab.preview_widget.set_sidebar_names(
            self._pane_names.get(PANE_SECTIONS, ""),
            self._pane_names.get(PANE_DOCUMENT, ""),
        )

    def _apply_toolbar_label_style(self) -> None:
        """Labels beside icons, except on buttons the bar has made icon-only.

        Dropping a label keeps the tooltip, and the accessible name is always
        the action's full text.
        """
        for action in self._toolbar_label_actions:
            button = self._toolbar.widgetForAction(action)
            if not isinstance(button, QToolButton):
                continue
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly
                if action in self._toolbar_icon_only
                else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            button.setAccessibleName(action.text().replace("&", ""))

    def _build_central_widget(self) -> None:
        self._recovery_dir = recovery_directory(settings_file_path())
        self._tab_manager = TabManager(
            temp_manager=self._temp_manager,
            recovery_dir=self._recovery_dir,
        )
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
        self._tab_manager.add_corner_widget(new_tab_button)

        if self._initial_tab is not None:
            self._adopt_tab(self._initial_tab)
        else:
            self._tab_manager.add_blank_tab()
            tab = self._tab_manager.active_tab
            if tab is not None:
                tab.set_zoom_level(thumbnail_zoom())
        self.setCentralWidget(self._tab_manager)
        self._toast = ToastOverlay(self._tab_manager)
        self._editor_runner = SerializedJobRunner(self._temp_manager)
        register_editor_handlers(self._editor_runner)
        self._editor_busy: dict[PdfTab, tuple[BusyOverlay, CancelToken]] = {}
        self._close_discarded: set[PdfTab] = set()
        self._close_waiting = False
        self._last_tab = self._tab_manager.currentWidget()
        self._apply_tab_order()
        self._tab_manager.currentChanged.connect(self._on_tab_order_stale)

    def _on_tab_order_stale(self, _index: int) -> None:
        self._apply_tab_order()

    def _apply_tab_order(self) -> None:
        set_content_tab_order(
            self._toolbar,
            self._tab_manager,
            status_bar=self.statusBar(),
            status_controls=(
                self._move_undo_button,
                *self._zoom_controls.focus_widgets(),
                # Last, so a newly activated window never lands on Minimize.
                self._chrome_toggle_btn,
                *self._window_control_buttons,
            ),
        )

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        self._attach_window_handle_filter()
        # Toolbar widgets only report visible once shown, so build the chain then.
        if not self._tab_order_applied:
            self._tab_order_applied = True
            self._apply_tab_order()
        if not self._native_frame_checked:
            self._native_frame_checked = True
            if self._uses_native_frame():
                try:
                    native_frame.apply_frame_styles(int(self.winId()))
                except (OSError, ctypes.ArgumentError) as exc:
                    # The window still shows; edge resizing falls back to Qt's.
                    self._native_frame_failed = True
                    log_failure("Apply native window frame", exc)

    def _status_page(self) -> QWidget | None:
        return self._tab_manager.currentWidget()

    def _sender_tab(self) -> PdfTab | None:
        sender = self.sender()
        for index in range(self._tab_manager.count()):
            tab = self._tab_manager.widget(index)
            if isinstance(tab, PdfTab) and sender in (tab.thumbnail_grid, tab.preview_widget):
                return tab
        return None

    def _transient_status(self, message: str, *, page: QWidget | None = None) -> None:
        page = page or self._sender_tab() or self._status_page()
        self._status_by_page[page] = message
        if page is self._status_page():
            self.statusBar().showMessage(message)
            self._transient_status_timer.start(STATUS_TRANSIENT_MS)

    def _persistent_status(self, message: str, *, page: QWidget | None = None) -> None:
        page = page or self._sender_tab() or self._status_page()
        self._status_by_page[page] = message
        if page is self._status_page():
            self._transient_status_timer.stop()
            self.statusBar().showMessage(message)

    def _restore_active_status(self) -> None:
        self.statusBar().showMessage(self._status_by_page.get(self._status_page(), "Ready"))

    def _show_toast(
        self,
        message: str,
        *,
        kind: str = "info",
        on_undo=None,
    ) -> None:
        self._toast.show_toast(message, kind=kind, on_undo=on_undo)

    def _begin_editor_job(self, tab: PdfTab, message: str) -> CancelToken:
        overlay = BusyOverlay(tab)
        overlay.set_cancellable(True)
        token = CancelToken()
        overlay.set_progress(None)

        def cancel() -> None:
            token.cancel()
            overlay.set_cancelling()
            if tab is self._active_tab():
                self._persistent_status("Cancelling…")

        overlay.cancelled.connect(cancel)
        overlay.show_message(message)
        tab.setProperty("editorJobRunning", True)
        self._editor_busy[tab] = (overlay, token)
        return token

    def _end_editor_job(self, tab: PdfTab) -> None:
        item = self._editor_busy.pop(tab, None)
        if item is not None:
            item[0].hide_overlay()
        tab.setProperty("editorJobRunning", False)
        self.editor_job_finished.emit(tab)

    def wait_for_editor_job(self, tab: PdfTab) -> None:
        """Run a nested event loop only for shutdown preparation's save contract."""
        if tab not in self._editor_busy:
            return
        loop = QEventLoop(self)

        def done(finished_tab: object) -> None:
            if finished_tab is tab:
                loop.quit()

        self.editor_job_finished.connect(done)
        try:
            if tab in self._editor_busy:
                loop.exec()
        finally:
            self.editor_job_finished.disconnect(done)

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
        self._restore_active_status()

    @staticmethod
    def _selection_summary(selection: set[int]) -> tuple[str, str]:
        """Return compact visible and complete accessible selection context."""
        ranges = format_indices_as_ranges(selection).replace("-", "–")
        count = len(selection)
        if "," not in ranges:
            noun = "Page" if count == 1 else "Pages"
            summary = f"{noun} {ranges} selected"
            return summary, summary
        summary = f"{count} pages selected"
        return summary, f"{summary}: Pages {ranges.replace(',', ', ')}"

    def _build_status_widgets(self) -> None:
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._progress_bar.setAccessibleName("Page rendering progress")
        self._progress_bar.hide()

        self._thumbnail_zoom_host = QWidget()
        self._thumbnail_zoom_host.setObjectName("ThumbnailZoomStatusHost")
        zoom_layout = QHBoxLayout(self._thumbnail_zoom_host)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(4)
        self._thumbnail_zoom_label = QLabel("Thumbnail size")
        self._thumbnail_zoom_label.setObjectName("ThumbnailZoomLabel")
        zoom_layout.addWidget(self._thumbnail_zoom_label)
        zoom_layout.addWidget(self._zoom_controls)
        self._thumbnail_zoom_host.hide()

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

        self.statusBar().setFont(tabular_font())
        self.statusBar().addPermanentWidget(self._move_undo_widget)
        self.statusBar().addPermanentWidget(self._progress_bar)
        self.statusBar().addPermanentWidget(self._thumbnail_zoom_host)
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
        grid.pages_copied_not_moved.connect(self._on_pages_copied_not_moved)
        grid.pdf_drop_failed.connect(self._on_pdf_drop_failed)
        grid.extract_to_folder_requested.connect(self._extract_selected_to_folder)
        grid.bind_page_actions(
            (self._select_all_action, self._deselect_all_action),
            (self._move_up_action, self._move_down_action, self._move_to_action),
            (
                self._duplicate_pages_action,
                self._rotate_cw_action,
                self._rotate_ccw_action,
            ),
            (self._delete_pages_action,),
            (self._page_jump_action,),
            (
                self._extract_selected_action,
                self._extract_selected_to_tab_action,
                self._extract_selected_to_window_action,
            ),
        )
        grid.open_pdfs_requested.connect(self._on_open_pdfs_requested)
        grid.bind_open_action(self._actions["open"])
        tab.start_screen.bind_actions(
            self._actions["open"], self._actions["merge"], self._actions["tools"]
        )
        tab.preview_widget.set_sidebar_actions(
            self._pane_actions[PANE_SECTIONS], self._pane_actions[PANE_DOCUMENT]
        )
        self._name_viewer_sidebar_toggles(tab)
        tab.start_screen.recent_file_requested.connect(self._open_recent_if_present)
        tab.pdf_loaded.connect(self._on_tab_pdf_loaded)
        tab.workspace_panes_changed.connect(self._on_workspace_panes_changed)
        tab.preview_widget.page_changed.connect(self._on_preview_page_changed)
        tab.preview_widget.busy_changed.connect(self._on_preview_busy_changed)
        tab.preview_widget.render_error.connect(self._on_preview_render_error)
        tab.preview_widget.closed.connect(self._on_viewer_closed)
        tab.preview_widget.status_message.connect(self._transient_status)
        tab.preview_widget.ocr_requested.connect(self._open_ocr_from_viewer)
        tab.dirty_changed.connect(self._on_tab_dirty_changed)
        tab.recovery_failed.connect(self._on_recovery_failed)

    def _on_recovery_failed(self, message: str) -> None:
        self._transient_status("Draft recovery unavailable")
        self._show_toast(message, kind="error")

    def restore_recovery_drafts(self) -> int:
        """Offer stale crash drafts and restore accepted documents as tabs."""
        try:
            drafts = [
                path
                for path in sorted(self._recovery_dir.glob("*.json"))
                if (owner := draft_owner_pid(path)) is None
                or not process_is_alive(owner)
            ]
        except OSError:
            return 0
        if not drafts:
            return 0
        recover = ask_named_confirmation(
            self,
            title="Recover unsaved changes",
            text=(
                f"PageDrop found unsaved changes from an earlier session "
                f"({len(drafts)} {'document' if len(drafts) == 1 else 'documents'}). "
                "Recover them now?"
            ),
            action="Recover",
            decline="Discard",
            default_action=True,
        )
        if not recover:
            for path in drafts:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            return 0

        restored = 0
        failures: list[str] = []
        for path in drafts:
            tab = self._tab_manager.active_tab
            if tab is None or not tab.is_blank or restored:
                tab = self._tab_manager.add_blank_tab()
            try:
                tab.restore_recovery_draft(
                    path,
                    lambda source, incorrect: self._prompt_pdf_password(
                        Path(source).name, incorrect=incorrect
                    ),
                )
            except (RecoveryError, PdfLoadError, OSError) as exc:
                failures.append(str(exc))
                if tab.is_blank and self._tab_manager.count() > 1:
                    self._tab_manager.close_tab(self._tab_manager.indexOf(tab))
                continue
            tab.set_zoom_level(thumbnail_zoom())
            self._tab_manager.setCurrentWidget(tab)
            restored += 1
        if restored:
            message = (
                "Recovered 1 unsaved document"
                if restored == 1
                else f"Recovered {restored} unsaved documents"
            )
            self._transient_status(message)
            self._show_toast(message, kind="success")
        if failures:
            QMessageBox.warning(
                self,
                "Recovery incomplete",
                "Some drafts could not be recovered:\n" + "\n".join(failures),
            )
        return restored

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
            (grid.pages_copied_not_moved, self._on_pages_copied_not_moved),
            (grid.pdf_drop_failed, self._on_pdf_drop_failed),
            (grid.extract_to_folder_requested, self._extract_selected_to_folder),
            (grid.open_pdfs_requested, self._on_open_pdfs_requested),
            (tab.start_screen.recent_file_requested, self._open_recent_if_present),
            (tab.pdf_loaded, self._on_tab_pdf_loaded),
            (tab.workspace_panes_changed, self._on_workspace_panes_changed),
            (preview.page_changed, self._on_preview_page_changed),
            (preview.busy_changed, self._on_preview_busy_changed),
            (preview.render_error, self._on_preview_render_error),
            (preview.closed, self._on_viewer_closed),
            (preview.status_message, self._transient_status),
            (preview.ocr_requested, self._open_ocr_from_viewer),
            (tab.dirty_changed, self._on_tab_dirty_changed),
            (tab.recovery_failed, self._on_recovery_failed),
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
            self._set_toolbar_primary()

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
        # The source window deletes its temp root on close; this tab's drags
        # and exports must live under ours.
        if tab._temp_manager is not self._temp_manager:
            tab.set_temp_manager(self._temp_manager)
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

        if tab in self._editor_busy:
            self._transient_status("Wait for the running task to finish before moving")
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
        current = self._tab_manager.widget(index)
        if self._tab_manager.count() <= 1:
            self._previous_tab = None
            self._last_tab = current
            return
        if self._last_tab is None:
            self._last_tab = current
            return
        if self._last_tab is not current:
            self._previous_tab = self._last_tab
        self._last_tab = current
        self._sync_toolbar_from_active_tab()

    def _on_tab_closed(self, closed_index: int) -> None:
        # Emitted before the tab leaves the manager (close or move to another window).
        closed = self._tab_manager.widget(closed_index)
        if closed is not None and closed is self._previous_tab:
            self._previous_tab = None
        if closed is not None and closed is self._last_tab:
            self._last_tab = None
        self._update_close_tab_action()

    def _switch_to_next_tab(self) -> None:
        if self._tab_manager.count() <= 1 or self._previous_tab is None:
            return
        previous = self._tab_manager.indexOf(self._previous_tab)
        if previous < 0 or previous == self._tab_manager.currentIndex():
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

    def _on_pane_toggled(self, pane: str, visible: bool) -> None:
        tab = self._active_tab()
        if tab is not None:
            tab.set_workspace_pane_visible(pane, visible)

    def _on_workspace_panes_changed(self) -> None:
        if self.sender() is self._active_tab():
            self._sync_pane_actions()

    def _sync_pane_actions(self) -> None:
        """Enable the sidebar toggles for a document and show the real sidebar state.

        Checked means open. The text, hint and icon name the sidebar of the
        active view: sections and document panel in the grid, navigation and
        markup tools in the viewer.
        """
        tab = self._active_tab()
        has_document = tab is not None and not tab.is_blank
        for pane, action in self._pane_actions.items():
            action.setEnabled(has_document)
            if tab is None:
                continue
            left = pane == PANE_SECTIONS
            if has_document:
                checked = tab.workspace_pane_visible(pane)
                noun = tab.workspace_pane_label(pane)
            else:
                checked = sections_visible() if left else document_panel_visible()
                noun = "sections" if left else "document panel"
            if action.isChecked() != checked:
                action.blockSignals(True)
                action.setChecked(checked)
                action.blockSignals(False)
            name = f"{'Hide' if checked else 'Show'} {noun}"
            hint = f"{name} ({action.shortcut().toString()})"
            if has_document and not left and not checked and tab.is_viewer_mode():
                if tool := tab.preview_widget.active_markup_label():
                    hint += f" — active: {tool}"
            action.setText(f"Show &{noun}")
            self._set_action_hint(action, hint)
            side = "left" if left else "right"
            action.setIcon(icons.icon(f"sidebar-{side}-fill" if checked else f"sidebar-{side}"))
            self._pane_names[pane] = name
        self._style_sidebar_toggles()
        if tab is not None:
            self._name_viewer_sidebar_toggles(tab)
        # The toggles live on this bar in the grid and on the viewer's own in
        # Pages view; refit whenever the view changed under them.
        on_bar = set(self._toolbar.actions())
        owned = self._viewer_owned_toolbar_actions()
        if any((a in on_bar) == (a in owned) for a in self._pane_actions.values()):
            self._refit_toolbar()

    def _sync_toolbar_from_active_tab(self) -> None:
        tab = self._active_tab()
        self._sync_pane_actions()
        self._set_toolbar_host(tab)
        if tab is None:
            self._reset_toolbar_for_tool_page()
            return
        if tab.is_blank:
            self._reset_toolbar_for_blank_tab()
            return

        self._update_window_title()
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
        self._update_thumbnail_zoom_host()
        self._update_preview_mode_ui()
        self._update_close_tab_action()
        self._update_save_as_action()
        selection = tab.thumbnail_grid.selection_manager.selection
        self._pending_selection = selection
        self._last_selection_toolbar_snap = self._selection_toolbar_snapshot(
            selection
        )
        self._sync_contextual_toolbar(selection)

    def _set_toolbar_host(self, tab: PdfTab | None) -> None:
        if self._toolbar_host_tab is tab:
            self._toolbar.setVisible(tab is not None)
            return
        if self._toolbar_host_tab is not None:
            self._toolbar_host_tab.detach_context_toolbar(self._toolbar)
        self._toolbar_host_tab = tab
        if tab is not None:
            tab.attach_context_toolbar(self._toolbar)

    def _sync_contextual_toolbar(self, selection: set[int]) -> None:
        # Page commands stay on the bar and are enabled by their own actions, so
        # nothing appears or disappears when the selection changes.
        has_selection = bool(selection)
        if has_selection:
            visible, accessible = self._selection_summary(selection)
        else:
            visible = accessible = "No selection"
        self._selection_toolbar_label.setText(visible)
        self._selection_toolbar_label.setToolTip(accessible if has_selection else "")
        self._selection_toolbar_label.setAccessibleName(accessible)
        self._selection_toolbar_label.setVisible(self._selection_toolbar_action.isVisible())
        self._sync_toolbar_overflow(has_selection)
        self._set_toolbar_primary()

    def _sync_toolbar_overflow(self, has_selection: bool) -> None:
        """Project commands that have no room on the toolbar into More."""
        menu = self._toolbar_overflow_menu
        menu.clear()
        static: list[QAction] = []
        if self._export_all_action.isEnabled():
            static.append(self._export_all_action)
        if has_selection and self._move_to_action.isEnabled():
            static.append(self._move_to_action)
        displaced = self._fit_toolbar(bool(static))
        menu.addActions(displaced)
        if displaced and static:
            menu.addSeparator()
        menu.addActions(static)
        shown = bool(menu.actions())
        self._toolbar_overflow_action.setVisible(shown)
        self._toolbar_overflow.setVisible(shown)

    def _fit_toolbar(self, static_overflow: bool) -> list[QAction]:
        """Trim the toolbar to its width; return the actions that left it.

        Labels go first, from the right (Save as keeps its own). Once every
        label is gone, commands move to More from the right. The selection cell
        is the last thing to leave, because the count is shown nowhere else.
        Qt's own extension button is only reachable by mouse, so the bar must
        never overflow. Displaced actions stay visible (menus and
        shortcuts share them); they just stop being toolbar buttons until there
        is room again.
        """
        toolbar = self._toolbar
        tab = self._active_tab()
        order = self._toolbar_order
        if self._fitting_toolbar:
            return []
        if not toolbar.isVisible() or tab is None or tab.is_blank:
            self._show_all_toolbar_items()
            return []
        self._measure_toolbar_buttons()
        measured = self._toolbar_hint_widths
        viewer_owned = self._viewer_owned_toolbar_actions()
        if any(
            a not in measured
            and a not in self._toolbar_separators
            and a not in viewer_owned
            for a in order
        ) or any(a not in self._toolbar_icon_widths for a in self._toolbar_label_droppable):
            # Not measured while present (e.g. after a font change): measure all.
            self._show_all_toolbar_items()
            return self._fit_toolbar(static_overflow)

        available = toolbar.width()
        removed = set(viewer_owned)
        displaced: list[QAction] = []
        droppable = list(reversed(self._toolbar_label_droppable))
        icon_only: set[QAction] = set()
        members = self._toolbar_members(removed, static_overflow)
        while self._toolbar_width_for(members, icon_only) > available and droppable:
            icon_only.add(droppable.pop(0))
        candidates = [*reversed(self._toolbar_displaceable), self._selection_toolbar_action]
        while self._toolbar_width_for(members, icon_only) > available and candidates:
            action = candidates.pop(0)
            removed.add(self._toolbar_slot.get(action, action))
            if action is not self._selection_toolbar_action:
                displaced.insert(0, action)
            members = self._toolbar_members(removed, bool(displaced) or static_overflow)
        self._toolbar_icon_only = frozenset(icon_only)
        self._apply_toolbar_members(members)
        self._apply_toolbar_label_style()
        return displaced

    def _viewer_owned_toolbar_actions(self) -> set[QAction]:
        """Sidebar toggles the viewer's own bar shows in Pages view.

        They leave the toolbar by being removed from it, never hidden, so
        their shortcuts keep working.
        """
        tab = self._active_tab()
        if tab is not None and tab.is_viewer_mode():
            return set(self._pane_actions.values())
        return set()

    def _show_all_toolbar_items(self) -> None:
        self._toolbar_icon_only = frozenset()
        self._apply_toolbar_members(
            set(self._toolbar_order) - self._viewer_owned_toolbar_actions()
        )
        self._apply_toolbar_label_style()

    def _measure_toolbar_buttons(self) -> None:
        """Record each present button's width with and without its label."""
        measured = self._toolbar_hint_widths
        icon_widths = self._toolbar_icon_widths
        for action in self._toolbar_order:
            widget = self._toolbar.widgetForAction(action)
            if widget is None:
                continue
            if action in self._toolbar_label_droppable and isinstance(widget, QToolButton):
                current = widget.toolButtonStyle()
                widget.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                measured[action] = max(0, widget.sizeHint().width())
                widget.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                icon_widths[action] = max(0, widget.sizeHint().width())
                widget.setToolButtonStyle(current)
            else:
                measured[action] = max(0, widget.sizeHint().width())

    def _toolbar_members(self, removed: set[QAction], more_needed: bool) -> set[QAction]:
        """Toolbar actions left after *removed*, with no stranded separators."""
        separators = set(self._toolbar_separators)
        spacer = self._toolbar_spacer_action
        more = self._toolbar_overflow_action
        anchor = self._toolbar_anchor_action
        items = [
            a
            for a in self._toolbar_order
            if a not in removed and a is not anchor and (a is not more or more_needed)
        ]
        # Separators only divide the groups left of the spacer; the view group
        # on the right has none.
        left_end = items.index(spacer)
        members: set[QAction] = set()
        have_item = False
        for index, action in enumerate(items):
            if action is spacer:
                members.add(action)
            elif action not in separators:
                members.add(action)
                have_item = True
            elif have_item and any(
                a not in separators for a in items[index + 1 : left_end]
            ):
                members.add(action)
                have_item = False
        return members

    def _toolbar_width_for(
        self, members: set[QAction], icon_only: set[QAction] | frozenset[QAction] = frozenset()
    ) -> int:
        style = self._toolbar.style()
        metric = QStyle.PixelMetric
        gap = style.pixelMetric(metric.PM_ToolBarItemSpacing, None, self._toolbar)
        margin = 2 * (
            style.pixelMetric(metric.PM_ToolBarFrameWidth, None, self._toolbar)
            + style.pixelMetric(metric.PM_ToolBarItemMargin, None, self._toolbar)
        )
        separator = style.pixelMetric(
            metric.PM_ToolBarSeparatorExtent, None, self._toolbar
        )
        widths = [
            separator
            if a in self._toolbar_separators
            else self._toolbar_icon_widths[a]
            if a in icon_only
            else self._toolbar_hint_widths[a]
            for a in self._toolbar_order
            if a in members
        ]
        return margin + sum(widths) + gap * max(0, len(widths) - 1)

    def _apply_toolbar_members(self, members: set[QAction]) -> None:
        """Make the toolbar hold exactly *members*, in toolbar order."""
        toolbar = self._toolbar
        own = {
            *self._toolbar_separators,
            self._selection_toolbar_action,
            self._toolbar_overflow_action,
            self._toolbar_anchor_action,
            self._toolbar_spacer_action,
            self._view_switch_action,
        }
        order = self._toolbar_order
        focus = QApplication.focusWidget()
        focus_lost = False
        rebuilt = False
        self._fitting_toolbar = True
        try:
            for index, action in enumerate(order):
                want = action in members
                if action in own:
                    action.setVisible(want)
                    if not want and action is self._view_switch_action:
                        focus_lost = focus_lost or (
                            focus is not None and self._view_switch.isAncestorOf(focus)
                        )
                elif want and action not in toolbar.actions():
                    present = toolbar.actions()
                    toolbar.insertAction(
                        next((b for b in order[index + 1 :] if b in present), None),
                        action,
                    )
                    rebuilt = True
                elif not want and action in toolbar.actions():
                    widget = toolbar.widgetForAction(action)
                    focus_lost = focus_lost or (
                        widget is not None and widget is focus
                    )
                    toolbar.removeAction(action)
                    rebuilt = True
            if rebuilt:
                self._style_toolbar_buttons()
                if self._tab_order_applied:
                    self._apply_tab_order()
            if focus_lost:
                self._toolbar_overflow.setFocus(Qt.FocusReason.OtherFocusReason)
        finally:
            self._fitting_toolbar = False

    def _refit_toolbar(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.is_blank or self._fitting_toolbar:
            return
        self._sync_toolbar_overflow(bool(tab.thumbnail_grid.selection_manager.selection))

    def _install_menu_focus_restore(self, menu: QMenu) -> None:
        """Return keyboard focus to the control that opened a transient menu."""
        menu.aboutToShow.connect(
            lambda: setattr(menu, "_pagedrop_focus_target", QApplication.focusWidget())
        )
        menu.aboutToHide.connect(
            lambda: QTimer.singleShot(0, lambda: self._restore_menu_focus(menu))
        )

    def _restore_menu_focus(self, menu: QMenu) -> None:
        target = getattr(menu, "_pagedrop_focus_target", None)
        if (
            isinstance(target, QWidget)
            and target.isVisible()
            and target.isEnabled()
            and target.window() is self
            and QApplication.activeModalWidget() is None
        ):
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _set_toolbar_primary(self) -> None:
        """Save as is the command bar's one primary action, in every state."""
        for action, icon_name in (
            (self._actions["open"], "folder-open"),
            (self._save_as_action, "floppy-disk"),
        ):
            button = self._toolbar.widgetForAction(action)
            if button is None:
                continue
            primary = action is self._save_as_action
            button.setObjectName("ToolbarPrimary" if primary else "")
            button.setIcon(
                icons.icon(icon_name, color=current_theme().on_ink)
                if primary
                else action.icon()
            )
            button.style().unpolish(button)
            button.style().polish(button)

    def _reset_toolbar_for_blank_tab(self) -> None:
        tab = self._active_tab()
        self._update_window_title()
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
        self._extract_selected_action.setEnabled(False)
        self._extract_selected_to_tab_action.setEnabled(False)
        self._extract_selected_to_window_action.setEnabled(False)
        self._view_switch.set_viewer_mode(False)
        self._zoom_controls.setEnabled(False)
        self._zoom_controls.set_value(
            tab.zoom_level if tab is not None else thumbnail_zoom()
        )
        self._progress_bar.hide()
        self._update_close_tab_action()
        self._update_save_as_action()
        self._pending_selection = set()
        self._last_selection_toolbar_snap = self._selection_toolbar_snapshot(set())
        self._sync_contextual_toolbar(set())
        self._toolbar.hide()
        self._update_thumbnail_zoom_host()

    def _reset_toolbar_for_tool_page(self) -> None:
        """Tool pages own their chrome and footer; never inherit PDF context."""
        self._update_window_title()
        self._progress_bar.hide()
        self._move_undo_widget.hide()
        # No document here: the preview, selection and page commands do nothing.
        self._preview_action.setEnabled(False)
        self._update_preview_mode_ui()
        self._persistent_status("Ready")

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
        self._extract_selected_action.setEnabled(enabled)
        self._extract_selected_to_tab_action.setEnabled(enabled)
        self._extract_selected_to_window_action.setEnabled(enabled)

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
        description = (
            tab.markup_session.undo_description()
            if tab.is_viewer_mode() and tab.markup_session.can_undo()
            else tab.edit_model.undo_description() if tab.edit_model is not None else None
        )
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
        self._update_undo_redo_actions()
        self._transient_status(self._history_outcome(description, undo=True))

    def _redo(self) -> None:
        tab = self._active_tab()
        if tab is None:
            return
        description = (
            tab.markup_session.redo_description()
            if tab.is_viewer_mode() and tab.markup_session.can_redo()
            else tab.edit_model.redo_description() if tab.edit_model is not None else None
        )
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
        self._update_undo_redo_actions()
        self._transient_status(self._history_outcome(description, undo=False))

    def _update_undo_redo_actions(self) -> None:
        tab = self._active_tab()
        model = tab.edit_model if tab is not None else None
        preview_blocking = tab is not None and tab.is_preview_visible()
        markup_undo = tab is not None and tab.is_viewer_mode() and tab.markup_session.can_undo()
        markup_redo = tab is not None and tab.is_viewer_mode() and tab.markup_session.can_redo()
        undo_description = (
            tab.markup_session.undo_description() if markup_undo else model.undo_description() if model else None
        )
        redo_description = (
            tab.markup_session.redo_description() if markup_redo else model.redo_description() if model else None
        )
        undo_enabled = markup_undo or (model is not None and model.can_undo() and not preview_blocking)
        redo_enabled = markup_redo or (model is not None and model.can_redo() and not preview_blocking)
        self._set_history_action(self._undo_action, "Undo", undo_description, undo_enabled, preview_blocking)
        self._set_history_action(self._redo_action, "Redo", redo_description, redo_enabled, preview_blocking)

    @staticmethod
    def _set_history_action(
        action: QAction,
        verb: str,
        description: str | None,
        enabled: bool,
        viewer_blocking: bool,
    ) -> None:
        action.setText(f"{verb} {description}" if description else f"&{verb}")
        reason = (
            f"Return to the page grid to {verb.casefold()} {description}"
            if description and viewer_blocking and not enabled
            else ""
        )
        action.setProperty("unavailableReason", reason)
        action.setToolTip(reason)
        action.setStatusTip(reason)
        action.setEnabled(enabled)

    @staticmethod
    def _history_outcome(description: str | None, *, undo: bool) -> str:
        if not description:
            return "Undo complete" if undo else "Redo complete"
        if undo and description.startswith("delete "):
            return f"Restored {description.removeprefix('delete ')}"
        if undo and description.startswith("rotate "):
            return "Rotation undone"
        if undo and description.startswith("add "):
            return f"Removed {description.removeprefix('add ')}"
        return f"{'Undid' if undo else 'Redid'} {description}"

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
        show_context_hint(
            self,
            self._view_switch,
            KEY_CONTEXT_HINT_BACK_TO_GRID,
            "Use Grid view to return to your thumbnails.",
        )

    def _show_transfer_hint(self, anchor: QWidget) -> None:
        show_context_hint(
            self,
            anchor,
            KEY_CONTEXT_HINT_TRANSFER,
            "Drag to another document to copy pages. Hold Shift to move them.",
        )

    def _update_preview_mode_ui(self) -> None:
        tab = self._active_tab()
        in_preview = tab is not None and tab.is_preview_visible()
        self._preview_action.setText("Back to grid" if in_preview else "Preview")
        self._view_switch.set_viewer_mode(in_preview)
        if in_preview:
            self._set_action_hint(self._preview_action, "Return to the thumbnail grid")
        else:
            self._set_action_hint(
                self._preview_action,
                "Preview selected page (Enter or double-click a card)",
            )
        has_pdf = tab is not None and tab.loader is not None
        self._update_thumbnail_zoom_host()
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
        # Fitted once the grid has its real size; the zoom control follows
        # through the grid's zoom signal.
        tab.thumbnail_grid.request_autofit()
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
        dialog = QDialog(self)
        dialog.setWindowTitle("Select pages")
        form = QFormLayout(dialog)
        page_input = QLineEdit(dialog)
        page_input.setObjectName("SelectPagesInput")
        page_input.setAccessibleName("Pages to select")
        label = QLabel("Pages:", dialog)
        label.setBuddy(page_input)
        form.addRow(label, page_input)
        description = QLabel(
            f"Use page numbers or ranges from 1 to {count}, separated by commas "
            "(for example, 1-3,5).",
            dialog,
        )
        description.setWordWrap(True)
        form.addRow(description)
        error = QLabel(dialog)
        error.setObjectName("SelectPagesError")
        error.setWordWrap(True)
        error.setAccessibleName("Selection error")
        error.hide()
        form.addRow(error)
        preview = QLabel("Enter pages to preview the selection.", dialog)
        preview.setObjectName("SelectPagesCount")
        preview.setAccessibleName("Selection count")
        form.addRow(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, dialog)
        select_button = buttons.addButton(
            "Select", QDialogButtonBox.ButtonRole.AcceptRole
        )
        select_button.setObjectName("SelectPagesConfirm")
        select_button.setEnabled(False)
        form.addRow(buttons)

        selected_indices: list[int] = []

        def indices_for_text() -> list[int] | None:
            ranges = parse_page_ranges(page_input.text(), count)
            if ranges is None:
                return None
            return sorted(
                {index for start, end in ranges for index in range(start, end + 1)}
            )

        def update_preview() -> None:
            nonlocal selected_indices
            selected_indices = indices_for_text() or []
            if not page_input.text().strip():
                error.clear()
                error.hide()
                preview.setText("Enter pages to preview the selection.")
            elif not selected_indices:
                error.setText(
                    f"Use page numbers from 1 to {count}, separated by commas or "
                    "ranges (for example, 1-3,5)."
                )
                error.show()
                preview.setText("No pages selected.")
                page_input.setFocus()
            else:
                error.clear()
                error.hide()
                noun = "page" if len(selected_indices) == 1 else "pages"
                preview.setText(f"{len(selected_indices)} {noun} will be selected.")
            select_button.setEnabled(bool(selected_indices))

        def select_pages() -> None:
            if not selected_indices:
                page_input.setFocus()
                return
            dialog.accept()

        page_input.textChanged.connect(update_preview)
        select_button.clicked.connect(select_pages)
        buttons.rejected.connect(dialog.reject)
        page_input.setFocus()
        if dialog.exec() != QDialog.DialogCode.Accepted or not selected_indices:
            return
        tab.thumbnail_grid.jump_to_pages(selected_indices)
        noun = "page" if len(selected_indices) == 1 else "pages"
        self._transient_status(f"Selected {len(selected_indices)} {noun}")

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
        if pending:
            # zoom_changed may just have surfaced the one-shot large-document
            # guidance; don't immediately replace it with render progress.
            if self.statusBar().currentMessage().startswith(
                "Large document at high zoom"
            ):
                return
            self._transient_status("Rendering thumbnails…")
            return
        if self.statusBar().currentMessage() == "Rendering thumbnails…":
            tab = self._active_tab()
            if tab is not None:
                self._transient_status(f"Thumbnail size: {tab.zoom_level} px")

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
        KeyboardShortcutsDialog(self._actions.values(), self).exec()

    def _show_about(self) -> None:
        version = QApplication.instance().applicationVersion()
        repo = "https://github.com/ParallaX07/PageDrop"
        box = QMessageBox(self)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.setWindowTitle("About PageDrop")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"<p>PageDrop version {version}</p>"
            "<p>Copyright (C) PageDrop contributors</p>"
            "<p>PageDrop is free software under AGPL-3.0-or-later. "
            "This program comes with ABSOLUTELY NO WARRANTY.</p>"
            f'<p><a href="{repo}/blob/v{version}/LICENSE">Read the licence</a></p>'
            f'<p>Source: <a href="{repo}/tree/v{version}">{repo}/tree/v{version}</a></p>'
        )
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        icon = self.windowIcon()
        if not icon.isNull():
            box.setIconPixmap(icon.pixmap(64, 64))
        box.exec()

    def _open_preferences(self) -> None:
        from pagedrop.ui.preferences_dialog import open_preferences

        open_preferences(
            self,
            coordinator=self._window_manager.update_coordinator if self._window_manager else None,
        )

    def _check_for_updates(self) -> None:
        if self._window_manager is None:
            QMessageBox.information(
                self, "PageDrop updates", "Updates are available only in the packaged Windows version."
            )
            return
        self._window_manager.update_presenter.check_manually(self)

    def _install_scoped_event_filters(self) -> None:
        """Watch only the widgets and the window handle this window cares about."""
        self._chrome_filter_targets = (
            self,
            self._toolbar,
            self._menu_bar,
            *self._title_drag_widgets,
        )
        for target in self._chrome_filter_targets:
            target.installEventFilter(self)
        self._attach_window_handle_filter()
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    def _attach_window_handle_filter(self) -> None:
        handle = self.windowHandle()
        if handle is not None:
            handle.installEventFilter(self)

    def _on_focus_changed(self, _old, new) -> None:
        """Page shortcuts are filtered on the focused widget of this window only."""
        self._remove_key_filter()
        if (
            isinstance(new, QWidget)
            and new.window() is self
            and new not in self._chrome_filter_targets
        ):
            new.installEventFilter(self)
            self._key_filter_widget = new

    def _remove_key_filter(self) -> None:
        widget, self._key_filter_widget = self._key_filter_widget, None
        if widget is not None:
            try:
                widget.removeEventFilter(self)
            except RuntimeError:  # the widget was already destroyed
                pass

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "_toolbar", None):
            if event.type() == QEvent.Type.Resize:
                # Filters run before the layout, so the bar lays out already fitted.
                self._refit_toolbar()
            elif event.type() == QEvent.Type.Show:
                QTimer.singleShot(0, self._refit_toolbar)
        if isinstance(obj, QWindow):
            if self._handle_edge_resize_event(event):
                return True
        elif obj is self:
            if event.type() == QEvent.Type.WindowDeactivate:
                self._clear_edge_state()
            elif event.type() == QEvent.Type.WinIdChange:
                self._attach_window_handle_filter()
        if self._handle_title_area_event(obj, event):
            return True
        if (
            event.type() != QEvent.Type.KeyPress
            or not isinstance(event, QKeyEvent)
            or QApplication.activeModalWidget() is not None
            or not isinstance(obj, QWidget)
            or obj.window() is not self
            or text_input_has_focus()
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
        if tab is None:
            page = self._tab_manager.currentWidget()
            title = getattr(page, "tab_title", None) or getattr(page, "WINDOW_TITLE", None)
            self.setWindowTitle(f"{self.APP_TITLE}: {title}" if title else self.APP_TITLE)
            self._sync_custom_title()
            return
        if tab.edit_model is None or tab.display_path is None:
            self.setWindowTitle(self.APP_TITLE)
            self._sync_custom_title()
            return
        count = tab.edit_model.logical_count()
        noun = "page" if count == 1 else "pages"
        self.setWindowTitle(
            f"{self.APP_TITLE}: {tab.tab_title} ({count} {noun})"
        )
        self._sync_custom_title()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_responsive_shell()

    def _update_thumbnail_zoom_host(self) -> None:
        if not hasattr(self, "_thumbnail_zoom_host"):
            return
        tab = self._active_tab()
        visible = tab is not None and tab.loader is not None and not tab.is_preview_visible()
        self._thumbnail_zoom_host.setVisible(visible)
        self._zoom_controls.set_slider_visible(self.width() > 800)
        # The buttons and px readout say what the cluster is; the caption goes
        # first so the status message keeps its room in a narrow window.
        self._thumbnail_zoom_label.setVisible(self.width() > COMPACT_STATUS_WIDTH)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            button = getattr(self, "_maximize_button", None)
            if button is not None:
                maximized = self.isMaximized()
                self._refresh_window_control_icons()
                button.setToolTip("Restore window" if maximized else "Maximize window")
                button.setAccessibleName(button.toolTip())
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            # Button widths are remeasured the next time the toolbar is fitted.
            getattr(self, "_toolbar_hint_widths", {}).clear()
            getattr(self, "_toolbar_icon_widths", {}).clear()
            QTimer.singleShot(0, self._update_responsive_shell)
            QTimer.singleShot(0, self._refit_toolbar)
        super().changeEvent(event)

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

        self._start_folder_export(
            tab, tab.selected_page_refs(), Path(folder), "Extracted"
        )

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

        refs = [
            tab.edit_model.page_at(index)
            for index in range(tab.edit_model.logical_count())
        ]
        self._start_folder_export(tab, refs, Path(folder), "Exported")

    def _start_folder_export(self, tab: PdfTab, refs, folder: Path, verb: str) -> None:
        if not refs or tab in self._editor_busy or tab.edit_model is None:
            return
        remember_directory(str(folder))
        base_name = Path(tab.display_name).stem
        token = self._begin_editor_job(
            tab, f"{verb[:-2] if verb.endswith('ed') else verb}ing pages…"
        )
        worker = EditorJobWorker.export(
            list(refs),
            folder,
            base_name,
            tab.credentials.snapshot(),
            token,
            tab._temp_manager,
        )
        signals = worker.signals

        def finish() -> None:
            release_editor_signals(signals)
            self._end_editor_job(tab)

        def succeeded(result: object) -> None:
            paths = list(result)
            count = len(paths)
            noun = "page" if count == 1 else "pages"
            renamed = any(
                path.name != f"{base_name}_page_{index:04d}.pdf"
                for index, path in enumerate(paths, start=1)
            )
            suffix = " (renamed to avoid collisions)" if renamed else ""
            message = f"{verb} {count} {noun} to {folder}{suffix}"
            self._transient_status(message)
            self._show_toast(f"{verb} {count} {noun}{suffix}", kind="success")
            finish()

        def cancelled() -> None:
            finish()
            self._transient_status(f"{verb} cancelled")
            self._show_toast(f"{verb} cancelled", kind="info")

        def failed(error: str) -> None:
            finish()
            QMessageBox.critical(
                self, f"{verb} pages", f"Could not {verb.lower()} pages:\n{error}"
            )
            self._transient_status(f"{verb} failed")
            self._show_toast(f"{verb} failed", kind="error")

        signals.progress.connect(
            lambda _fraction, message: self._persistent_status(message)
            if tab is self._active_tab()
            else None
        )
        signals.succeeded.connect(succeeded)
        signals.cancelled.connect(cancelled)
        signals.failed.connect(failed)
        start_editor_worker(worker)

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
        if self._window_manager is not None and self._window_manager.preparing_installation:
            return
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
        if new_window is None:
            return
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
        if self._window_manager is not None and self._window_manager.preparing_installation:
            return
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
        # The explicit floor is for a top-level window; hosted, it would set the
        # tab stack's (and so this window's) minimum size.
        page.setMinimumSize(0, 0)
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

    def _open_ocr_from_viewer(self) -> None:
        """Open the existing OCR shell; it pre-fills the active document."""
        self._open_tools_window()
        if self._tools_window is not None:
            self._tools_window._on_tile_activated("ocr_pdf")

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

    def open_command_line_paths(self, paths: list[str]) -> None:
        """Open PDFs named on the command line; report any that cannot be opened."""
        good: list[str] = []
        problems: list[str] = []
        for path in paths:
            file = Path(path)
            if not _is_file(file):
                problems.append(f"{file.name or path}: file not found")
            elif file.suffix.lower() != ".pdf":
                problems.append(f"{file.name}: not a PDF file")
            else:
                good.append(path)
        if problems:
            message = "Could not open " + "; ".join(problems)
            self._transient_status(message)
            self._show_toast(message, kind="error")
        if not good:
            return
        remember_directory(good[0])
        active = self._active_tab()
        if active is None:
            active = self._tab_manager.add_blank_tab()
        self._open_paths_as_tabs(good, first_tab=active if active.is_blank else None)

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
        self._open_recent_if_present(path)

    def _open_recent_if_present(self, path: str) -> None:
        """Open a recent file, or say why not when it has gone."""
        if not _is_file(Path(path)):
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
            if self._confirm_replace_tab(active):
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
        if new_window is None:
            return
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
            except PdfEmptyError as exc:
                log_failure("Open PDF", exc, path=path)
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
                log_failure("Open PDF", exc, path=path)
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

    def _blank_tab_start_screen(self):
        """The active tab's start screen, or None when something else is showing."""
        tab = self._active_tab()
        if tab is None or not tab.is_blank:
            return None
        if tab.content_stack.currentWidget() is not tab.start_screen:
            return None
        return tab.start_screen

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        screen = self._blank_tab_start_screen()
        if screen is None:
            event.ignore()
            return
        screen.dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        screen = self._blank_tab_start_screen()
        if screen is None:
            event.ignore()
            return
        screen.dragMoveEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        screen = self._blank_tab_start_screen()
        if screen is not None:
            screen.dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        screen = self._blank_tab_start_screen()
        if screen is None:
            event.ignore()
            return
        screen.dropEvent(event)

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

    def _open_source_paths(self) -> set[str]:
        """Source paths of every open PDF tab in this and any other window."""
        windows = {self}
        if self._window_manager is not None:
            windows.update(self._window_manager.windows)
        paths: set[str] = set()
        for window in windows:
            for index in range(window._tab_manager.count()):
                tab = window._tab_manager.widget(index)
                if isinstance(tab, PdfTab) and tab.edit_model is not None:
                    paths.update(tab.edit_model.source_paths())
        return paths

    def _save_as(self, tab: PdfTab | None = None) -> bool:
        """Start a non-blocking Save As transaction for an immutable tab snapshot."""
        target = tab or self._active_tab()
        if target is None or target.edit_model is None or target in self._editor_busy:
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

        try:
            reject_source_overwrite(
                path, *model.source_paths(), *self._open_source_paths()
            )
        except SourceOverwriteError:
            QMessageBox.warning(
                self,
                "Save as",
                "Cannot save over a source file, including one open in "
                "another tab.\nChoose a different path.",
            )
            return False

        regions = target.markup_session.redaction_regions(model)
        scope = prompt_redaction_scope(self) if regions else None
        if regions and scope is None:
            return False
        snapshot = model.snapshot_for_write()
        markup = copy.deepcopy(target.markup_session.non_redaction_ops(model) or None)
        revision = (tuple(model.iter_pages()), tuple(target.peek_markup_ops()))
        credentials = RuntimeCredentials()
        for source, password in target.credentials.snapshot().items():
            credentials.set(source, password)
        token = self._begin_editor_job(target, "Saving PDF…")
        spec = JobSpec.create(
            "editor_save",
            inputs=sorted(snapshot.source_paths()),
            output=path,
            options={
                "model": snapshot,
                "markup": markup,
                "regions": copy.deepcopy(regions),
                "scope": scope,
            },
            overwrite=True,
        )
        worker = EditorJobWorker.save(self._editor_runner, spec, token, credentials)
        signals = worker.signals

        def finish() -> None:
            release_editor_signals(signals)
            self._end_editor_job(target)

        def progress(_fraction: float, message: str) -> None:
            if target is self._active_tab():
                self._persistent_status(message)

        def succeeded(_result: object) -> None:
            remember_directory(path)
            current = target.edit_model
            if current is None or (
                tuple(current.iter_pages()), tuple(target.peek_markup_ops())
            ) != revision:
                message = f"Saved {Path(path).name} from an earlier snapshot"
                self._transient_status(message)
                self._show_toast(message, kind="warning")
                finish()
                return
            try:
                target.commit_saved_output(path)
            except (PdfLoadError, OSError) as exc:
                QMessageBox.critical(self, "Save as", f"Saved copy could not be opened:\n{exc}")
                finish()
                return
            self._tab_manager.update_tab_title(target)
            if target is self._active_tab():
                self._sync_toolbar_from_active_tab()
                message = (
                    f"Verified redacted copy saved to {Path(path).name}"
                    if regions
                    else f"Saved to {Path(path).name}"
                )
                self._transient_status(message)
                self._show_toast(message, kind="success")
            finish()

        def cancelled() -> None:
            finish()
            self._transient_status("Save cancelled")
            self._show_toast("Save cancelled", kind="info")

        def failed(error: str) -> None:
            finish()
            QMessageBox.critical(self, "Save as", f"Could not save PDF:\n{error}")
            self._transient_status("Save failed")
            self._show_toast("Save failed", kind="error")

        signals.progress.connect(progress)
        signals.succeeded.connect(succeeded)
        signals.cancelled.connect(cancelled)
        signals.failed.connect(failed)
        start_editor_worker(worker)
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

    def _save_and_wait(self, tab: PdfTab) -> bool:
        """Save As, wait for the job, and report whether the tab is now clean."""
        if not self._save_as(tab):
            return False
        self.wait_for_editor_job(tab)
        return not tab.is_dirty

    def _confirm_replace_tab(self, tab: PdfTab) -> bool:
        """True when *tab* may be replaced: idle, and saved or explicitly discarded."""
        if tab in self._editor_busy:
            self._transient_status("Wait for the running task to finish before opening")
            return False
        if not tab.is_dirty:
            return True
        choice = self._prompt_unsaved_changes(tab)
        if choice == "cancel":
            return False
        return choice != "save" or self._save_and_wait(tab)

    def _try_close_tab(self, index: int) -> bool:
        if self._window_manager is not None and self._window_manager.preparing_installation:
            return False
        if index < 0 or index >= self._tab_manager.count():
            return False

        tab = self._tab_manager.widget(index)
        if isinstance(tab, PdfTab):
            if tab in self._editor_busy:
                self._transient_status("Wait for the running task to finish before closing")
                return False
            if tab.is_blank:
                if self._is_only_blank_tab():
                    return False
            elif tab.is_dirty and confirm_before_closing_dirty_tabs():
                choice = self._prompt_unsaved_changes(tab)
                if choice == "cancel":
                    return False
                if choice == "save" and not self._save_and_wait(tab):
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
        tab = self._active_tab()
        if tab is not None:
            self._sync_contextual_toolbar(tab.thumbnail_grid.selection_manager.selection)

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

    def _on_pages_copied_not_moved(self, count: int) -> None:
        if not self._grid_belongs_to_window(self.sender()):
            return
        noun = "page" if count == 1 else "pages"
        message = (
            f"Copied {count} {noun}, not moved: the source is in another "
            "PageDrop process"
        )
        self._transient_status(message, page=self._sender_tab())
        self._show_toast(message, kind="info")
        self._sync_toolbar_from_active_tab()

    def _on_page_transfer_failed(self, message: str) -> None:
        if not self._grid_belongs_to_window(self.sender()):
            return
        QMessageBox.warning(self, "Page transfer", message)
        self._transient_status(message, page=self._sender_tab())

    def _on_pdf_drop_failed(self, exc: object) -> None:
        if not self._grid_belongs_to_window(self.sender()):
            return
        tab = self._sender_tab()
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
        self._persistent_status("Ready", page=tab)

    def _on_rendering_error(self, message: str) -> None:
        # One notice per loaded document; the grid keeps rendering other pages.
        if not self._grid_belongs_to_window(self.sender()):
            return
        self._show_toast("Some thumbnails could not be rendered", kind="error")
        self._transient_status(
            f"Some thumbnails could not be rendered: {message}",
            page=self._sender_tab(),
        )

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
        self._sync_contextual_toolbar(selection)
        if selection:
            show_context_hint(
                self,
                self._selection_toolbar_label,
                KEY_CONTEXT_HINT_SELECTION_EXPORT,
                "Drag selected pages to a folder to export them as PDF files.",
            )

    def hideEvent(self, event) -> None:  # noqa: ANN001, N802
        self._clear_edge_state()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._clear_edge_state()
        if self._window_manager is not None:
            if self._window_manager.preparing_installation:
                event.ignore()
                return
            prepared_shutdown = self._window_manager.prepared_shutdown
        else:
            prepared_shutdown = False
        if not prepared_shutdown:
            if self._editor_busy:
                self._transient_status("Wait for the running task to finish before closing")
                event.ignore()
                return
            if not self._confirm_window_close():
                event.ignore()
                return

        self._remove_key_filter()
        try:
            QApplication.instance().focusChanged.disconnect(self._on_focus_changed)
        except TypeError:  # already disconnected by an earlier close attempt
            pass
        for index in range(self._tab_manager.count()):
            widget = self._tab_manager.widget(index)
            if isinstance(widget, PdfTab):
                widget.close_loader()
        self._temp_manager.cleanup()
        if self._should_persist_geometry():
            save_window_geometry(self.saveGeometry())
        super().closeEvent(event)
        if event.isAccepted():
            icons.unregister_refresh(self._refresh_action_icons)
            if self._window_manager is not None:
                self._window_manager.notify_window_closed(self)

    def _confirm_window_close(self) -> bool:
        """Resolve unsaved edits, then running tool jobs; False aborts or defers the close."""
        discarded, self._close_discarded = self._close_discarded, set()
        if confirm_before_closing_dirty_tabs():
            prompted = set(discarded)
            while True:
                tab = next(
                    (
                        widget
                        for widget in self._tab_widgets()
                        if isinstance(widget, PdfTab)
                        and not widget.is_blank
                        and widget.is_dirty
                        and widget not in prompted
                    ),
                    None,
                )
                if tab is None:
                    break
                prompted.add(tab)
                choice = self._prompt_unsaved_changes(tab)
                if choice == "cancel":
                    return False
                if choice == "save":
                    if not self._save_and_wait(tab):
                        return False
                else:
                    discarded.add(tab)
        pages = [widget for widget in self._tab_widgets() if not isinstance(widget, PdfTab)]
        for page in pages:
            request_close = getattr(page, "request_close", None)
            if callable(request_close) and not request_close():
                return False
        pending = [
            page for page in pages if callable(getattr(page, "worker_pending", None)) and page.worker_pending()
        ]
        if not pending:
            return True
        # A cancelled job's worker may still be writing staging; close only after it ends.
        self._close_discarded = discarded
        self._persistent_status("Cancelling the running task…")
        if not self._close_waiting:
            self._close_waiting = True
            remaining = len(pending)

            def worker_done() -> None:
                nonlocal remaining
                remaining -= 1
                if remaining == 0:
                    self._close_waiting = False
                    QTimer.singleShot(0, self.close)

            for page in pending:
                page.when_worker_finished(worker_done)
        return False

    def _tab_widgets(self) -> list[QWidget | None]:
        return [self._tab_manager.widget(i) for i in range(self._tab_manager.count())]

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
