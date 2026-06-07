from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStyle,
    QToolBar,
    QWidget,
)

from pagedrop.core.pdf_loader import PdfEmptyError, PdfLoadError, PdfLoader
from pagedrop.core.pdf_merge import PdfMergeModel
from pagedrop.core.pdf_writer import merge_pdf_files
from pagedrop.ui.busy_overlay import BusyOverlay
from pagedrop.ui.merge_file_grid import MergeFileGrid
from pagedrop.ui.page_preview import PagePreviewWidget
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_THUMBNAIL_WIDTH,
    MIN_THUMBNAIL_WIDTH,
    ZOOM_WHEEL_STEP,
)
from pagedrop.ui.zoom_controls import ZoomControls

_PREVIEW_FOOTER_HINT = (
    "← → change page · Ctrl+scroll zoom · Esc back to grid"
)


class _MergeWorker(QRunnable):
    class Signals(QObject):
        succeeded = pyqtSignal(str)
        failed = pyqtSignal(str)

    def __init__(self, file_paths: list[str], output_path: str) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._file_paths = file_paths
        self._output_path = output_path
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            merge_pdf_files(self._file_paths, self._output_path)
        except PdfLoadError as exc:
            self.signals.failed.emit(f"Could not read a source PDF:\n{exc}")
        except OSError as exc:
            self.signals.failed.emit(f"Could not write PDF:\n{exc}")
        except Exception as exc:
            self.signals.failed.emit(f"Could not merge PDFs:\n{exc}")
        else:
            self.signals.succeeded.emit(self._output_path)


