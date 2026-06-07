from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class BusyOverlay(QWidget):
    """Semi-transparent overlay that blocks interaction while work is in progress."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BusyOverlay")
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._message = QLabel("Loading…")
        self._message.setObjectName("BusyOverlayMessage")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        layout.addWidget(self._message)

    def show_message(self, message: str) -> None:
        self._message.setText(message)
        self._sync_geometry()
        self.show()
        self.raise_()

    def hide_overlay(self) -> None:
        self.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_geometry()

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
