from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.jobs.credentials import RuntimeCredentials
from pagedrop.core.pdf_loader import (
    PdfEmptyError,
    PdfLoadError,
    PdfLoader,
    PdfPasswordError,
    PdfPasswordRequiredError,
)
from pagedrop.core.pdf_merge import PdfMergeModel
from pagedrop.core.pdf_service import FITZ_LOCK
from pagedrop.core.pdf_writer import merge_pdf_files
from pagedrop.core.supported_formats import is_pdf_path
from pagedrop.ui.busy_overlay import BusyOverlay, ToastOverlay
from pagedrop.ui.dialogs import prompt_discard_file_list, prompt_pdf_password
from pagedrop.ui.job_chrome import explain_busy_running
from pagedrop.ui.keyboard_nav import (
    enable_toolbar_keyboard_navigation,
    set_content_tab_order,
)
from pagedrop.ui.merge_file_grid import MergeFileGrid
from pagedrop.ui.page_preview import PagePreviewWidget
from pagedrop.ui.result_actions import (
    ResultActionsBar,
    open_in_editor,
    preview_pdf,
    show_in_folder,
)
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_THUMBNAIL_WIDTH,
    MIN_THUMBNAIL_WIDTH,
    ZOOM_WHEEL_STEP,
)
from pagedrop.ui.tool_page import StatusFooter
from pagedrop.ui.zoom_controls import ZoomControls

_PREVIEW_FOOTER_HINT = (
    "← → change page · Ctrl+scroll zoom · Esc back to grid"
)

# Show a progress dialog once folder validation exceeds this many candidates.
_FOLDER_PROGRESS_THRESHOLD = 8


