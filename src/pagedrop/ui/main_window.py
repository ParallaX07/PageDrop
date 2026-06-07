from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStyle,
    QToolBar,
)

from pagedrop.core.pdf_loader import (
    PdfLoadError,
    PdfLoader,
)
from pagedrop.ui.thumbnail_grid import ThumbnailGrid


class MainWindow(QMainWindow):
    APP_TITLE = "PageDrop"

    def __init__(self) -> None:
        super().__init__()
        self.current_pdf_path: str | None = None
        self._loader: PdfLoader | None = None

        self.setWindowTitle(self.APP_TITLE)
        self.resize(900, 650)

        self._build_menu()
        self._build_toolbar()
        self._build_central_widget()
        self._build_status_widgets()
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
        self._thumbnail_grid = ThumbnailGrid()
        self._thumbnail_grid.rendering_started.connect(self._on_rendering_started)
        self._thumbnail_grid.rendering_progress.connect(self._on_rendering_progress)
        self._thumbnail_grid.rendering_finished.connect(self._on_rendering_finished)
        self.setCentralWidget(self._thumbnail_grid)

    def _build_status_widgets(self) -> None:
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.hide()
        self.statusBar().addPermanentWidget(self._progress_bar)

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
        if self._loader is not None:
            self._thumbnail_grid.clear()
            self._loader.close()
            self._loader = None

        try:
            loader = PdfLoader(path)
        except PdfLoadError as exc:
            QMessageBox.critical(self, "Open PDF", str(exc))
            self._reset_ui()
            self.statusBar().showMessage("Ready")
            return

        self._loader = loader
        self.current_pdf_path = path

        filename = Path(path).name
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
            self.statusBar().showMessage(f"Loaded {self._loader.page_count} pages")

    def closeEvent(self, event: QCloseEvent) -> None:
        pass  # TODO: confirm if there are unsaved operations
        self._thumbnail_grid.clear()
        if self._loader is not None:
            self._loader.close()
        super().closeEvent(event)
