from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QMimeData, QPoint, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QEnterEvent,
    QFocusEvent,
    QFont,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
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
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.ui.theme import (
    CARD_PADDING,
    CARD_WIDTH,
    accent_qcolor,
    page_card_stylesheet,
    shadow_qcolor,
)
from pagedrop.utils.temp_manager import TempManager


class PageCard(QFrame):
    clicked = pyqtSignal(int, Qt.KeyboardModifier)
    double_clicked = pyqtSignal(int)
    context_menu_requested = pyqtSignal(int, QPoint)
    CARD_WIDTH = CARD_WIDTH

    def __init__(self, page_index: int, parent=None) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self._card_width = CARD_WIDTH
        self._source_pixmap: QPixmap | None = None
        self._selected = False
        self._hovered = False
        self._keyboard_focused = False
        self._drag_start_pos: QPoint | None = None
        self._page_ref: PageRef | None = None
        self._model: PdfEditModel | None = None
        self._selection_manager: SelectionManager | None = None
        self._temp_manager: TempManager | None = None

        self.setObjectName("PageCard")
        self.setFixedWidth(self._card_width)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(14)
        self._shadow.setOffset(0, 3)
        self._shadow.setColor(QColor(*shadow_qcolor(alpha=55)))
        self.setGraphicsEffect(self._shadow)

        self._thumbnail_label = QLabel()
        self._thumbnail_label.setObjectName("PageCardThumbnail")
        self._thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail_label.setMinimumHeight(80)

        self._page_label = QLabel(f"Page {page_index + 1}")
        self._page_label.setObjectName("PageCardLabel")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self._thumbnail_label)
        layout.addWidget(self._page_label)

        self.set_selected(False)

    @property
    def is_selected(self) -> bool:
        return self._selected

    @property
    def page_ref(self) -> PageRef | None:
        return self._page_ref

    def set_page_ref(self, ref: PageRef) -> None:
        self._page_ref = ref

    def set_logical_index(self, index: int) -> None:
        self.page_index = index
        self._page_label.setText(f"Page {index + 1}")

    def set_drag_context(
        self,
        model: PdfEditModel,
        selection_manager: SelectionManager,
        temp_manager: TempManager,
    ) -> None:
        self._model = model
        self._selection_manager = selection_manager
        self._temp_manager = temp_manager

    def set_page_tooltip(self, width_mm: int, height_mm: int) -> None:
        page_num = self.page_index + 1
        self.setToolTip(
            f"Page {page_num} · {width_mm}×{height_mm} mm · Click to select"
        )

    def set_keyboard_focused(self, focused: bool) -> None:
        if self._keyboard_focused != focused:
            self._keyboard_focused = focused
            self._apply_visual_state()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hovered = True
        self._shadow.setBlurRadius(18)
        self._shadow.setOffset(0, 4)
        self._shadow.setColor(QColor(*shadow_qcolor(alpha=72)))
        self._apply_visual_state()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._shadow.setBlurRadius(14)
        self._shadow.setOffset(0, 3)
        self._shadow.setColor(QColor(*shadow_qcolor(alpha=55)))
        self._apply_visual_state()
        super().leaveEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.context_menu_requested.emit(self.page_index, event.globalPos())
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        if self._drag_start_pos is None:
            super().mouseMoveEvent(event)
            return
        if (
            self._model is None
            or self._selection_manager is None
            or self._temp_manager is None
        ):
            if self._model is None:
                window = self.window()
                if hasattr(window, "statusBar"):
                    window.statusBar().showMessage("Open a PDF first")
            super().mouseMoveEvent(event)
            return

        distance = (event.pos() - self._drag_start_pos).manhattanLength()
        if distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        self._drag_start_pos = None
        self._start_drag()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._drag_start_pos is not None
        ):
            self.clicked.emit(self.page_index, event.modifiers())
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.page_index)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

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
            )
        except OSError as exc:
            QMessageBox.critical(
                self.window(),
                "Extract Pages",
                f"Could not prepare pages for drag-and-drop (disk full or write error):\n{exc}",
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self.window(),
                "Extract Pages",
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

        accent = accent_qcolor()
        painter.setBrush(QColor(*accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_x, badge_y, badge_w, badge_h, 6, 6)
        painter.setPen(QColor(255, 255, 255))
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

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self._source_pixmap = pixmap
        self._refresh_thumbnail_display(fast=False)

    def _refresh_thumbnail_display(self, *, fast: bool = False) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return
        target_width = self._card_width - CARD_PADDING
        mode = (
            Qt.TransformationMode.FastTransformation
            if fast
            else Qt.TransformationMode.SmoothTransformation
        )
        if self._source_pixmap.width() == target_width:
            display = self._source_pixmap
        else:
            display = self._source_pixmap.scaledToWidth(target_width, mode)
        self._thumbnail_label.setPixmap(display)
        self._thumbnail_label.setMinimumHeight(display.height())

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_visual_state()

    def _apply_visual_state(self) -> None:
        self.setStyleSheet(
            page_card_stylesheet(
                selected=self._selected,
                hovered=self._hovered,
                focused=self._keyboard_focused,
            )
        )
