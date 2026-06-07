from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QAction, QCloseEvent, QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
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


class MainWindow(QMainWindow):
    APP_TITLE = "PageDrop"

    def __init__(self) -> None:
        super().__init__()
        self._temp_manager = TempManager()

        self.setWindowTitle(self.APP_TITLE)
        self.setMinimumSize(720, 480)
        self.resize(960, 680)

        self._build_menu()
        self._build_toolbar()
        self._build_status_widgets()
        self._build_central_widget()
        self._build_selection_shortcuts()
        self._build_tab_shortcuts()
        QApplication.instance().installEventFilter(self)
        self.statusBar().showMessage("Ready")
        self._sync_toolbar_from_active_tab()

    @property
    def current_pdf_path(self) -> str | None:
        tab = self._tab_manager.active_tab
        return tab.pdf_path if tab is not None else None

    @current_pdf_path.setter
    def current_pdf_path(self, value: str | None) -> None:
        pass  # legacy tests may assign; path lives on PdfTab

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
        file_menu = self.menuBar().addMenu("&File")

        open_action = file_menu.addAction("&Open PDF...")
        open_action.triggered.connect(self._open_pdf)

        self._close_action = file_menu.addAction("&Close Tab")
        self._close_action.triggered.connect(self._close_tab)
        self._close_action.setEnabled(False)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

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
        self._tab_manager.tab_added.connect(self._connect_tab_signals)
        self._tab_manager.tab_closed.connect(lambda _: self._update_close_tab_action())

        new_tab_button = QToolButton()
        new_tab_button.setObjectName("NewTabButton")
        new_tab_button.setText("+")
        new_tab_button.setToolTip("New tab (Ctrl+T)")
        new_tab_button.clicked.connect(self._new_blank_tab)
        self._tab_manager.setCornerWidget(
            new_tab_button,
            Qt.Corner.TopRightCorner,
        )

        self._tab_manager.add_blank_tab()
        self.setCentralWidget(self._tab_manager)

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
        tab.preview_widget.page_changed.connect(self._on_preview_page_changed)
        tab.preview_widget.busy_changed.connect(self._on_preview_busy_changed)

    def _active_tab(self) -> PdfTab | None:
        return self._tab_manager.active_tab

    def _grid_belongs_to_active_tab(self, grid) -> bool:
        tab = self._active_tab()
        return tab is not None and grid is tab.thumbnail_grid

    def _new_blank_tab(self) -> None:
        tab = self._tab_manager.add_blank_tab()
        self._tab_manager.setCurrentWidget(tab)
        self._update_close_tab_action()

    def _switch_to_next_tab(self) -> None:
        count = self._tab_manager.count()
        if count <= 1:
            return
        self._tab_manager.setCurrentIndex((self._tab_manager.currentIndex() + 1) % count)

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
        if tab is None or tab.edit_model is None:
            return
        selection = tab.thumbnail_grid.selection_manager.selection
        if not selection:
            return
        count = len(selection)
        if not tab.delete_selected_pages():
            return
        self._tab_manager.update_tab_title(tab)
        self._update_delete_pages_action()
        self._update_move_pages_actions()
        self._deselect_all_action.setEnabled(False)
        if tab.edit_model.logical_count() == 0:
            self.statusBar().showMessage("All pages deleted")
        else:
            noun = "page" if count == 1 else "pages"
            self.statusBar().showMessage(f"Deleted {count} {noun}")

    def _move_selected_pages_up(self) -> None:
        tab = self._active_tab()
        if tab is None or tab.edit_model is None:
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
        if tab is None or tab.edit_model is None:
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
        if tab is None or tab.loader is None:
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
        if tab.loader is not None:
            selection = tab.thumbnail_grid.selection_manager.selection
            if selection:
                self._on_selection_changed(selection)
            else:
                self.statusBar().showMessage(f"Loaded {tab.loader.page_count} pages")

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
        if tab is None or tab.loader is None or not tab.is_preview_visible():
            return
        page = tab.preview_widget.current_page + 1
        total = tab.loader.page_count
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
        if tab is None or tab.loader is None:
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
        if tab is None or tab.loader is None or tab.pdf_path is None:
            self.setWindowTitle(self.APP_TITLE)
            return
        filename = Path(tab.pdf_path).name
        count = tab.loader.page_count
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

        for path in paths:
            tab = self._tab_manager.add_blank_tab()
            self._load_pdf(path, tab=tab)
        self._tab_manager.setCurrentIndex(self._tab_manager.count() - 1)

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
            return

        choice = self._ask_open_target(path)
        if choice == "current":
            self._load_pdf(path, tab=active)
        elif choice == "new":
            tab = self._tab_manager.add_blank_tab()
            self._tab_manager.setCurrentWidget(tab)
            self._load_pdf(path, tab=tab)

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
        cancel_button = message.addButton(
            QMessageBox.StandardButton.Cancel,
        )
        message.exec()
        clicked = message.clickedButton()
        if clicked is cancel_button:
            return None
        if clicked is current_button:
            return "current"
        if clicked is new_button:
            return "new"
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
            self.statusBar().showMessage(f"Loading {loader.page_count} pages…")

    def _close_tab(self) -> None:
        if self._is_only_blank_tab():
            return
        index = self._tab_manager.currentIndex()
        if index >= 0:
            self._tab_manager.close_tab(index)
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
        if tab is not None and tab.loader is not None:
            selection = tab.thumbnail_grid.selection_manager.selection
            if selection:
                self._on_selection_changed(selection)
            else:
                self.statusBar().showMessage(
                    f"Loaded {tab.loader.page_count} pages"
                )

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
        elif tab.loader is not None and not self._progress_bar.isVisible():
            self.statusBar().showMessage(f"Loaded {tab.loader.page_count} pages")

    def _on_preview_busy_changed(self, busy: bool, message: str) -> None:
        tab = self._active_tab()
        if tab is None or self.sender() is not tab.preview_widget:
            return
        if busy and message:
            self.statusBar().showMessage(message)
        elif tab.loader is not None:
            page = tab.preview_widget.current_page + 1
            total = tab.loader.page_count
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
        pass  # TODO: confirm if there are unsaved operations
        QApplication.instance().removeEventFilter(self)
        for index in range(self._tab_manager.count()):
            widget = self._tab_manager.widget(index)
            if isinstance(widget, PdfTab):
                widget.close_loader()
        self._temp_manager.cleanup()
        super().closeEvent(event)
