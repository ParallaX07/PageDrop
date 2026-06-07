from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QMimeData, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QEnterEvent,
    QMouseEvent,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QVBoxLayout,
)

from pagedrop.core.drag_mime import INTERNAL_MERGE_FILE_MIME, encode_page_indices
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.ui.theme import (
    CARD_PADDING,
    CARD_WIDTH,
    convert_file_card_stylesheet,
    shadow_qcolor,
)


class ConvertFileCard(QFrame):
    """Grid card for one image in the Create PDF queue."""

    clicked = pyqtSignal(int, Qt.KeyboardModifier)
    double_clicked = pyqtSignal(int)

    def __init__(
        self,
        file_index: int,
        path: str,
        dimensions: tuple[int, int],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.file_index = file_index
        self.path = path
        self.dimensions = dimensions
        self._card_width = CARD_WIDTH
        self._source_pixmap: QPixmap | None = None
        self._selected = False
        self._hovered = False
        self._drag_start_pos: QPoint | None = None
        self._selection_manager: SelectionManager | None = None

        self.setObjectName("ConvertFileCard")
        self.setFixedWidth(self._card_width)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        width, height = dimensions
        self.setToolTip(f"{path}\n{width} × {height} px")

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(14)
        self._shadow.setOffset(0, 3)
        self._shadow.setColor(QColor(*shadow_qcolor(alpha=55)))
        self.setGraphicsEffect(self._shadow)

        self._thumbnail_label = QLabel()
        self._thumbnail_label.setObjectName("ConvertFileCardThumbnail")
        self._thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail_label.setMinimumHeight(80)

        filename = Path(path).name
        self._title_label = QLabel(filename)
        self._title_label.setObjectName("ConvertFileCardTitle")
        self._title_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._title_label.setWordWrap(True)

        self._subtitle_label = QLabel(f"{width} × {height}")
        self._subtitle_label.setObjectName("ConvertFileCardSubtitle")
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self._thumbnail_label)
        layout.addWidget(self._title_label)
        layout.addWidget(self._subtitle_label)

        self.set_selected(False)

    def set_selection_manager(self, manager: SelectionManager) -> None:
        self._selection_manager = manager

    def set_file_index(self, index: int) -> None:
        self.file_index = index

    def set_card_width(
        self,
        width: int,
        *,
        fast: bool = True,
        refresh_thumbnail: bool = True,
    ) -> None:
        self._card_width = width
        self.setFixedWidth(width)
        if refresh_thumbnail:
            self._refresh_thumbnail_display(fast=fast)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self._source_pixmap = pixmap
        self._refresh_thumbnail_display(fast=False)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        if self._drag_start_pos is None or self._selection_manager is None:
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
            self.clicked.emit(self.file_index, event.modifiers())
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.file_index)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _start_drag(self) -> None:
        assert self._selection_manager is not None

        if self.file_index not in self._selection_manager.selection:
            self._selection_manager.select_single(self.file_index)

        indices = sorted(self._selection_manager.selection)
        mime = QMimeData()
        mime.setData(INTERNAL_MERGE_FILE_MIME, encode_page_indices(indices))

        drag = QDrag(self)
        drag.setMimeData(mime)

        pixmap = self._thumbnail_label.pixmap()
        if pixmap is not None and not pixmap.isNull():
            preview = pixmap.scaledToWidth(
                120,
                Qt.TransformationMode.SmoothTransformation,
            )
            drag.setPixmap(preview)
            drag.setHotSpot(QPoint(preview.width() // 2, preview.height() // 2))

        QApplication.setOverrideCursor(Qt.CursorShape.DragMoveCursor)
        try:
            if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and not os.environ.get(
                "PAGEDROP_TESTING"
            ):
                pass
            else:
                drag.exec(Qt.DropAction.MoveAction)
        finally:
            QApplication.restoreOverrideCursor()

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

    def _apply_visual_state(self) -> None:
        self.setStyleSheet(
            convert_file_card_stylesheet(
                selected=self._selected,
                hovered=self._hovered,
            )
        )
