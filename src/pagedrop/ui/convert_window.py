from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QPixmap, QResizeEvent, QShowEvent, QWheelEvent
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.image_to_pdf import (
    ConvertModel,
    ImageConvertError,
    inspect_image,
    planned_individual_outputs,
    validate_images,
)
from pagedrop.core.pdf_loader import MAX_RENDER_WIDTH_PX
from pagedrop.core.supported_formats import (
    image_dialog_filter,
    is_pdf_path,
    is_supported_image,
)
from pagedrop.ui.busy_overlay import BusyOverlay, ToastOverlay
from pagedrop.ui.convert_file_grid import ConvertFileGrid, render_image_thumbnail_png
from pagedrop.ui.dialogs import prompt_discard_file_list
from pagedrop.ui import icons
from pagedrop.ui.job_chrome import JobChromeMixin, explain_busy_running
from pagedrop.ui.keyboard_nav import (
    enable_toolbar_keyboard_navigation,
    set_content_tab_order,
)
from pagedrop.ui.result_actions import ResultActionsBar
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    ICON_SIZE,
    MAX_THUMBNAIL_WIDTH,
    MIN_PREVIEW_RENDER_WIDTH,
    MIN_THUMBNAIL_WIDTH,
    ON_PRIMARY,
    ZOOM_WHEEL_STEP,
)
from pagedrop.ui.tool_page import StatusFooter, ToolWorkflowHeader
from pagedrop.ui.tool_shell import run_tool_job
from pagedrop.ui.zoom_controls import ZoomControls

_PREVIEW_FOOTER_HINT = (
    "← → or ↑ ↓ change image  ·  Ctrl+scroll zoom  ·  Ctrl+0 fit width  ·  Esc back to grid"
)
_OUTPUT_SINGLE = "single"
_OUTPUT_SEPARATE = "separate"


