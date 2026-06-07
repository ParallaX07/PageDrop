from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout


class PageCard(QFrame):
    CARD_WIDTH = 170

    def __init__(self, page_index: int, parent=None) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self._selected = False

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
