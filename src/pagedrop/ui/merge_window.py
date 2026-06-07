from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QListWidget,
    QListWidgetItem,
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
from pagedrop.ui.page_preview import PagePreviewWidget
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.thumbnail_grid import ThumbnailGrid

_PATH_ROLE = Qt.ItemDataRole.UserRole
_PREVIEW_FOOTER_HINT = (
    "← → change page · Ctrl+scroll zoom · Esc back to list"
)


class MergeFileListWidget(QListWidget):
    """File list with internal reordering and inbound PDF drops."""

    files_dropped = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MergeFileList")
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if ThumbnailGrid.pdf_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if ThumbnailGrid.pdf_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        paths = ThumbnailGrid.pdf_paths_from_mime(event.mimeData())
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class MergeWindow(QMainWindow):
    WINDOW_TITLE = "Merge PDFs"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = PdfMergeModel()
        self._page_counts: dict[str, int] = {}
        self._list_syncing = False
        self._preview_loader: PdfLoader | None = None

        self.setWindowTitle(self.WINDOW_TITLE)
        self.setMinimumSize(480, 360)
        self.resize(560, 480)

        self._build_central_widget()
        self._build_toolbar()
        self._connect_signals()
        self._update_actions()
        self._update_status()

    def _build_central_widget(self) -> None:
        self._stack = QStackedWidget()
        self._stack.setObjectName("MergeContentStack")

        self._list_widget = MergeFileListWidget()
        self._preview_widget = PagePreviewWidget()
        self._preview_widget.set_footer_hint(_PREVIEW_FOOTER_HINT)

        self._stack.addWidget(self._list_widget)
        self._stack.addWidget(self._preview_widget)
        self.setCentralWidget(self._stack)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Merge", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._back_to_list_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack),
            "Back to list",
        )
        self._back_to_list_action.triggered.connect(self._close_preview)
        self._back_to_list_action.setVisible(False)

        self._add_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Add PDFs…",
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

        self._merge_action = toolbar.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "Merge…",
        )
        self._merge_action.triggered.connect(self._merge_pdfs)
        merge_button = toolbar.widgetForAction(self._merge_action)
        if merge_button is not None:
            merge_button.setObjectName("ToolbarPrimary")

    def _connect_signals(self) -> None:
        self._list_widget.itemSelectionChanged.connect(self._update_actions)
        self._list_widget.itemDoubleClicked.connect(self._on_list_item_double_clicked)
        self._list_widget.files_dropped.connect(self._add_paths)
        self._list_widget.model().rowsMoved.connect(self._on_rows_moved)
        self._preview_widget.page_changed.connect(self._update_status)
        self._preview_widget.closed.connect(self._close_preview)

    def _selected_indices(self) -> list[int]:
        return sorted(self._list_widget.row(item) for item in self._list_widget.selectedItems())

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

        self._remove_action.setEnabled(has_selection)
        self._move_up_action.setEnabled(self._can_move_up())
        self._move_down_action.setEnabled(self._can_move_down())
        self._merge_action.setEnabled(has_files)

    def _is_preview_visible(self) -> bool:
        return self._stack.currentWidget() is self._preview_widget

    def _on_list_item_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(_PATH_ROLE)
        if not path:
            return
        self._open_preview(str(path))

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
        self._stack.setCurrentWidget(self._list_widget)
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

    def _format_item_text(self, filename: str, page_count: int | None) -> str:
        if page_count is None:
            return filename
        noun = "page" if page_count == 1 else "pages"
        return f"{filename}\n{page_count} {noun}"

    def _make_list_item(self, path: str) -> QListWidgetItem:
        filename = Path(path).name
        page_count = self._page_counts.get(path)
        item = QListWidgetItem(self._format_item_text(filename, page_count))
        item.setData(_PATH_ROLE, path)
        item.setToolTip(path)
        return item

    def _refresh_list(self, *, preserve_selection: list[int] | None = None) -> None:
        selected_paths: list[str] = []
        if preserve_selection is not None:
            for index in preserve_selection:
                if 0 <= index < self._model.file_count():
                    selected_paths.append(self._model.path_at(index))
        else:
            for index in self._selected_indices():
                if 0 <= index < self._model.file_count():
                    selected_paths.append(self._model.path_at(index))

        self._list_syncing = True
        try:
            self._list_widget.clear()
            for index in range(self._model.file_count()):
                self._list_widget.addItem(self._make_list_item(self._model.path_at(index)))

            if selected_paths:
                for row in range(self._list_widget.count()):
                    item = self._list_widget.item(row)
                    if item.data(_PATH_ROLE) in selected_paths:
                        item.setSelected(True)
        finally:
            self._list_syncing = False

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
        self._refresh_list()
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
        self._refresh_list()
        noun = "file" if len(indices) == 1 else "files"
        self.statusBar().showMessage(f"Removed {len(indices)} {noun}")

    def _move_up(self) -> None:
        indices = self._selected_indices()
        if not indices or not self._can_move_up():
            return
        self._model.move_up(indices)
        self._refresh_list(preserve_selection=indices)

    def _move_down(self) -> None:
        indices = self._selected_indices()
        if not indices or not self._can_move_down():
            return
        self._model.move_down(indices)
        self._refresh_list(preserve_selection=indices)

    def _on_rows_moved(
        self,
        parent: QModelIndex,
        start: int,
        end: int,
        destination: QModelIndex,
        row: int,
    ) -> None:
        del parent, destination
        if self._list_syncing:
            return

        if start == end:
            self._model.reorder(start, row)
        else:
            paths = [
                self._list_widget.item(i).data(_PATH_ROLE)
                for i in range(self._list_widget.count())
            ]
            while self._model.file_count() > 0:
                self._model.remove_at(0)
            self._model.add_files(paths)

        self._update_actions()
        self._update_status()

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

        try:
            merge_pdf_files(self._model.all_paths(), path)
        except PdfLoadError as exc:
            QMessageBox.critical(
                self,
                "Merge PDFs",
                f"Could not read a source PDF:\n{exc}",
            )
            return
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Merge PDFs",
                f"Could not write PDF:\n{exc}",
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Merge PDFs",
                f"Could not merge PDFs:\n{exc}",
            )
            return

        remember_directory(path)
        filename = Path(path).name
        file_count = self._model.file_count()
        noun = "file" if file_count == 1 else "files"
        self.statusBar().showMessage(f"Merged {file_count} {noun} to {filename}")

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
        self._refresh_list()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._model.file_count() > 0:
            if self._prompt_discard_file_list() != "discard":
                event.ignore()
                return
            self._clear_file_list()

        if self._preview_loader is not None:
            self._preview_loader.close()
            self._preview_loader = None

        super().closeEvent(event)