class _MergeWorker(QRunnable):
    """Whole-file merge off the UI thread (see core.thread_policy)."""

    class Signals(QObject):
        succeeded = pyqtSignal(str)
        failed = pyqtSignal(str)

    def __init__(
        self,
        file_paths: list[str],
        output_path: str,
        *,
        passwords: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._file_paths = file_paths
        self._output_path = output_path
        self._passwords = passwords
        self.setAutoDelete(True)

    def run(self) -> None:
        # Paths only; FITZ_LOCK around fitz merge; pool max 1.
        try:
            with FITZ_LOCK:
                merge_pdf_files(
                    self._file_paths,
                    self._output_path,
                    passwords=self._passwords,
                )
        except PdfLoadError as exc:
            self.signals.failed.emit(f"Could not read a source PDF:\n{exc}")
        except OSError as exc:
            self.signals.failed.emit(f"Could not write PDF:\n{exc}")
        except Exception as exc:
            self.signals.failed.emit(f"Could not merge PDFs:\n{exc}")
        else:
            self.signals.succeeded.emit(self._output_path)


class MergeWindow(QWidget):
    WINDOW_TITLE = "Merge PDFs"
    PAGE_ID = "merge"

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        editor: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.tool_page_id = self.PAGE_ID
        self._editor = editor
        self._model = PdfMergeModel()
        self._page_counts: dict[str, int] = {}
        self._credentials = RuntimeCredentials()
        self._preview_loader: PdfLoader | None = None
        self._merging = False
        self._merge_pool = QThreadPool(self)
        self._merge_pool.setMaxThreadCount(1)
        self._status = StatusFooter()

        self.setWindowTitle(self.WINDOW_TITLE)
        self.setObjectName("MergeWindow")
        self.setMinimumSize(640, 480)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._build_central_widget()
        # Toolbar must sit above the stack: insert at top after stack exists.
        self._build_toolbar()
        self._root.insertWidget(0, self._toolbar)
        self._result_bar = ResultActionsBar()
        self._root.addWidget(self._result_bar)
        self._root.addWidget(self._status)
        self._toast = ToastOverlay(self)
        self._connect_signals()
        self._update_actions()
        self._update_status()

    @property
    def tab_title(self) -> str:
        return self.WINDOW_TITLE

    def statusBar(self) -> StatusFooter:  # noqa: N802
        return self._status

    def set_editor(self, editor: QWidget | None) -> None:
        self._editor = editor

    @property
    def editor(self) -> QWidget | None:
        return self._editor

    def _build_central_widget(self) -> None:
        self._stack = QStackedWidget()
        self._stack.setObjectName("MergeContentStack")

        self._file_grid = MergeFileGrid()
        self._file_grid.set_password_lookup(self._credentials.get)
        self._preview_widget = PagePreviewWidget()
        self._preview_widget.set_footer_hint(_PREVIEW_FOOTER_HINT)

        self._stack.addWidget(self._file_grid)
        self._stack.addWidget(self._preview_widget)
        self._root.addWidget(self._stack, stretch=1)

        self._busy_overlay = BusyOverlay(self._stack)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Merge", self)
        toolbar.setMovable(False)
        self._toolbar = toolbar

        def tip(action, text: str) -> None:
            action.setToolTip(text)
            action.setStatusTip(text)

        self._back_to_list_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack),
            "Back to grid",
        )
        self._back_to_list_action.triggered.connect(self._close_preview)
        self._back_to_list_action.setVisible(False)
        tip(self._back_to_list_action, "Return to file grid (Esc)")

        self._add_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Add PDFs",
        )
        self._add_action.triggered.connect(self._add_pdfs)
        tip(self._add_action, "Add PDF files to merge")

        self._add_folder_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            "Add folder…",
        )
        self._add_folder_action.triggered.connect(self._add_folder)
        tip(self._add_folder_action, "Add all PDFs from a folder")

        self._remove_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon),
            "Remove",
        )
        self._remove_action.triggered.connect(self._remove_selected)
        tip(self._remove_action, "Remove selected files")

        self._move_up_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp),
            "Move up",
        )
        self._move_up_action.triggered.connect(self._move_up)
        tip(self._move_up_action, "Move selected files up")

        self._move_down_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown),
            "Move down",
        )
        self._move_down_action.triggered.connect(self._move_down)
        tip(self._move_down_action, "Move selected files down")

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
        tip(self._merge_action, "Merge files into one PDF")
        merge_button = toolbar.widgetForAction(self._merge_action)
        if merge_button is not None:
            merge_button.setObjectName("ToolbarPrimary")

        enable_toolbar_keyboard_navigation(toolbar)
        set_content_tab_order(toolbar, self._stack, status_bar=self.statusBar())

    def _connect_signals(self) -> None:
        self._file_grid.selection_changed.connect(self._update_actions)
        self._file_grid.preview_requested.connect(self._open_preview)
        self._file_grid.files_dropped.connect(self._add_paths)
        self._file_grid.files_reordered.connect(self._on_files_reordered)
        self._file_grid.zoom_changed.connect(self._on_zoom_changed)
        self._file_grid.rendering_error.connect(self._on_thumbnail_failed)
        self._zoom_controls.zoom_requested.connect(self._file_grid.set_thumbnail_zoom)
        self._zoom_controls.reset_requested.connect(
            lambda: self._file_grid.set_thumbnail_zoom(DEFAULT_THUMBNAIL_WIDTH)
        )
        self._preview_widget.page_changed.connect(self._update_status)
        self._preview_widget.closed.connect(self._close_preview)
        self._result_bar.preview_requested.connect(self._on_preview_result)
        self._result_bar.open_in_editor_requested.connect(self._on_open_result)
        self._result_bar.show_in_folder_requested.connect(self._on_show_folder)
        # ponytail: whole-file merge has no CancelToken — Cancel stays hidden;
        # Escape/close explain "still running…". Upgrade: cancel in merge_pdf_files.
        self._busy_overlay.escape_blocked.connect(self._explain_busy)

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
        self._add_folder_action.setVisible(not in_preview)
        self._remove_action.setVisible(not in_preview)
        self._move_up_action.setVisible(not in_preview)
        self._move_down_action.setVisible(not in_preview)
        self._merge_action.setVisible(not in_preview)
        self._zoom_controls.setVisible(not in_preview)

        toolbar_enabled = not self._merging
        self._add_action.setEnabled(toolbar_enabled)
        self._add_folder_action.setEnabled(toolbar_enabled)
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

    def _on_thumbnail_failed(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _open_preview(self, path: str) -> None:
        if self._preview_loader is not None:
            self._preview_loader.close()
            self._preview_loader = None

        filename = Path(path).name
        password = self._credentials.get(path)
        try:
            loader = PdfLoader(path, password=password)
        except PdfEmptyError:
            QMessageBox.warning(
                self,
                "Preview",
                f"{filename} has no pages.",
            )
            return
        except PdfLoadError as exc:
            QMessageBox.critical(
                self,
                "Preview",
                f"Could not open {filename}:\n{exc}",
            )
            return

        self._preview_loader = loader
        self._preview_widget.reset_zoom_to_fit()
        self._preview_widget.set_loader(loader, password=password)
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
            self.statusBar().showMessage(f"Preview · page {page} of {total}")
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
        self._model.clear()
        self._model.add_files(paths)

    def _on_files_reordered(self, paths: list[str]) -> None:
        self._sync_model_from_grid(paths)
        self._update_actions()
        self._update_status()

    def _validate_pdf(self, path: str) -> int | None:
        filename = Path(path).name
        password = self._credentials.get(path)
        while True:
            try:
                page_count = self._page_count(path, password=password)
            except PdfPasswordRequiredError:
                password = prompt_pdf_password(self, filename)
                if password is None:
                    return None
                continue
            except PdfPasswordError:
                password = prompt_pdf_password(self, filename, incorrect=True)
                if password is None:
                    return None
                continue
            except PdfEmptyError:
                QMessageBox.warning(
                    self,
                    "Add PDFs",
                    f"{filename} has no pages.",
                )
                return None
            except PdfLoadError as exc:
                QMessageBox.critical(
                    self,
                    "Add PDFs",
                    f"Could not open {filename}:\n{exc}",
                )
                return None
            if password is not None:
                self._credentials.set(path, password)
            return page_count

    @staticmethod
    def _page_count(path: str, *, password: str | None = None) -> int:
        loader = PdfLoader(path, password=password)
        try:
            return loader.page_count
        finally:
            loader.close()

    def _add_paths(self, paths: list[str]) -> None:
        accepted: list[str] = []
        for path in paths:
            page_count = self._validate_pdf(path)
            if page_count is None:
                continue
            resolved = str(Path(path).resolve())
            password = self._credentials.get(path)
            if password is not None:
                self._credentials.set(resolved, password)
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

    def _discover_pdfs_in_folder(self, folder: str) -> list[str]:
        root = Path(folder)
        return sorted(
            str(path)
            for path in root.rglob("*")
            if path.is_file() and is_pdf_path(path)
        )

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Add folder",
            last_directory(),
        )
        if not folder:
            return
        remember_directory(folder)

        candidates = self._discover_pdfs_in_folder(folder)
        if not candidates:
            QMessageBox.information(
                self,
                "Add folder",
                "No PDF files found in that folder.",
            )
            return

        accepted, skipped, cancelled = self._validate_folder_candidates(candidates)
        if cancelled and not accepted:
            self.statusBar().showMessage("Add folder cancelled")
            return

        if accepted:
            self._model.add_files(accepted)
            self._refresh_grid()

        parts: list[str] = []
        if accepted:
            noun = "file" if len(accepted) == 1 else "files"
            parts.append(f"Added {len(accepted)} {noun}")
        if skipped:
            parts.append(f"skipped {len(skipped)}")
        if cancelled:
            parts.append("cancelled")
        self.statusBar().showMessage(", ".join(parts) if parts else "No files added")

        if skipped:
            preview = "\n".join(
                f"• {Path(path).name}: {reason}" for path, reason in skipped[:8]
            )
            extra = len(skipped) - 8
            if extra > 0:
                preview = f"{preview}\n…and {extra} more"
            QMessageBox.warning(
                self,
                "Add folder",
                f"Could not add {len(skipped)} PDF file(s):\n\n{preview}",
            )

    def _validate_folder_candidates(
        self, paths: list[str]
    ) -> tuple[list[str], list[tuple[str, str]], bool]:
        """Validate folder PDFs; returns (accepted, skipped, cancelled)."""
        accepted: list[str] = []
        skipped: list[tuple[str, str]] = []
        total = len(paths)
        progress: QProgressDialog | None = None
        if total >= _FOLDER_PROGRESS_THRESHOLD:
            progress = QProgressDialog(
                "Checking PDFs…",
                "Cancel",
                0,
                total,
                self,
            )
            progress.setWindowTitle("Add folder")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)

        cancelled = False
        for index, path in enumerate(paths):
            if progress is not None:
                progress.setValue(index)
                progress.setLabelText(f"Checking {Path(path).name}…")
                QApplication.processEvents()
                if progress.wasCanceled():
                    cancelled = True
                    break

            password = self._credentials.get(path)
            while True:
                try:
                    page_count = self._page_count(path, password=password)
                    break
                except PdfPasswordRequiredError:
                    password = prompt_pdf_password(self, Path(path).name)
                    if password is None:
                        skipped.append((path, "password cancelled"))
                        page_count = None
                        break
                except PdfPasswordError:
                    password = prompt_pdf_password(
                        self, Path(path).name, incorrect=True
                    )
                    if password is None:
                        skipped.append((path, "password cancelled"))
                        page_count = None
                        break
                except PdfEmptyError:
                    skipped.append((path, "no pages"))
                    page_count = None
                    break
                except PdfLoadError as exc:
                    skipped.append((path, str(exc)))
                    page_count = None
                    break
            if page_count is None:
                continue

            resolved = str(Path(path).resolve())
            if password is not None:
                self._credentials.set(resolved, password)
            self._page_counts[resolved] = page_count
            accepted.append(resolved)

        if progress is not None:
            progress.setValue(total if not cancelled else progress.value())
            progress.close()

        return accepted, skipped, cancelled

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
        self._result_bar.clear()
        self._busy_overlay.show_message("Merging PDFs…")
        self.statusBar().showMessage("Merging PDFs…")
        self._update_actions()

        worker = _MergeWorker(
            file_paths,
            output_path,
            passwords=self._credentials.snapshot() or None,
        )
        worker.signals.succeeded.connect(self._on_merge_succeeded)
        worker.signals.failed.connect(self._on_merge_failed)
        self._merge_pool.start(worker)

    def _explain_busy(self) -> None:
        explain_busy_running(
            status_bar=self.statusBar(),
            toast=self._toast,
            label="Merge",
        )

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
        status = f"Merged {file_count} {noun} to {filename}"
        self.statusBar().showMessage(status)
        self._toast.show_toast(status, kind="success")
        self._result_bar.show_for(path, message=status)

    def _on_merge_failed(self, message: str) -> None:
        self._finish_merge()
        self._result_bar.clear()
        self.statusBar().showMessage("Merge failed")
        self._toast.show_toast("Merge failed", kind="error")
        QMessageBox.critical(self, "Merge PDFs", message)

    def _on_preview_result(self, path: str) -> None:
        preview_pdf(path, parent=self)

    def _on_open_result(self, path: str) -> None:
        editor = self._editor
        if editor is None:
            self._toast.show_toast("No editor window available", kind="error")
            return
        try:
            open_in_editor(path, editor)
        except Exception as exc:
            QMessageBox.critical(
                self,
                self.WINDOW_TITLE,
                f"Could not open in editor:\n{exc}",
            )
            return
        self._toast.show_toast(f"Opened {Path(path).name}", kind="success")

    def _on_show_folder(self, path: str) -> None:
        if not show_in_folder(path):
            QMessageBox.warning(
                self,
                self.WINDOW_TITLE,
                "Could not open the folder for this file.",
            )
            return
        self._toast.show_toast("Opened folder", kind="info")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_busy_overlay"):
            parent = self._busy_overlay.parentWidget()
            if parent is not None:
                self._busy_overlay.setGeometry(parent.rect())

    def _prompt_discard_file_list(self) -> str:
        """Return ``discard`` or ``cancel``."""
        return prompt_discard_file_list(
            self,
            window_title=self.WINDOW_TITLE,
            informative_text="Closing will remove all files from the merge list.",
        )

    def _clear_file_list(self) -> None:
        self._model.clear()
        self._page_counts.clear()
        self._credentials.clear()
        if self._is_preview_visible():
            self._close_preview()
        self._refresh_grid()

    def request_close(self) -> bool:
        if self._merging:
            self._explain_busy()
            return False

        if self._model.file_count() > 0:
            if self._prompt_discard_file_list() != "discard":
                return False
            self._clear_file_list()

        if self._preview_loader is not None:
            self._preview_loader.close()
            self._preview_loader = None

        self._file_grid.cancel_rendering()
        return True

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self.request_close():
            event.ignore()
            return
        super().closeEvent(event)