class MergeWindow(QMainWindow):
    WINDOW_TITLE = "Merge PDFs"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = PdfMergeModel()
        self._page_counts: dict[str, int] = {}
        self._preview_loader: PdfLoader | None = None
        self._merging = False
        self._merge_pool = QThreadPool(self)
        self._merge_pool.setMaxThreadCount(1)

        self.setWindowTitle(self.WINDOW_TITLE)
        self.setMinimumSize(640, 480)
        self.resize(760, 560)

        self._build_central_widget()
        self._build_toolbar()
        self._connect_signals()
        self._update_actions()
        self._update_status()

    def _build_central_widget(self) -> None:
        self._stack = QStackedWidget()
        self._stack.setObjectName("MergeContentStack")

        self._file_grid = MergeFileGrid()
        self._preview_widget = PagePreviewWidget()
        self._preview_widget.set_footer_hint(_PREVIEW_FOOTER_HINT)

        self._stack.addWidget(self._file_grid)
        self._stack.addWidget(self._preview_widget)
        self.setCentralWidget(self._stack)

        self._busy_overlay = BusyOverlay(self._stack)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Merge", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._back_to_list_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack),
            "Back to grid",
        )
        self._back_to_list_action.triggered.connect(self._close_preview)
        self._back_to_list_action.setVisible(False)

        self._add_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Add PDFs",
        )
        self._add_action.triggered.connect(self._add_pdfs)

        self._remove_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon),
            "Remove",
        )
        self._remove_action.triggered.connect(self._remove_selected)

        self._move_up_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp),
            "Move Up",
        )
        self._move_up_action.triggered.connect(self._move_up)

        self._move_down_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown),
            "Move Down",
        )
        self._move_down_action.triggered.connect(self._move_down)

        from PyQt6.QtWidgets import QSizePolicy

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

        self._merge_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "Merge",
        )
        self._merge_action.triggered.connect(self._merge_pdfs)
        merge_button = toolbar.widgetForAction(self._merge_action)
        if merge_button is not None:
            merge_button.setObjectName("ToolbarPrimary")

    def _connect_signals(self) -> None:
        self._file_grid.selection_changed.connect(self._update_actions)
        self._file_grid.preview_requested.connect(self._open_preview)
        self._file_grid.files_dropped.connect(self._add_paths)
        self._file_grid.files_reordered.connect(self._on_files_reordered)
        self._file_grid.zoom_changed.connect(self._on_zoom_changed)
        self._zoom_controls.zoom_requested.connect(self._file_grid.set_thumbnail_zoom)
        self._preview_widget.page_changed.connect(self._update_status)
        self._preview_widget.closed.connect(self._close_preview)

    def _selected_indices(self) -> list[int]:
        return self._file_grid.selected_indices()

    def _can_move_up(self) -> bool:
        indices = self._selected_indices()
        return bool(indices) and indices[0] > 0

    def _can_move_down(self) -> bool:
        indices = self._selected_indices()
        count = self._model.file_count()
        return bool(indices) and indices[-1] < count - 1

    def _update_actions(self) -> None:
        in_preview = self._is_preview_visible()
        has_selection = bool(self._selected_indices())
        has_files = self._model.file_count() > 0

        self._back_to_list_action.setVisible(in_preview)
        self._add_action.setVisible(not in_preview)
        self._remove_action.setVisible(not in_preview)
        self._move_up_action.setVisible(not in_preview)
        self._move_down_action.setVisible(not in_preview)
        self._merge_action.setVisible(not in_preview)
        self._zoom_controls.setVisible(not in_preview)

        toolbar_enabled = not self._merging
        self._add_action.setEnabled(toolbar_enabled)
        self._remove_action.setEnabled(has_selection and toolbar_enabled)
        self._move_up_action.setEnabled(self._can_move_up() and toolbar_enabled)
        self._move_down_action.setEnabled(self._can_move_down() and toolbar_enabled)
        self._merge_action.setEnabled(has_files and not self._merging)
        self._zoom_controls.setEnabled(has_files and not in_preview and not self._merging)

    def _is_preview_visible(self) -> bool:
        return self._stack.currentWidget() is self._preview_widget

    def _on_zoom_changed(self, thumbnail_width_px: int) -> None:
        self._zoom_controls.set_value(thumbnail_width_px)
        self.statusBar().showMessage(f"Thumbnail size: {thumbnail_width_px} px")

    def _open_preview(self, path: str) -> None:
        if self._preview_loader is not None:
            self._preview_loader.close()
            self._preview_loader = None

        filename = Path(path).name
        try:
            loader = PdfLoader(path)
        except PdfEmptyError:
            QMessageBox.warning(
                self,
                "Preview PDF",
                f"{filename} has no pages.",
            )
            return
        except PdfLoadError as exc:
            QMessageBox.critical(
                self,
                "Preview PDF",
                f"Could not open {filename}:\n{exc}",
            )
            return

        self._preview_loader = loader
        self._preview_widget.reset_zoom_to_fit()
        self._preview_widget.set_loader(loader)
        self._preview_widget.show_page(0)
        self._stack.setCurrentWidget(self._preview_widget)
        self._update_actions()
        self._update_status()

    def _close_preview(self) -> None:
        if not self._is_preview_visible():
            return
        self._stack.setCurrentWidget(self._file_grid)
        if self._preview_loader is not None:
            self._preview_loader.close()
            self._preview_loader = None
        self._preview_widget.set_loader(None)
        self._update_actions()
        self._update_status()

    def _update_status(self) -> None:
        if self._is_preview_visible() and self._preview_loader is not None:
            page = self._preview_widget.current_page + 1
            total = self._preview_loader.page_count
            self.statusBar().showMessage(f"Preview — page {page} of {total}")
            return

        count = self._model.file_count()
        if count == 0:
            self.statusBar().showMessage("No files")
        elif count == 1:
            self.statusBar().showMessage("1 file")
        else:
            self.statusBar().showMessage(f"{count} files")

    def _selected_paths(self) -> set[str]:
        return {
            self._model.path_at(index)
            for index in self._selected_indices()
            if 0 <= index < self._model.file_count()
        }

    def _refresh_grid(self, *, preserve_selection: list[int] | None = None) -> None:
        if preserve_selection is not None:
            selected_paths = {
                self._model.path_at(index)
                for index in preserve_selection
                if 0 <= index < self._model.file_count()
            }
        else:
            selected_paths = self._selected_paths()

        paths = [self._model.path_at(i) for i in range(self._model.file_count())]
        self._file_grid.set_files(
            paths,
            self._page_counts,
            selected_paths=selected_paths,
        )
        self._zoom_controls.set_value(self._file_grid.thumbnail_width_px)
        self._update_actions()
        self._update_status()

    def _sync_model_from_grid(self, paths: list[str]) -> None:
        while self._model.file_count() > 0:
            self._model.remove_at(0)
        self._model.add_files(paths)

    def _on_files_reordered(self, paths: list[str]) -> None:
        self._sync_model_from_grid(paths)
        self._update_actions()
        self._update_status()

    def _validate_pdf(self, path: str) -> int | None:
        filename = Path(path).name
        try:
            loader = PdfLoader(path)
            count = loader.page_count
            loader.close()
            return count
        except PdfEmptyError:
            QMessageBox.warning(
                self,
                "Add PDF",
                f"{filename} has no pages.",
            )
            return None
        except PdfLoadError as exc:
            QMessageBox.critical(
                self,
                "Add PDF",
                f"Could not open {filename}:\n{exc}",
            )
            return None

    def _add_paths(self, paths: list[str]) -> None:
        accepted: list[str] = []
        for path in paths:
            page_count = self._validate_pdf(path)
            if page_count is None:
                continue
            resolved = str(Path(path).resolve())
            self._page_counts[resolved] = page_count
            accepted.append(resolved)

        if not accepted:
            return

        self._model.add_files(accepted)
        self._refresh_grid()
        noun = "file" if len(accepted) == 1 else "files"
        self.statusBar().showMessage(f"Added {len(accepted)} {noun}")

    def _add_pdfs(self) -> None:
        start_dir = last_directory()
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add PDFs",
            start_dir,
            "PDF Files (*.pdf);;All Files (*)",
        )
        if not paths:
            return
        remember_directory(paths[0])
        self._add_paths(paths)

    def _remove_selected(self) -> None:
        indices = self._selected_indices()
        if not indices:
            return
        self._model.remove_indices(indices)
        self._refresh_grid()
        noun = "file" if len(indices) == 1 else "files"
        self.statusBar().showMessage(f"Removed {len(indices)} {noun}")

    def _move_up(self) -> None:
        indices = self._selected_indices()
        if not indices or not self._can_move_up():
            return
        self._model.move_up(indices)
        self._refresh_grid(preserve_selection=indices)

    def _move_down(self) -> None:
        indices = self._selected_indices()
        if not indices or not self._can_move_down():
            return
        self._model.move_down(indices)
        self._refresh_grid(preserve_selection=indices)

    def _default_merge_path(self) -> str:
        first_path = Path(self._model.path_at(0))
        return str(first_path.parent / f"{first_path.stem}_merged.pdf")

    def _merge_pdfs(self) -> None:
        if self._model.file_count() == 0:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Merge PDFs",
            self._default_merge_path(),
            "PDF Files (*.pdf);;All Files (*)",
        )
        if not path:
            return

        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"

        self._start_merge(self._model.all_paths(), path)

    def _start_merge(self, file_paths: list[str], output_path: str) -> None:
        self._merging = True
        self._busy_overlay.show_message("Merging PDFs…")
        self.statusBar().showMessage("Merging PDFs…")
        self._update_actions()

        worker = _MergeWorker(file_paths, output_path)
        worker.signals.succeeded.connect(self._on_merge_succeeded)
        worker.signals.failed.connect(self._on_merge_failed)
        self._merge_pool.start(worker)

    def _finish_merge(self) -> None:
        self._merging = False
        self._busy_overlay.hide_overlay()
        self._update_actions()

    def _on_merge_succeeded(self, path: str) -> None:
        self._finish_merge()
        remember_directory(path)
        filename = Path(path).name
        file_count = self._model.file_count()
        noun = "file" if file_count == 1 else "files"
        self.statusBar().showMessage(f"Merged {file_count} {noun} to {filename}")

    def _on_merge_failed(self, message: str) -> None:
        self._finish_merge()
        self.statusBar().showMessage("Merge failed")
        QMessageBox.critical(self, "Merge PDFs", message)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_busy_overlay"):
            parent = self._busy_overlay.parentWidget()
            if parent is not None:
                self._busy_overlay.setGeometry(parent.rect())

    def _prompt_discard_file_list(self) -> str:
        """Return ``discard`` or ``cancel``."""
        if os.environ.get("PAGEDROP_TESTING") == "1":
            return "discard"

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Question)
        message.setWindowTitle(self.WINDOW_TITLE)
        message.setText("Discard file list?")
        message.setInformativeText(
            "Closing will remove all files from the merge list."
        )
        discard_button = message.addButton(
            "Discard",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        cancel_button = message.addButton(QMessageBox.StandardButton.Cancel)
        message.exec()
        if message.clickedButton() is discard_button:
            return "discard"
        return "cancel"

    def _clear_file_list(self) -> None:
        while self._model.file_count() > 0:
            self._model.remove_at(0)
        self._page_counts.clear()
        if self._is_preview_visible():
            self._close_preview()
        self._refresh_grid()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._merging:
            event.ignore()
            return

        if self._model.file_count() > 0:
            if self._prompt_discard_file_list() != "discard":
                event.ignore()
                return
            self._clear_file_list()

        if self._preview_loader is not None:
            self._preview_loader.close()
            self._preview_loader = None

        self._file_grid.cancel_rendering()
        super().closeEvent(event)
