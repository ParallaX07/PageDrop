from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, QTimer
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


class ToastOverlay(QWidget):
    """Non-blocking auto-dismiss notice; same chrome as BusyOverlay, no dimming."""

    DEFAULT_TIMEOUT_MS = 2500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ToastOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter
        )
        layout.setContentsMargins(24, 24, 24, 48)

        self._message = QLabel()
        self._message.setObjectName("ToastOverlayMessage")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        layout.addWidget(self._message)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        if parent is not None:
            parent.installEventFilter(self)

    def show_toast(
        self, message: str, timeout_ms: int = DEFAULT_TIMEOUT_MS
    ) -> None:
        self._message.setText(message)
        self._sync_geometry()
        self.show()
        self.raise_()
        self._timer.start(timeout_ms)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._sync_geometry()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_geometry()

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
