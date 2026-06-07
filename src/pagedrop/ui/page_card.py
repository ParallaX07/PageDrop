from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QMimeData, QPoint, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QFont,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QMessageBox, QVBoxLayout

from pagedrop.core.page_extractor import extract_pages_to_files
from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.utils.temp_manager import TempManager


class PageCard(QFrame):
    clicked = pyqtSignal(int, Qt.KeyboardModifier)
    CARD_WIDTH = 170

    def __init__(self, page_index: int, parent=None) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self._selected = False
        self._drag_start_pos: QPoint | None = None
        self._loader: PdfLoader | None = None
        self._selection_manager: SelectionManager | None = None
        self._temp_manager: TempManager | None = None

        self.setFixedWidth(self.CARD_WIDTH)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._thumbnail_label = QLabel()
        self._thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail_label.setMinimumHeight(80)

        self._page_label = QLabel(f"Page {page_index + 1}")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(self._thumbnail_label)
        layout.addWidget(self._page_label)

        self.set_selected(False)

    @property
    def is_selected(self) -> bool:
        return self._selected

    def set_drag_context(
        self,
        loader: PdfLoader,
        selection_manager: SelectionManager,
        temp_manager: TempManager,
    ) -> None:
        self._loader = loader
        self._selection_manager = selection_manager
        self._temp_manager = temp_manager

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
            self._loader is None
            or self._selection_manager is None
            or self._temp_manager is None
        ):
            if self._loader is None:
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

    def _start_drag(self) -> None:
        assert self._loader is not None
        assert self._selection_manager is not None
        assert self._temp_manager is not None

        if self.page_index not in self._selection_manager.selection:
            self._selection_manager.select_single(self.page_index)

        page_indices = sorted(self._selection_manager.selection)
        base_name = Path(self._loader.path).stem
        output_dir = self._temp_manager.create_drag_dir()

        try:
            temp_paths = extract_pages_to_files(
                self._loader.path,
                page_indices,
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
        urls = [QUrl.fromLocalFile(str(path)) for path in temp_paths]
        mime.setUrls(urls)

        drag = QDrag(self)
        drag.setMimeData(mime)

        pixmap = self._build_drag_pixmap(len(page_indices))
        if pixmap is not None:
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

        QApplication.setOverrideCursor(Qt.CursorShape.DragCopyCursor)
        try:
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

        painter.setBrush(QColor(59, 130, 246))
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
        scaled = pixmap.scaledToWidth(
            self.CARD_WIDTH - 8,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumbnail_label.setPixmap(scaled)
        self._thumbnail_label.setMinimumHeight(scaled.height())

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        if selected:
            self.setStyleSheet("border: 3px solid #3b82f6; border-radius: 4px;")
        else:
            self.setStyleSheet("border: 1px solid #666; border-radius: 4px;")
