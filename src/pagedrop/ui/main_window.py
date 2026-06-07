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
    QStyle,
    QToolBar,
)

from pagedrop.core.pdf_loader import (
    PdfEmptyError,
    PdfLoadError,
    PdfLoader,
)
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.utils.temp_manager import TempManager


class MainWindow(QMainWindow):
    APP_TITLE = "PageDrop"

    def __init__(self) -> None:
        super().__init__()
        self.current_pdf_path: str | None = None
        self._loader: PdfLoader | None = None
        self._temp_manager = TempManager()

        self.setWindowTitle(self.APP_TITLE)
        self.resize(900, 650)

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

        toolbar.addSeparator()

        self._filename_label = QLabel("No file open")
        self._filename_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        toolbar.addWidget(self._filename_label)

    def _build_central_widget(self) -> None:
        self._thumbnail_grid = ThumbnailGrid(temp_manager=self._temp_manager)
        self._thumbnail_grid.rendering_started.connect(self._on_rendering_started)
        self._thumbnail_grid.rendering_progress.connect(self._on_rendering_progress)
        self._thumbnail_grid.rendering_finished.connect(self._on_rendering_finished)
        self._thumbnail_grid.rendering_error.connect(self._on_rendering_error)
        self._thumbnail_grid.selection_changed.connect(self._on_selection_changed)
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
        self._close_action.setEnabled(True)
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
        self._close_action.setEnabled(False)
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
        QApplication.instance().removeEventFilter(self)
        self._thumbnail_grid.clear()
        if self._loader is not None:
            self._loader.close()
        self._temp_manager.cleanup()
        super().closeEvent(event)
