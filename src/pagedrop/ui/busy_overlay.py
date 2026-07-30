from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

# info | success | error | warning | undo — property drives theme chrome
ToastKind = str

# Accessible description so AT hears kind, not only the message text.
_TOAST_KIND_A11Y: dict[str, str] = {
    "success": "Success notification",
    "error": "Error notification",
    "warning": "Warning notification",
    "undo": "Undo notification",
    "info": "Notification",
}


class BusyOverlay(QWidget):
    """Semi-transparent overlay that blocks interaction while work is in progress."""

    cancelled = pyqtSignal()
    # Escape while busy but Cancel is hidden — hosts toast/status "still running…".
    escape_blocked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BusyOverlay")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Busy")
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._panel = QWidget()
        self._panel.setObjectName("BusyOverlayPanel")
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(12)
        panel_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._message = QLabel("Loading…")
        self._message.setObjectName("BusyOverlayMessage")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        panel_layout.addWidget(self._message)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("BusyOverlayCancel")
        self._cancel_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._cancel_btn.setAccessibleName("Cancel")
        self._cancel_btn.clicked.connect(self.cancelled.emit)
        self._cancel_btn.hide()
        self._cancel_btn.installEventFilter(self)
        panel_layout.addWidget(
            self._cancel_btn, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        layout.addWidget(self._panel)

    def set_cancellable(self, enabled: bool) -> None:
        """Show or hide the inline Cancel button (Tools jobs enable this)."""
        self._cancel_btn.setVisible(enabled)

    def show_message(self, message: str) -> None:
        self._message.setText(message)
        self.setAccessibleDescription(message)
        self._sync_geometry()
        self.show()
        self.raise_()
        self._grab_focus()

    def hide_overlay(self) -> None:
        self.hide()

    def _escape_cancels(self) -> bool:
        return (
            self.isVisible()
            and self._cancel_btn.isVisible()
            and self._cancel_btn.isEnabled()
        )

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.isVisible():
            if self._escape_cancels():
                self.cancelled.emit()
            else:
                self.escape_blocked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        # Cancel holds focus while busy — Escape must still map to cancel.
        if (
            watched is self._cancel_btn
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
            and self._escape_cancels()
        ):
            self.cancelled.emit()
            return True
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._grab_focus()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_geometry()

    def _grab_focus(self) -> None:
        """Take keyboard focus so Escape reaches Cancel while the overlay is up."""
        if self._cancel_btn.isVisible() and self._cancel_btn.isEnabled():
            self._cancel_btn.setFocus(Qt.FocusReason.PopupFocusReason)
        else:
            self.setFocus(Qt.FocusReason.PopupFocusReason)

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())


class ToastOverlay(QWidget):
    """Non-blocking auto-dismiss notice; same chrome as BusyOverlay, no dimming.

    Thin helper — not a notification manager. Use ``kind`` for chrome and
    ``on_undo`` when the notice offers a one-shot undo affordance.
    """

    DEFAULT_TIMEOUT_MS = 2500
    ERROR_TIMEOUT_MS = 6000
    UNDO_TIMEOUT_MS = 8000

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

        self._card = QWidget()
        self._card.setObjectName("ToastOverlayCard")
        card_layout = QHBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(8)

        self._message = QLabel()
        self._message.setObjectName("ToastOverlayMessage")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        card_layout.addWidget(self._message)

        self._undo_button = QPushButton("Undo")
        self._undo_button.setObjectName("ToastOverlayUndo")
        self._undo_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._undo_button.setAccessibleName("Undo")
        self._undo_button.clicked.connect(self._on_undo_clicked)
        self._undo_button.hide()
        card_layout.addWidget(self._undo_button)

        layout.addWidget(self._card)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._on_undo: Callable[[], None] | None = None

        if parent is not None:
            parent.installEventFilter(self)

    def show_toast(
        self,
        message: str,
        *,
        kind: ToastKind = "info",
        timeout_ms: int | None = None,
        on_undo: Callable[[], None] | None = None,
    ) -> None:
        self._message.setText(message)
        self._message.setProperty("kind", kind)
        # Announce to assistive tech when the toast appears (O1).
        self._message.setAccessibleName(message)
        self._message.setAccessibleDescription(
            _TOAST_KIND_A11Y.get(kind, "Notification")
        )
        style = self._message.style()
        if style is not None:
            style.unpolish(self._message)
            style.polish(self._message)

        self._on_undo = on_undo
        if on_undo is not None:
            self.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
            )
            self._undo_button.show()
            if timeout_ms is None:
                timeout_ms = self.UNDO_TIMEOUT_MS
        else:
            self.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            self._undo_button.hide()
            if timeout_ms is None:
                # Errors stay longer so they aren't missed after dialogs close.
                timeout_ms = (
                    self.ERROR_TIMEOUT_MS
                    if kind == "error"
                    else self.DEFAULT_TIMEOUT_MS
                )

        self._sync_geometry()
        self.show()
        self.raise_()
        self._timer.start(timeout_ms)

    def _on_undo_clicked(self) -> None:
        callback = self._on_undo
        self._on_undo = None
        self.hide()
        self._timer.stop()
        if callback is not None:
            callback()

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