class _ImagePreviewScrollArea(QScrollArea):
    """Scroll area that zooms the image preview on Ctrl+scroll."""

    def __init__(
        self, preview: _ImagePreviewWidget, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._preview = preview

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return

        step = ZOOM_WHEEL_STEP * max(
            1, self._preview.render_width_px // DEFAULT_THUMBNAIL_WIDTH
        )
        zoom_delta = step if delta > 0 else -step
        self._preview.zoom_by(zoom_delta)
        event.accept()


class _ImagePreviewWidget(QWidget):
    closed = pyqtSignal()
    image_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._paths: list[str] = []
        self._dimensions: dict[str, tuple[int, int]] = {}
        self._index = 0
        self._path: str | None = None
        self._current_dimensions: tuple[int, int] = (0, 0)
        self._render_width_px = MIN_PREVIEW_RENDER_WIDTH
        self._manual_zoom = False

        self._scroll = _ImagePreviewScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._image_label = QLabel()
        self._image_label.setObjectName("ConvertPreviewImage")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll.setWidget(self._image_label)
        self._scroll.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._footer = QLabel(_PREVIEW_FOOTER_HINT)
        self._footer.setObjectName("PagePreviewHint")
        self._footer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._scroll, stretch=1)

        footer_container = QWidget()
        footer_container.setObjectName("PreviewFooter")
        footer_layout = QVBoxLayout(footer_container)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.addWidget(self._footer)
        layout.addWidget(footer_container)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @property
    def render_width_px(self) -> int:
        return self._render_width_px

    @property
    def current_index(self) -> int:
        return self._index

    def show_images(
        self,
        paths: list[str],
        dimensions: dict[str, tuple[int, int]],
        index: int,
    ) -> None:
        self._paths = list(paths)
        self._dimensions = dimensions
        self._manual_zoom = False
        if not self._paths:
            self.clear_image()
            return
        self._index = max(0, min(index, len(self._paths) - 1))
        self._update_render_width()
        self._render_current()

    def clear_image(self) -> None:
        self._paths = []
        self._path = None
        self._current_dimensions = (0, 0)
        self._manual_zoom = False
        self._image_label.clear()

    def reset_zoom_to_fit(self) -> None:
        self._manual_zoom = False
        previous = self._render_width_px
        self._update_render_width()
        if self._path is not None and self._render_width_px != previous:
            self._render_current()

    def zoom_by(self, step: int) -> None:
        if self._path is None:
            return
        new_width = self._render_width_px + step
        new_width = max(
            MIN_PREVIEW_RENDER_WIDTH,
            min(MAX_RENDER_WIDTH_PX, new_width),
        )
        if new_width == self._render_width_px:
            return
        self._manual_zoom = True
        self._render_width_px = new_width
        self._render_current()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._path is not None:
            self._update_render_width()
            self._render_current()
        self.setFocus()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.isVisible() and self._path is not None and not self._manual_zoom:
            previous = self._render_width_px
            self._update_render_width()
            if self._render_width_px != previous:
                self._render_current()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._go_to_index(self._index - 1)
            event.accept()
            return
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._go_to_index(self._index + 1)
            event.accept()
            return
        if (
            key == Qt.Key.Key_0
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.reset_zoom_to_fit()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.closed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _fit_render_width(self) -> int:
        viewport = self._scroll.viewport()
        available = max(viewport.width() - 32, MIN_PREVIEW_RENDER_WIDTH)
        return min(MAX_RENDER_WIDTH_PX, available)

    def _update_render_width(self) -> None:
        if not self._manual_zoom:
            self._render_width_px = self._fit_render_width()

    def _go_to_index(self, index: int) -> None:
        if not self._paths:
            return
        clamped = max(0, min(index, len(self._paths) - 1))
        if clamped == self._index:
            return
        self._index = clamped
        self._render_current()
        self.image_changed.emit(self._index)

    def _render_current(self) -> None:
        if not self._paths:
            return
        path = self._paths[self._index]
        dimensions = self._dimensions.get(path, (0, 0))
        self._path = path
        self._current_dimensions = dimensions
        render_width = min(max(self._render_width_px, 1), MAX_RENDER_WIDTH_PX)
        png = render_image_thumbnail_png(path, render_width)
        pixmap = None
        if png is not None:
            pixmap = QPixmap()
            pixmap.loadFromData(png, "PNG")
        if pixmap is None or pixmap.isNull():
            self._image_label.clear()
            self._image_label.setText("Could not preview image")
            return
        self._image_label.setText("")
        self._image_label.setPixmap(pixmap)
        self._image_label.adjustSize()


class ConvertWindow(JobChromeMixin, QWidget):
    WINDOW_TITLE = "Create PDF"
    PAGE_ID = "create_pdf"

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        editor: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.tool_page_id = self.PAGE_ID
        self._editor = editor
        self._model = ConvertModel()
        self._dimensions: dict[str, tuple[int, int]] = {}
        self._output_mode = _OUTPUT_SINGLE
        self._init_job_chrome_state()
        self._status = StatusFooter()

        self.setWindowTitle(self.WINDOW_TITLE)
        self.setObjectName("ConvertWindow")
        self.setMinimumSize(640, 480)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._build_central_widget()
        self._build_toolbar()
        self._root.insertWidget(0, self._toolbar)
        self._root.insertWidget(
            0,
            ToolWorkflowHeader(
                self.WINDOW_TITLE,
                "Arrange images, choose an output mode, then create a new PDF.",
            ),
        )
        self._result_bar = ResultActionsBar()
        self._root.insertWidget(self._root.indexOf(self._stack), self._result_bar)
        self._root.addWidget(self._status)
        self._toast = ToastOverlay(self)
        refresh_cb = self._refresh_toolbar_icons
        icons.register_refresh(refresh_cb)
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
        self._stack.setObjectName("ConvertContentStack")

        self._file_grid = ConvertFileGrid()
        self._preview_widget = _ImagePreviewWidget()

        self._stack.addWidget(self._file_grid)
        self._stack.addWidget(self._preview_widget)
        self._root.addWidget(self._stack, stretch=1)

        self._busy_overlay = BusyOverlay(self._stack)
        self._busy_overlay.cancelled.connect(self.cancel_active_job)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Create PDF", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._toolbar = toolbar

        def tip(action, text: str) -> None:
            action.setToolTip(text)
            action.setStatusTip(text)

        self._back_to_list_action = toolbar.addAction(
            icons.icon("arrow-left"),
            "Back to grid",
        )
        self._back_to_list_action.triggered.connect(self._close_preview)
        self._back_to_list_action.setVisible(False)
        tip(self._back_to_list_action, "Return to image grid (Esc)")

        self._add_action = toolbar.addAction(
            icons.icon("folder-open"),
            "Add images…",
        )
        self._add_action.triggered.connect(self._add_images)
        tip(self._add_action, "Add images to convert")
        add_button = toolbar.widgetForAction(self._add_action)
        if add_button is not None:
            add_button.setObjectName("ToolbarSecondary")

        self._remove_action = toolbar.addAction(
            icons.icon("trash"),
            "Remove",
        )
        self._remove_action.triggered.connect(self._remove_selected)
        tip(self._remove_action, "Remove selected images")

        self._move_up_action = toolbar.addAction(
            icons.icon("arrow-up"),
            "Move up",
        )
        self._move_up_action.triggered.connect(self._move_up)
        tip(self._move_up_action, "Move selected images up")

        self._move_down_action = toolbar.addAction(
            icons.icon("arrow-down"),
            "Move down",
        )
        self._move_down_action.triggered.connect(self._move_down)
        tip(self._move_down_action, "Move selected images down")

        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        toolbar.addWidget(spacer)

        # Align with Merge: zoom group, then primary action (+ output mode).
        self._zoom_controls = ZoomControls(
            min_width=MIN_THUMBNAIL_WIDTH,
            max_width=MAX_THUMBNAIL_WIDTH,
            step=ZOOM_WHEEL_STEP,
            initial=DEFAULT_THUMBNAIL_WIDTH,
        )
        toolbar.addWidget(self._zoom_controls)

        self._create_action = toolbar.addAction(
            icons.icon("floppy-disk", color=ON_PRIMARY),
            "Save PDF…",
        )
        self._create_action.triggered.connect(self._create_pdfs)
        tip(self._create_action, "Save images as PDF")
        create_button = toolbar.widgetForAction(self._create_action)
        if create_button is not None:
            create_button.setObjectName("ToolbarPrimary")

        mode_host = QWidget()
        mode_host.setObjectName("OutputModeHost")
        mode_row = QHBoxLayout(mode_host)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(0)
        self._single_mode_action = QToolButton()
        self._single_mode_action.setText("One PDF")
        self._single_mode_action.setCheckable(True)
        self._single_mode_action.setChecked(True)
        self._single_mode_action.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._single_mode_action.setToolTip("Combine all images into one PDF")
        self._single_mode_action.setStatusTip("Combine all images into one PDF")
        self._separate_mode_action = QToolButton()
        self._separate_mode_action.setText("Separate PDFs")
        self._separate_mode_action.setCheckable(True)
        self._separate_mode_action.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._separate_mode_action.setToolTip("Save each image as its own PDF")
        self._separate_mode_action.setStatusTip("Save each image as its own PDF")
        mode_group = QButtonGroup(mode_host)
        mode_group.setExclusive(True)
        mode_group.addButton(self._single_mode_action)
        mode_group.addButton(self._separate_mode_action)
        mode_row.addWidget(self._single_mode_action)
        mode_row.addWidget(self._separate_mode_action)
        toolbar.addWidget(mode_host)
        self._output_mode_host = mode_host

        enable_toolbar_keyboard_navigation(toolbar)
        set_content_tab_order(toolbar, self._stack, status_bar=self.statusBar())
        self._toolbar = toolbar

    def _refresh_toolbar_icons(self) -> None:
        """Re-tint Phosphor toolbar icons after a light/dark swap."""
        self._back_to_list_action.setIcon(icons.icon("arrow-left"))
        self._add_action.setIcon(icons.icon("folder-open"))
        self._remove_action.setIcon(icons.icon("trash"))
        self._move_up_action.setIcon(icons.icon("arrow-up"))
        self._move_down_action.setIcon(icons.icon("arrow-down"))
        self._create_action.setIcon(icons.icon("floppy-disk", color=ON_PRIMARY))

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
        self._preview_widget.closed.connect(self._close_preview)
        self._preview_widget.image_changed.connect(self._on_preview_image_changed)
        self._single_mode_action.toggled.connect(self._on_output_mode_changed)
        self._wire_result_actions()
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

    def _on_output_mode_changed(self, single_checked: bool) -> None:
        self._output_mode = _OUTPUT_SINGLE if single_checked else _OUTPUT_SEPARATE
        label = "Save PDF…" if self._output_mode == _OUTPUT_SINGLE else "Choose folder…"
        tip = (
            "Save images as PDF"
            if self._output_mode == _OUTPUT_SINGLE
            else "Save each image as a separate PDF"
        )
        self._create_action.setText(label)
        self._create_action.setToolTip(tip)
        self._create_action.setStatusTip(tip)
        self._update_actions()

    def _update_actions(self) -> None:
        in_preview = self._is_preview_visible()
        has_selection = bool(self._selected_indices())
        has_files = self._model.file_count() > 0

        self._back_to_list_action.setVisible(in_preview)
        self._add_action.setVisible(not in_preview)
        self._remove_action.setVisible(not in_preview)
        self._move_up_action.setVisible(not in_preview)
        self._move_down_action.setVisible(not in_preview)
        self._output_mode_host.setVisible(not in_preview)
        self._create_action.setVisible(not in_preview)
        self._zoom_controls.setVisible(not in_preview)

        toolbar_enabled = not self.is_job_running()
        self._add_action.setEnabled(toolbar_enabled)
        self._remove_action.setEnabled(has_selection and toolbar_enabled)
        self._move_up_action.setEnabled(self._can_move_up() and toolbar_enabled)
        self._move_down_action.setEnabled(self._can_move_down() and toolbar_enabled)
        self._create_action.setEnabled(has_files and not self.is_job_running())
        self._zoom_controls.setEnabled(has_files and not in_preview and not self.is_job_running())
        self._output_mode_host.setEnabled(toolbar_enabled)
        self._set_result_precedence(self._result_bar.isVisible())

    def _set_result_precedence(self, available: bool) -> None:
        button = self._toolbar.widgetForAction(self._create_action)
        if button is None:
            return
        button.setProperty("resultAvailable", available)
        button.style().unpolish(button)
        button.style().polish(button)

    def _is_preview_visible(self) -> bool:
        return self._stack.currentWidget() is self._preview_widget

    def _on_zoom_changed(self, thumbnail_width_px: int) -> None:
        self._zoom_controls.set_value(thumbnail_width_px)
        self.statusBar().showMessage(f"Thumbnail size: {thumbnail_width_px} px")

    def _on_thumbnail_failed(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _open_preview(self, path: str) -> None:
        dimensions = self._dimensions.get(path)
        if dimensions is None:
            try:
                dimensions = inspect_image(path)
            except ImageConvertError as exc:
                QMessageBox.critical(
                    self,
                    "Preview",
                    f"Could not open {Path(path).name}:\n{exc}",
                )
                return
            self._dimensions[path] = dimensions
        paths = self._file_grid.ordered_paths
        try:
            index = paths.index(path)
        except ValueError:
            return
        self._preview_widget.show_images(paths, self._dimensions, index)
        self._stack.setCurrentWidget(self._preview_widget)
        self._preview_widget.setFocus()
        self._update_actions()
        self._update_status()

    def _on_preview_image_changed(self, index: int) -> None:
        self._file_grid.selection_manager.select_single(index)
        self._update_status()

    def _close_preview(self) -> None:
        if not self._is_preview_visible():
            return
        self._stack.setCurrentWidget(self._file_grid)
        self._preview_widget.clear_image()
        self._update_actions()
        self._update_status()

    def _update_status(self) -> None:
        if self._is_preview_visible() and self._preview_widget._path is not None:
            filename = Path(self._preview_widget._path).name
            width, height = self._preview_widget._current_dimensions
            total = len(self._preview_widget._paths)
            page = self._preview_widget.current_index + 1
            self.statusBar().showMessage(
                f"Preview · {filename} ({width} × {height} px) · {page}/{total}"
            )
            return

        count = self._model.file_count()
        if count == 0:
            self.statusBar().showMessage("No images")
        elif count == 1:
            self.statusBar().showMessage("1 image")
        else:
            self.statusBar().showMessage(f"{count} images")

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
            self._dimensions,
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

    def _reject_message_for_path(self, path: str) -> str | None:
        filename = Path(path).name
        if is_pdf_path(path):
            return (
                f"{filename} is a PDF.\n\n"
                "Create PDF accepts images only. Use Merge PDFs for PDF files."
            )
        if not is_supported_image(path):
            return (
                f"{filename} is not a supported image format.\n\n"
                "Create PDF accepts images only. Use Merge PDFs for PDF files."
            )
        return None

    def _validate_image(self, path: str) -> tuple[int, int] | None:
        reject = self._reject_message_for_path(path)
        if reject is not None:
            QMessageBox.warning(self, "Add images", reject)
            return None
        try:
            dimensions = inspect_image(path)
        except ImageConvertError as exc:
            QMessageBox.critical(
                self,
                "Add images",
                f"Could not open {Path(path).name}:\n{exc}",
            )
            return None
        return dimensions

    def _add_paths(self, paths: list[str]) -> None:
        accepted: list[str] = []
        for path in paths:
            dimensions = self._validate_image(path)
            if dimensions is None:
                continue
            resolved = str(Path(path).resolve())
            self._dimensions[resolved] = dimensions
            accepted.append(resolved)

        if not accepted:
            return

        self._model.add_files(accepted)
        self._refresh_grid()
        noun = "image" if len(accepted) == 1 else "images"
        self.statusBar().showMessage(f"Added {len(accepted)} {noun}")

    def _add_images(self) -> None:
        start_dir = last_directory()
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add images",
            start_dir,
            image_dialog_filter(),
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
        noun = "image" if len(indices) == 1 else "images"
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

    def _default_output_path(self) -> str:
        first_path = Path(self._model.path_at(0))
        return str(first_path.parent / f"{first_path.stem}_combined.pdf")

    def _validate_batch_before_convert(self) -> bool:
        paths = self._model.all_paths()
        try:
            validate_images(paths)
        except ImageConvertError as exc:
            QMessageBox.critical(
                self,
                self.WINDOW_TITLE,
                f"Cannot create PDF:\n{exc}",
            )
            return False
        return True

    def _set_job_controls_enabled(self, enabled: bool) -> None:
        self._busy_overlay.set_cancellable(not enabled)
        self._update_actions()

    def _create_pdfs(self) -> None:
        if self._model.file_count() == 0:
            return
        if not self._validate_batch_before_convert():
            return

        paths = self._model.all_paths()

        if self._output_mode == _OUTPUT_SINGLE:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save PDF",
                self._default_output_path(),
                "PDF files (*.pdf);;All files (*)",
                "",
                QFileDialog.Option.DontConfirmOverwrite,
            )
            if not path:
                return
            if not path.lower().endswith(".pdf"):
                path = f"{path}.pdf"
            self._start_convert(paths, "images_to_pdf", [Path(path)])
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose output folder",
            last_directory(),
        )
        if not folder:
            return

        remember_directory(folder)
        self._start_convert(
            paths, "images_to_pdfs", planned_individual_outputs(paths, folder)
        )

    def _start_convert(
        self, paths: list[str], job_type: str, outputs: list[Path]
    ) -> None:
        count = len(paths)
        noun = "image" if count == 1 else "images"
        written = len(outputs)

        def success_message(result: str) -> str:
            remember_directory(result)
            if job_type == "images_to_pdf":
                return f"Created PDF from {count} {noun}: {Path(result).name}"
            file_noun = "file" if written == 1 else "files"
            status = f"Created {written} PDF {file_noun} from {count} {noun}"
            # The result bar binds to the first path only.
            return f"{status}. Showing first" if written > 1 else status

        run_tool_job(
            self,
            job_type=job_type,
            inputs=paths,
            output=str(outputs[0]),
            existing_paths=[path for path in outputs if path.exists()],
            progress_message=(
                "Creating PDF…" if job_type == "images_to_pdf" else "Creating PDFs…"
            ),
            success_toast=success_message,
        )

    def _explain_busy(self) -> None:
        explain_busy_running(
            status_bar=self.statusBar(),
            toast=self._toast,
            label="Create PDF",
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_busy_overlay"):
            parent = self._busy_overlay.parentWidget()
            if parent is not None:
                self._busy_overlay.setGeometry(parent.rect())

    def _prompt_discard_file_list(self) -> str:
        return prompt_discard_file_list(
            self,
            window_title=self.WINDOW_TITLE,
            informative_text=(
                "Closing will remove all images from the Create PDF list."
            ),
        )

    def _clear_file_list(self) -> None:
        self._model.clear()
        self._dimensions.clear()
        if self._is_preview_visible():
            self._close_preview()
        self._refresh_grid()

    def request_close(self) -> bool:
        if self.is_job_running():
            self._explain_busy()
            return False

        if self._model.file_count() > 0:
            if self._prompt_discard_file_list() != "discard":
                return False
            self._clear_file_list()

        self._file_grid.cancel_rendering()
        return True

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self.request_close():
            event.ignore()
            return
        super().closeEvent(event)
