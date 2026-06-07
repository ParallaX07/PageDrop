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
    QWidget,
)

from pagedrop.core.pdf_loader import (
    PdfEmptyError,
    PdfLoadError,
    PdfLoader,
)
from pagedrop.ui.page_preview import PagePreviewDialog
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_THUMBNAIL_WIDTH,
    MIN_THUMBNAIL_WIDTH,
    ZOOM_WHEEL_STEP,
)
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.ui.zoom_controls import ZoomControls
from pagedrop.utils.temp_manager import TempManager


class MainWindow(QMainWindow):
    APP_TITLE = "PageDrop"

    def __init__(self) -> None:
        super().__init__()
        self.current_pdf_path: str | None = None
        self._loader: PdfLoader | None = None
        self._preview_dialog: PagePreviewDialog | None = None
        self._temp_manager = TempManager()

        self.setWindowTitle(self.APP_TITLE)
        self.setMinimumSize(720, 480)
        self.resize(960, 680)

        self._build_menu()
        self._build_toolbar()
        self._build_central_widget()
        self._build_status_widgets()
        self._build_selection_shortcuts()
        QApplication.instance().installEventFilter(self)
        self.statusBar().showMessage("Ready")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_action = file_menu.addAction("&Open PDF...")
        open_action.triggered.connect(self._open_pdf)

        self._close_action = file_menu.addAction("&Close PDF")
        self._close_action.triggered.connect(self._close_pdf)
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

        self._preview_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Preview",
        )
        self._preview_action.setToolTip("Preview selected page (double-click a card)")
        self._preview_action.triggered.connect(self._open_preview)
        self._preview_action.setEnabled(False)

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

    def _build_central_widget(self) -> None:
        self._thumbnail_grid = ThumbnailGrid(temp_manager=self._temp_manager)
        self._thumbnail_grid.rendering_started.connect(self._on_rendering_started)
        self._thumbnail_grid.rendering_progress.connect(self._on_rendering_progress)
        self._thumbnail_grid.rendering_finished.connect(self._on_rendering_finished)
        self._thumbnail_grid.rendering_error.connect(self._on_rendering_error)
        self._thumbnail_grid.selection_changed.connect(self._on_selection_changed)
        self._thumbnail_grid.preview_requested.connect(self._open_preview_at)
        self._thumbnail_grid.zoom_changed.connect(self._on_zoom_changed)
        self._thumbnail_grid.zoom_changed.connect(self._zoom_controls.set_value)
        self._zoom_controls.zoom_requested.connect(
            self._thumbnail_grid.set_thumbnail_zoom
        )
        self.setCentralWidget(self._thumbnail_grid)

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

        clear_selection = QAction(self)
        clear_selection.setShortcut(QKeySequence.StandardKey.Cancel)
        clear_selection.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        clear_selection.triggered.connect(self._clear_selection)
        self.addAction(clear_selection)

    def _select_all_pages(self) -> None:
        self._thumbnail_grid.selection_manager.select_all()

    def _clear_selection(self) -> None:
        self._thumbnail_grid.selection_manager.clear()

    def _preview_start_page(self) -> int:
        selection = self._thumbnail_grid.selection_manager.selection
        if selection:
            return min(selection)
        return 0

    def _open_preview(self) -> None:
        if self._loader is None:
            return
        self._open_preview_at(self._preview_start_page())

    def _open_preview_at(self, page_index: int) -> None:
        if self._loader is None:
            return

        if self._preview_dialog is not None and self._preview_dialog.isVisible():
            self._preview_dialog.close()

        dialog = PagePreviewDialog(
            self._loader,
            start_page=page_index,
            on_page_changed=self._on_preview_page_changed,
            parent=self,
        )
        dialog.finished.connect(self._on_preview_closed)
        self._preview_dialog = dialog
        dialog.showMaximized()

    def _on_preview_page_changed(self, page_index: int) -> None:
        self._thumbnail_grid.selection_manager.select_single(page_index)

    def _on_preview_closed(self) -> None:
        self._preview_dialog = None

    def _on_zoom_changed(self, thumbnail_width_px: int) -> None:
        if self._loader is not None:
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

        if event.matches(QKeySequence.StandardKey.Cancel):
            if self._thumbnail_grid.selection_manager.selection:
                self._clear_selection()
                return True
        elif event.matches(QKeySequence.StandardKey.SelectAll) and self._loader is not None:
            self._select_all_pages()
            return True
        elif self._loader is not None and event.text() in {"+", "="}:
            self._thumbnail_grid.zoom_by(ZOOM_WHEEL_STEP)
            return True
        elif self._loader is not None and event.text() == "-":
            self._thumbnail_grid.zoom_by(-ZOOM_WHEEL_STEP)
            return True

        return super().eventFilter(obj, event)

    def _open_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open PDF",
            "",
            "PDF Files (*.pdf);;All Files (*)",
        )
        if not path:
            return

        self._load_pdf(path)

    def _load_pdf(self, path: str) -> None:
        self._thumbnail_grid.cancel_rendering()

        if self._loader is not None:
            self._thumbnail_grid.clear()
            self._loader.close()
            self._loader = None

        filename = Path(path).name

        try:
            loader = PdfLoader(path)
        except PdfEmptyError:
            QMessageBox.warning(
                self,
                "Open PDF",
                f"{filename} has no pages.",
            )
            self._reset_ui()
            self.statusBar().showMessage("Ready")
            return
        except PdfLoadError as exc:
            QMessageBox.critical(
                self,
                "Open PDF",
                f"Could not open {filename}:\n{exc}",
            )
            self._reset_ui()
            self.statusBar().showMessage("Ready")
            return

        self._loader = loader
        self.current_pdf_path = path

        self.setWindowTitle(f"{self.APP_TITLE} — {filename}")
        self._filename_label.setText(filename)
        self._filename_label.setProperty("active", True)
        self._filename_label.style().unpolish(self._filename_label)
        self._filename_label.style().polish(self._filename_label)
        self._close_action.setEnabled(True)
        self._preview_action.setEnabled(True)
        self._zoom_controls.setEnabled(True)
        self._zoom_controls.set_value(self._thumbnail_grid.thumbnail_width_px)
        self.statusBar().showMessage(f"Loading {loader.page_count} pages…")
        self._thumbnail_grid.load_pdf(loader)

    def _close_pdf(self) -> None:
        self._thumbnail_grid.clear()
        if self._loader is not None:
            self._loader.close()
            self._loader = None

        self.current_pdf_path = None
        self._reset_ui()
        self.statusBar().showMessage("PDF closed")

    def _reset_ui(self) -> None:
        self.setWindowTitle(self.APP_TITLE)
        self._filename_label.setText("No file open")
        self._filename_label.setProperty("active", False)
        self._filename_label.style().unpolish(self._filename_label)
        self._filename_label.style().polish(self._filename_label)
        self._close_action.setEnabled(False)
        self._preview_action.setEnabled(False)
        self._zoom_controls.setEnabled(False)
        self._zoom_controls.set_value(DEFAULT_THUMBNAIL_WIDTH)
        self._progress_bar.hide()

    def _on_rendering_started(self, total_pages: int) -> None:
        self._progress_bar.setRange(0, total_pages)
        self._progress_bar.setValue(0)
        self._progress_bar.show()

    def _on_rendering_progress(self, current: int, total: int) -> None:
        self._progress_bar.setValue(current)
        self.statusBar().showMessage(f"Rendering page {current} of {total}…")

    def _on_rendering_finished(self) -> None:
        self._progress_bar.hide()
        if self._loader is not None:
            if self._thumbnail_grid.selection_manager.selection:
                self._on_selection_changed(
                    self._thumbnail_grid.selection_manager.selection
                )
            else:
                self.statusBar().showMessage(f"Loaded {self._loader.page_count} pages")

    def _on_rendering_error(self, message: str) -> None:
        self._progress_bar.hide()
        QMessageBox.critical(
            self,
            "Render Pages",
            f"Could not render thumbnails:\n{message}",
        )
        self.statusBar().showMessage("Rendering failed")

    def _on_selection_changed(self, selection: set[int]) -> None:
        if selection:
            count = len(selection)
            noun = "page" if count == 1 else "pages"
            self.statusBar().showMessage(f"{count} {noun} selected")
        else:
            self.statusBar().showMessage("No selection")

    def closeEvent(self, event: QCloseEvent) -> None:
        pass  # TODO: confirm if there are unsaved operations
        if self._preview_dialog is not None:
            self._preview_dialog.close()
        QApplication.instance().removeEventFilter(self)
        self._thumbnail_grid.clear()
        if self._loader is not None:
            self._loader.close()
        self._temp_manager.cleanup()
        super().closeEvent(event)
