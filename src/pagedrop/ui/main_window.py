from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QAction, QCloseEvent, QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QStyle,
    QToolBar,
    QToolButton,
    QWidget,
)

from pagedrop.core.pdf_loader import (
    PdfEmptyError,
    PdfLoadError,
)
from pagedrop.core.pdf_writer import write_pdf
from pagedrop.ui.merge_window import MergeWindow
from pagedrop.ui.convert_window import ConvertWindow
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.tab_manager import TabManager
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_THUMBNAIL_WIDTH,
    MIN_THUMBNAIL_WIDTH,
    ZOOM_WHEEL_STEP,
)
from pagedrop.ui.zoom_controls import ZoomControls
from pagedrop.utils.temp_manager import TempManager

if TYPE_CHECKING:
    from pagedrop.ui.window_manager import WindowManager


def _fit_message_box_buttons(message: QMessageBox) -> None:
    """Size multi-action message boxes so button labels are not clipped."""
    buttons = message.buttons()
    if len(buttons) < 2:
        return
    widest = max(button.sizeHint().width() for button in buttons)
    for button in buttons:
        button.setMinimumWidth(widest)
    message.setMinimumWidth(message.sizeHint().width())


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

        self.setWindowTitle(self.APP_TITLE)
        self.setMinimumSize(720, 480)
        self.resize(960, 680)

        self._build_menu()
        self._build_toolbar()
        self._build_status_widgets()
        self._build_selection_shortcuts()
        self._build_tab_shortcuts()
        self._build_central_widget()
        QApplication.instance().installEventFilter(self)
        self.statusBar().showMessage("Ready")
        self._sync_toolbar_from_active_tab()

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
        open_action.triggered.connect(self._open_pdf)

        self._close_action = file_menu.addAction("&Close Tab")
        self._close_action.triggered.connect(self._close_tab)
        self._close_action.setEnabled(False)

        self._save_as_action = file_menu.addAction("Save &As")
        self._save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._save_as_action.triggered.connect(self._save_as)
        self._save_as_action.setEnabled(False)

        file_menu.addSeparator()

        self._new_window_action = file_menu.addAction("New &Window")
        self._new_window_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self._new_window_action.triggered.connect(self._new_window)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        merge_action = menubar.addAction("Merge PDFs")
        merge_action.triggered.connect(self._open_merge_window)

        create_pdf_action = menubar.addAction("Create PDF")
        create_pdf_action.triggered.connect(self._open_convert_window)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Open",
        )
        open_action.triggered.connect(self._open_pdf)
        open_button = toolbar.widgetForAction(open_action)
        if open_button is not None:
            open_button.setObjectName("ToolbarPrimary")

        self._preview_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Preview",
        )
        self._preview_action.setToolTip(
            "Preview selected page in this window (double-click a card)"
        )
        self._preview_action.triggered.connect(self._open_preview)
        self._preview_action.setEnabled(False)

        toolbar.addSeparator()

        self._select_all_action = toolbar.addAction("Select All")
        self._select_all_action.setToolTip("Select all pages (Ctrl+A)")
        self._select_all_action.triggered.connect(self._select_all_pages)
        self._select_all_action.setEnabled(False)

        self._deselect_all_action = toolbar.addAction("Deselect All")
        self._deselect_all_action.setToolTip("Clear selection (Esc)")
        self._deselect_all_action.triggered.connect(self._clear_selection)
        self._deselect_all_action.setEnabled(False)

        self._move_up_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp),
            "Move up",
        )
        self._move_up_action.setToolTip("Move selected pages up (Ctrl+↑)")
        self._move_up_action.triggered.connect(self._move_selected_pages_up)
        self._move_up_action.setEnabled(False)

        self._move_down_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown),
            "Move down",
        )
        self._move_down_action.setToolTip("Move selected pages down (Ctrl+↓)")
        self._move_down_action.triggered.connect(self._move_selected_pages_down)
        self._move_down_action.setEnabled(False)

        self._delete_pages_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon),
            "Delete page(s)",
        )
        self._delete_pages_action.setToolTip("Delete selected pages (Delete)")
        self._delete_pages_action.triggered.connect(self._delete_selected_pages)
        self._delete_pages_action.setEnabled(False)

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
            initial=DEFAULT_THUMBNAIL_WIDTH,
        )
        toolbar.addWidget(self._zoom_controls)
        self._zoom_controls.zoom_requested.connect(self._on_zoom_requested)

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
        new_tab_button.clicked.connect(self._new_blank_tab)
        self._tab_manager.setCornerWidget(
            new_tab_button,
            Qt.Corner.TopRightCorner,
        )

        if self._initial_tab is not None:
            self._adopt_tab(self._initial_tab)
        else:
            self._tab_manager.add_blank_tab()
        self.setCentralWidget(self._tab_manager)
        self._last_tab_index = self._tab_manager.currentIndex()

    def _build_status_widgets(self) -> None:
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.hide()
        self.statusBar().addPermanentWidget(self._progress_bar)

    def _build_selection_shortcuts(self) -> None:
        select_all = QAction(self)
        select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        select_all.triggered.connect(self._select_all_pages)
        self.addAction(select_all)

        self._clear_selection_action = QAction(self)
        self._clear_selection_action.setShortcut(QKeySequence.StandardKey.Cancel)
        self._clear_selection_action.setShortcutContext(
            Qt.ShortcutContext.ApplicationShortcut
        )
        self._clear_selection_action.triggered.connect(self._on_escape)
        self.addAction(self._clear_selection_action)

        delete_pages = QAction(self)
        delete_pages.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        delete_pages.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        delete_pages.triggered.connect(self._delete_selected_pages)
        self.addAction(delete_pages)

        move_up = QAction(self)
        move_up.setShortcut(QKeySequence("Ctrl+Up"))
        move_up.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        move_up.triggered.connect(self._move_selected_pages_up)
        self.addAction(move_up)

        move_down = QAction(self)
        move_down.setShortcut(QKeySequence("Ctrl+Down"))
        move_down.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        move_down.triggered.connect(self._move_selected_pages_down)
        self.addAction(move_down)

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
        grid.page_transfer_failed.connect(self._on_page_transfer_failed)
        grid.pdf_drop_failed.connect(self._on_pdf_drop_failed)
        grid.extract_to_folder_requested.connect(self._extract_selected_to_folder)
        grid.open_pdfs_requested.connect(self._on_open_pdfs_requested)
        tab.preview_widget.page_changed.connect(self._on_preview_page_changed)
        tab.preview_widget.busy_changed.connect(self._on_preview_busy_changed)
        tab.dirty_changed.connect(self._update_save_as_action)

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
            (grid.page_transfer_failed, self._on_page_transfer_failed),
            (grid.pdf_drop_failed, self._on_pdf_drop_failed),
            (grid.extract_to_folder_requested, self._extract_selected_to_folder),
            (grid.open_pdfs_requested, self._on_open_pdfs_requested),
            (preview.page_changed, self._on_preview_page_changed),
            (preview.busy_changed, self._on_preview_busy_changed),
            (tab.dirty_changed, self._update_save_as_action),
        ):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass

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
        self._zoom_controls.setEnabled(not tab.is_preview_visible())
        self._zoom_controls.set_value(tab.zoom_level)
        self._update_preview_mode_ui()
        self._update_close_tab_action()
        self._update_save_as_action()

    def _reset_toolbar_for_blank_tab(self) -> None:
        self._update_window_title()
        self._filename_label.setText("No file open")
        self._filename_label.setProperty("active", False)
        self._filename_label.style().unpolish(self._filename_label)
        self._filename_label.style().polish(self._filename_label)
        self._preview_action.setEnabled(False)
        self._select_all_action.setEnabled(False)
        self._deselect_all_action.setEnabled(False)
        self._delete_pages_action.setEnabled(False)
        self._move_up_action.setEnabled(False)
        self._move_down_action.setEnabled(False)
        self._zoom_controls.setEnabled(False)
        self._zoom_controls.set_value(DEFAULT_THUMBNAIL_WIDTH)
        self._progress_bar.hide()
        self._update_close_tab_action()
        self._update_save_as_action()

    def _update_save_as_action(self) -> None:
        tab = self._active_tab()
        self._save_as_action.setEnabled(
            tab is not None
            and tab.edit_model is not None
            and tab.edit_model.logical_count() > 0
        )

    def _update_delete_pages_action(self) -> None:
        tab = self._active_tab()
        self._delete_pages_action.setEnabled(
            tab is not None
            and tab.edit_model is not None
            and not tab.is_preview_visible()
            and bool(tab.thumbnail_grid.selection_manager.selection)
        )

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
        self._deselect_all_action.setEnabled(False)
        self._update_save_as_action()
        if tab.edit_model.logical_count() == 0:
            self.statusBar().showMessage("All pages deleted")
        else:
            noun = "page" if count == 1 else "pages"
            self.statusBar().showMessage(f"Deleted {count} {noun}")

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
        count = len(tab.thumbnail_grid.selection_manager.selection)
        noun = "page" if count == 1 else "pages"
        self.statusBar().showMessage(f"Moved {count} {noun} up")

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
        count = len(tab.thumbnail_grid.selection_manager.selection)
        noun = "page" if count == 1 else "pages"
        self.statusBar().showMessage(f"Moved {count} {noun} down")

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
            if selection:
                self._on_selection_changed(selection)
            else:
                count = tab.edit_model.logical_count()
                noun = "page" if count == 1 else "pages"
                self.statusBar().showMessage(f"Loaded {count} {noun}")

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
        self._preview_action.setToolTip(
            "Return to the thumbnail grid"
            if in_preview
            else "Preview selected page in this window (double-click a card)"
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

    def _update_preview_status(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None or not tab.is_preview_visible():
            return
        page = tab.preview_widget.current_page + 1
        total = tab.edit_model.logical_count()
        self.statusBar().showMessage(f"Preview — page {page} of {total}")

    def _on_preview_page_changed(self, page_index: int) -> None:
        tab = self._active_tab()
        if tab is None or tab.preview_widget is not self.sender():
            return
        tab.thumbnail_grid.selection_manager.select_single(page_index)
        self._update_preview_status()

    def _on_zoom_requested(self, thumbnail_width_px: int) -> None:
        tab = self._active_tab()
        if tab is None:
            return
        tab.set_zoom_level(thumbnail_width_px)

    def _on_zoom_changed(self, thumbnail_width_px: int) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        tab = self._active_tab()
        if tab is not None and tab.loader is not None:
            self._zoom_controls.set_value(thumbnail_width_px)
            self.statusBar().showMessage(
                f"Thumbnail size: {thumbnail_width_px} px"
            )

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
        filename = Path(tab.pdf_path).name
        count = tab.edit_model.logical_count()
        noun = "page" if count == 1 else "pages"
        self.setWindowTitle(f"{self.APP_TITLE} — {filename} ({count} {noun})")

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
        self.statusBar().showMessage(f"Extracted {count} {noun} to {folder}")

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

        choice = self._ask_multi_open_target(len(paths))
        if choice is None:
            return
        if choice == "tabs":
            for path in paths:
                tab = self._tab_manager.add_blank_tab()
                self._load_pdf(path, tab=tab)
            self._tab_manager.setCurrentIndex(self._tab_manager.count() - 1)
        else:
            for path in paths:
                self._open_in_new_window(path)

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
        _fit_message_box_buttons(message)
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
        _fit_message_box_buttons(message)
        message.exec()
        clicked = message.clickedButton()
        if clicked is cancel_button:
            return None
        if clicked is tabs_button:
            return "tabs"
        if clicked is windows_button:
            return "windows"
        return None

    def _load_pdf(self, path: str, *, tab: PdfTab | None = None) -> None:
        target = tab or self._active_tab()
        if target is None:
            target = self._tab_manager.add_blank_tab()

        filename = Path(path).name

        try:
            loader = target.load_pdf(path)
        except PdfEmptyError:
            QMessageBox.warning(
                self,
                "Open PDF",
                f"{filename} has no pages.",
            )
            if target is self._active_tab():
                self._sync_toolbar_from_active_tab()
                self.statusBar().showMessage("Ready")
            return
        except PdfLoadError as exc:
            QMessageBox.critical(
                self,
                "Open PDF",
                f"Could not open {filename}:\n{exc}",
            )
            if target is self._active_tab():
                self._sync_toolbar_from_active_tab()
                self.statusBar().showMessage("Ready")
            return

        self._tab_manager.update_tab_title(target)
        if target is self._active_tab():
            self._sync_toolbar_from_active_tab()
            count = (
                target.edit_model.logical_count()
                if target.edit_model is not None
                else loader.page_count
            )
            noun = "page" if count == 1 else "pages"
            self.statusBar().showMessage(f"Loading {count} {noun}…")

    def _on_open_pdfs_requested(self, paths: list) -> None:
        """Open PDFs dropped onto a blank tab (first into that tab, rest as new tabs)."""
        if not paths or not self._grid_belongs_to_active_tab(self.sender()):
            return
        tab = self._active_tab()
        if tab is None or not tab.is_blank:
            return

        remember_directory(paths[0])
        self._load_pdf(paths[0], tab=tab)
        for path in paths[1:]:
            new_tab = self._tab_manager.add_blank_tab()
            self._load_pdf(path, tab=new_tab)
        if len(paths) > 1:
            self._tab_manager.setCurrentIndex(self._tab_manager.count() - 1)

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
            self.statusBar().showMessage(f"Saved to {Path(path).name}")
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
            self.statusBar().showMessage(f"Tab renamed to {tab.tab_title}")

    def _prompt_unsaved_changes(self, tab: PdfTab) -> str:
        """Return ``save``, ``discard``, or ``cancel``."""
        if os.environ.get("PAGEDROP_TESTING") == "1":
            return "discard"

        model = tab.edit_model
        filename = Path(model.original_path).name if model is not None else "document"
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Unsaved Changes")
        message.setText(f'"{filename}" has unsaved changes.')
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
        _fit_message_box_buttons(message)
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
        elif tab.is_dirty:
            choice = self._prompt_unsaved_changes(tab)
            if choice == "cancel":
                return False
            if choice == "save" and not self._save_as(tab):
                return False

        self._tab_manager.close_tab(index)
        return True

    def _close_tab(self) -> None:
        if self._is_only_blank_tab():
            return
        index = self._tab_manager.currentIndex()
        if index >= 0 and self._try_close_tab(index):
            self._sync_toolbar_from_active_tab()
            self.statusBar().showMessage("Tab closed")

    def _on_tab_close_requested(self, index: int) -> None:
        tab = self._tab_manager.widget(index)
        if isinstance(tab, PdfTab) and tab.is_blank and self._is_only_blank_tab():
            return
        if self._try_close_tab(index):
            self._sync_toolbar_from_active_tab()
            self.statusBar().showMessage("Tab closed")

    def _on_rendering_started(self, total_pages: int) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self._progress_bar.setRange(0, total_pages)
        self._progress_bar.setValue(0)
        self._progress_bar.show()

    def _on_rendering_progress(self, current: int, total: int) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self._progress_bar.setValue(current)
        self.statusBar().showMessage(f"Rendering page {current} of {total}…")

    def _on_rendering_finished(self) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        tab = self._active_tab()
        self._progress_bar.hide()
        if tab is not None and tab.edit_model is not None:
            selection = tab.thumbnail_grid.selection_manager.selection
            if selection:
                self._on_selection_changed(selection)
            else:
                count = tab.edit_model.logical_count()
                noun = "page" if count == 1 else "pages"
                self.statusBar().showMessage(f"Loaded {count} {noun}")

    def _on_pages_inserted(
        self, count: int, filename: str, position: int
    ) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self._update_window_title()
        noun = "page" if count == 1 else "pages"
        self.statusBar().showMessage(
            f"Inserted {count} {noun} from {filename} at position {position}"
        )

    def _on_cross_window_pages_inserted(
        self, count: int, filename: str
    ) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        noun = "page" if count == 1 else "pages"
        self.statusBar().showMessage(
            f"Inserted {count} {noun} from {filename}"
        )
        self._sync_toolbar_from_active_tab()

    def _on_pages_moved_out(self, count: int, target_filename: str) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        noun = "page" if count == 1 else "pages"
        suffix = f" to {target_filename}" if target_filename else ""
        self.statusBar().showMessage(
            f"Moved {count} {noun}{suffix}"
        )
        self._sync_toolbar_from_active_tab()

    def _on_pages_transferred_via_tab_bar(
        self, count: int, target_filename: str, moved: bool
    ) -> None:
        sender = self.sender()
        if sender is None or not self._grid_belongs_to_window(sender):
            return
        noun = "page" if count == 1 else "pages"
        verb = "Moved" if moved else "Appended"
        suffix = f" to {target_filename}" if target_filename else ""
        self.statusBar().showMessage(f"{verb} {count} {noun}{suffix}")
        self._sync_toolbar_from_active_tab()

    def _on_page_transfer_failed(self, message: str) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self.statusBar().showMessage(message)

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
        self.statusBar().showMessage("Ready")

    def _on_rendering_error(self, message: str) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        self._progress_bar.hide()
        QMessageBox.critical(
            self,
            "Render Pages",
            f"Could not render thumbnails:\n{message}",
        )
        self.statusBar().showMessage("Rendering failed")

    def _on_grid_busy_changed(self, busy: bool, message: str) -> None:
        if not self._grid_belongs_to_active_tab(self.sender()):
            return
        tab = self._active_tab()
        if tab is None or tab.is_preview_visible():
            return
        if busy and message:
            self.statusBar().showMessage(message)
        elif tab.edit_model is not None and not self._progress_bar.isVisible():
            count = tab.edit_model.logical_count()
            noun = "page" if count == 1 else "pages"
            self.statusBar().showMessage(f"Loaded {count} {noun}")

    def _on_preview_busy_changed(self, busy: bool, message: str) -> None:
        tab = self._active_tab()
        if tab is None or self.sender() is not tab.preview_widget:
            return
        if busy and message:
            self.statusBar().showMessage(message)
        elif tab.edit_model is not None:
            page = tab.preview_widget.current_page + 1
            total = tab.edit_model.logical_count()
            self.statusBar().showMessage(f"Preview · page {page} of {total}")

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
        if selection:
            count = len(selection)
            noun = "page" if count == 1 else "pages"
            self.statusBar().showMessage(f"{count} {noun} selected")
        elif tab is not None and tab.loader is not None:
            self.statusBar().showMessage("No selection")

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
        super().closeEvent(event)
        if event.isAccepted() and self._window_manager is not None:
            self._window_manager.notify_window_closed(self)
