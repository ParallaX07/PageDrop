from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QEvent, QMimeData, QPoint, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QFont, QMouseEvent, QPainter, QPixmap, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from pagedrop.core.drag_mime import (
    INTERNAL_PAGE_MIME,
    PAGE_TRANSFER_MIME,
    encode_page_indices,
    encode_page_refs,
)
from pagedrop.core.page_extractor import extract_page_refs_to_files
from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_loader import PdfPasswordError, PdfPasswordRequiredError
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.ui.base_file_card import BaseFileCard
from pagedrop.ui.theme import CARD_PADDING, RADIUS_BADGE, SPACE_1, SPACE_2, accent_qcolor, on_accent_qcolor
from pagedrop.utils.temp_manager import TempManager

# Portrait placeholder while the real thumbnail is rendering.
_SKELETON_ASPECT = 1.414
_SKELETON_PULSE_DIM = 0.55
_SKELETON_PULSE_BRIGHT = 1.0


class PageCard(BaseFileCard):
    context_menu_requested = pyqtSignal(int, QPoint)

    def __init__(self, page_index: int, parent=None) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self._page_ref: PageRef | None = None
        self._model: PdfEditModel | None = None
        self._selection_manager: SelectionManager | None = None
        self._temp_manager: TempManager | None = None
        self._is_skeleton = True
        self._page_overlay_wanted = False
        self._size_provider: Callable[[], tuple[int, int]] | None = None
        self._size_cached: tuple[int, int] | None = None
        self._skeleton_pulse_effect: QGraphicsOpacityEffect | None = None

        self.setObjectName("PageCard")
        self._thumbnail_label.setObjectName("PageCardThumbnail")

        self._page_overlay = QLabel(str(page_index + 1), self._thumbnail_label)
        self._page_overlay.setObjectName("PageCardPageOverlay")
        self._page_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._page_overlay.hide()

        # Semantic rotation chip — same material as page overlay, opposite corner.
        self._rotation_overlay = QLabel("", self._thumbnail_label)
        self._rotation_overlay.setObjectName("PageCardRotationOverlay")
        self._rotation_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._rotation_overlay.hide()

        self._page_label = QLabel(f"Page {page_index + 1}")
        self._page_label.setObjectName("PageCardLabel")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        layout.setSpacing(SPACE_1)
        layout.addWidget(self._thumbnail_label)
        layout.addWidget(self._page_label)

        self._apply_visual_state()
        self._apply_skeleton_size()
        self._sync_page_overlay_visibility()
        self.setToolTip(f"Page {page_index + 1} · Click to select")
        self._sync_accessible()

    def _item_index(self) -> int:
        return self.page_index

    @property
    def is_selected(self) -> bool:
        return self._selected

    @property
    def page_ref(self) -> PageRef | None:
        return self._page_ref

    def set_page_ref(self, ref: PageRef) -> None:
        self._page_ref = ref
        self.set_rotation_indicator(ref.rotation)

    def set_logical_index(self, index: int) -> None:
        self.page_index = index
        self._page_label.setText(f"Page {index + 1}")
        self._page_overlay.setText(str(index + 1))
        self._sync_page_overlay_geometry()
        if self._size_cached is None:
            self.setToolTip(f"Page {index + 1} · Click to select")
        else:
            self._apply_sized_tooltip(*self._size_cached)
        self._sync_accessible()

    def set_page_overlay_visible(self, visible: bool) -> None:
        if self._page_overlay_wanted == visible:
            return
        self._page_overlay_wanted = visible
        self._sync_page_overlay_visibility()

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self._is_skeleton = False
        self.clear_skeleton_pulse()
        super().set_thumbnail(pixmap)
        self._sync_page_overlay_visibility()

    def release_thumbnail(self) -> bool:
        """Drop the cached pixmap and return to skeleton placeholder.

        Returns True if a pixmap was released.
        """
        if self._source_pixmap is None and self._is_skeleton:
            return False
        had_pixmap = self._source_pixmap is not None
        self._source_pixmap = None
        self._thumbnail_label.clear()
        self._is_skeleton = True
        self.clear_skeleton_pulse()
        self._apply_skeleton_size()
        self._sync_page_overlay_visibility()
        return had_pixmap

    def set_skeleton_pulse(self, dim: bool) -> None:
        """Gentle opacity blink so placeholders read as loading, not blank."""
        if not self._is_skeleton:
            return
        if self._skeleton_pulse_effect is None:
            effect = QGraphicsOpacityEffect(self._thumbnail_label)
            self._thumbnail_label.setGraphicsEffect(effect)
            self._skeleton_pulse_effect = effect
        self._skeleton_pulse_effect.setOpacity(
            _SKELETON_PULSE_DIM if dim else _SKELETON_PULSE_BRIGHT
        )

    def clear_skeleton_pulse(self) -> None:
        if self._skeleton_pulse_effect is None:
            return
        self._thumbnail_label.setGraphicsEffect(None)
        self._skeleton_pulse_effect = None

    def set_page_size_provider(
        self, provider: Callable[[], tuple[int, int]] | None
    ) -> None:
        """Defer fitz page-size lookup until the tooltip is shown."""
        self._size_provider = provider
        self._size_cached = None
        self.setToolTip(f"Page {self.page_index + 1} · Click to select")

    def set_page_tooltip(self, width_mm: int, height_mm: int) -> None:
        self._size_provider = None
        self._size_cached = (width_mm, height_mm)
        self._apply_sized_tooltip(width_mm, height_mm)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            self._ensure_sized_tooltip()
        return super().event(event)

    def _ensure_sized_tooltip(self) -> None:
        if self._size_cached is not None:
            self._apply_sized_tooltip(*self._size_cached)
            return
        if self._size_provider is None:
            return
        self._size_cached = self._size_provider()
        self._apply_sized_tooltip(*self._size_cached)

    def _apply_sized_tooltip(self, width_mm: int, height_mm: int) -> None:
        page_num = self.page_index + 1
        self.setToolTip(
            f"Page {page_num} · {width_mm}×{height_mm} mm · Click to select"
        )
        self._sync_accessible()

    def _sync_accessible(self) -> None:
        page_num = self.page_index + 1
        self.setAccessibleName(f"Page {page_num}")
        if self._size_cached is not None:
            width_mm, height_mm = self._size_cached
            self.setAccessibleDescription(
                f"{width_mm}×{height_mm} mm · Click to select"
            )
        else:
            self.setAccessibleDescription("Click to select")

    def _sync_page_overlay_visibility(self) -> None:
        visible = self._page_overlay_wanted or self._is_skeleton
        self._page_overlay.setVisible(visible)
        if visible:
            self._sync_page_overlay_geometry()

    def _apply_skeleton_size(self) -> None:
        if not self._is_skeleton:
            return
        thumb_w = max(1, self._card_width - CARD_PADDING)
        self._thumbnail_label.setMinimumHeight(max(80, int(thumb_w * _SKELETON_ASPECT)))
        self._sync_page_overlay_geometry()

    def set_rotation_indicator(self, degrees: int) -> None:
        rot = degrees % 360
        if rot == 0:
            self._rotation_overlay.hide()
            return
        self._rotation_overlay.setText(f"{rot}°")
        self._rotation_overlay.show()
        self._sync_rotation_overlay_geometry()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_page_overlay_geometry()
        self._sync_rotation_overlay_geometry()

    def _sync_page_overlay_geometry(self) -> None:
        if not self._page_overlay.isVisible():
            return
        self._page_overlay.adjustSize()
        margin = 4
        x = max(
            0,
            self._thumbnail_label.width() - self._page_overlay.width() - margin,
        )
        y = max(
            0,
            self._thumbnail_label.height() - self._page_overlay.height() - margin,
        )
        self._page_overlay.move(x, y)

    def _sync_rotation_overlay_geometry(self) -> None:
        if not self._rotation_overlay.isVisible():
            return
        self._rotation_overlay.adjustSize()
        margin = 4
        self._rotation_overlay.move(margin, margin)

    def set_drag_context(
        self,
        model: PdfEditModel,
        selection_manager: SelectionManager,
        temp_manager: TempManager,
    ) -> None:
        self._model = model
        self._selection_manager = selection_manager
        self._temp_manager = temp_manager

    def contextMenuEvent(self, event) -> None:
        self.context_menu_requested.emit(self.page_index, event.globalPos())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # Status hint when drag context is missing (open PDF first).
        if (
            (event.buttons() & Qt.MouseButton.LeftButton)
            and self._drag_start_pos is not None
            and self._model is None
        ):
            window = self.window()
            if hasattr(window, "statusBar"):
                window.statusBar().showMessage("Open a PDF first")
        super().mouseMoveEvent(event)

    def _can_start_drag(self) -> bool:
        return (
            self._model is not None
            and self._selection_manager is not None
            and self._temp_manager is not None
        )

    def set_card_width(
        self,
        width: int,
        *,
        fast: bool = True,
        refresh_thumbnail: bool = True,
        apply_layout: bool = True,
    ) -> None:
        self._card_width = width
        if apply_layout:
            self.apply_layout_width()
        if refresh_thumbnail:
            self._refresh_thumbnail_display(fast=fast)

    def apply_layout_width(self) -> None:
        if self.width() != self._card_width:
            self.setFixedWidth(self._card_width)
        self._apply_skeleton_size()

    def refresh_thumbnail_display(self, *, fast: bool = False) -> None:
        """Re-scale the cached source pixmap to the current card width."""
        self._refresh_thumbnail_display(fast=fast)

    def _start_drag(self) -> None:
        assert self._model is not None
        assert self._selection_manager is not None
        assert self._temp_manager is not None

        if self.page_index not in self._selection_manager.selection:
            self._selection_manager.select_single(self.page_index)

        logical_indices = sorted(self._selection_manager.selection)
        refs = [self._model.page_at(i) for i in logical_indices]
        base_name = Path(self._model.original_path).stem
        output_dir = self._temp_manager.create_drag_dir()

        try:
            temp_paths = extract_page_refs_to_files(
                refs,
                output_dir,
                base_name,
                passwords=self._source_passwords(),
            )
        except (PdfPasswordRequiredError, PdfPasswordError) as exc:
            QMessageBox.critical(
                self.window(),
                "Extract pages",
                f"Could not prepare pages for drag-and-drop:\n{exc}",
            )
            return
        except OSError as exc:
            QMessageBox.critical(
                self.window(),
                "Extract pages",
                f"Could not prepare pages for drag-and-drop (disk full or write error):\n{exc}",
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self.window(),
                "Extract pages",
                f"Could not prepare pages for drag-and-drop:\n{exc}",
            )
            return

        mime = QMimeData()
        mime.setData(INTERNAL_PAGE_MIME, encode_page_indices(logical_indices))
        mime.setData(PAGE_TRANSFER_MIME, encode_page_refs(refs))
        urls = [QUrl.fromLocalFile(str(path)) for path in temp_paths]
        mime.setUrls(urls)

        drag = QDrag(self)
        drag.setMimeData(mime)

        pixmap = self._build_drag_pixmap(len(logical_indices))
        if pixmap is not None:
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

        QApplication.setOverrideCursor(Qt.CursorShape.DragCopyCursor)
        window = self.window()
        status_bar = getattr(window, "statusBar", None)
        if callable(status_bar):
            status_bar().showMessage("Release to place pages")
        try:
            # Offscreen/test Qt has no drop target; exec() would block the event loop forever.
            # Under tests, conftest patches exec to return immediately. Offscreen
            # without PAGEDROP_TESTING has no drop target — skip the native loop.
            if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and not os.environ.get(
                "PAGEDROP_TESTING"
            ):
                pass
            else:
                drag.exec(Qt.DropAction.CopyAction)
        finally:
            QApplication.restoreOverrideCursor()
            self._temp_manager.cleanup_paths(temp_paths)
            restore = getattr(window, "_restore_document_status", None)
            if callable(restore):
                restore()

    def _build_drag_pixmap(self, count: int) -> QPixmap | None:
        thumbnail = self._thumbnail_label.pixmap()
        if thumbnail is None or thumbnail.isNull():
            return None

        scaled = thumbnail.scaledToWidth(
            120,
            Qt.TransformationMode.SmoothTransformation,
        )
        width = scaled.width()
        height = scaled.height()

        if count <= 1:
            return scaled

        stack_offset = 6
        canvas = QPixmap(width + stack_offset * 2, height + stack_offset * 2)
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for layer in range(min(count, 3)):
            offset = (min(count, 3) - 1 - layer) * stack_offset
            painter.drawPixmap(offset, offset, scaled)

        badge_text = f"×{count}"
        badge_font = QFont()
        badge_font.setBold(True)
        badge_font.setPointSize(10)
        painter.setFont(badge_font)

        metrics = painter.fontMetrics()
        badge_w = metrics.horizontalAdvance(badge_text) + 10
        badge_h = metrics.height() + 4
        badge_x = canvas.width() - badge_w - 2
        badge_y = 2

        # Hairline edge so the accent chip stays readable on stacked thumbs
        painter.setBrush(accent_qcolor())
        painter.setPen(QColor(0, 0, 0, 90))
        painter.drawRoundedRect(
            badge_x, badge_y, badge_w, badge_h, RADIUS_BADGE, RADIUS_BADGE
        )
        painter.setPen(on_accent_qcolor())
        painter.drawText(
            badge_x,
            badge_y,
            badge_w,
            badge_h,
            Qt.AlignmentFlag.AlignCenter,
            badge_text,
        )
        painter.end()

        return canvas

    def _source_passwords(self) -> dict[str, str] | None:
        from pagedrop.ui.thumbnail_grid import ThumbnailGrid

        current = self.parentWidget()
        while current is not None:
            if isinstance(current, ThumbnailGrid):
                return current._source_passwords()
            current = current.parentWidget()
        return None

