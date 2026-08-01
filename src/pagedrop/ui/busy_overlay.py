from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pagedrop.ui.accessibility import prefers_reduce_motion

# info | success | error | warning | undo — property drives theme chrome
ToastKind = str

# Occasional feedback only (Emil frequency rule). Ease-out ~150–200ms.
_MOTION_MS = 180
_EASE_OUT = QEasingCurve.Type.OutCubic
_TOAST_SLIDE_PX = 12
_TOAST_MARGINS = (24, 24, 24, 48)

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

        # Lazy effect — permanent QGraphicsOpacityEffect segfaults on Qt teardown.
        # Init motion fields before hide() — hideEvent clears effects.
        self._opacity_effect: QGraphicsOpacityEffect | None = None
        self._fade = QPropertyAnimation(self)
        self._fade.setPropertyName(b"opacity")
        self._fade.setDuration(_MOTION_MS)
        self._fade.setEasingCurve(_EASE_OUT)
        self._fade.finished.connect(self._on_fade_finished)
        self._hiding = False
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
        # Progress ticks call this while shown — update label only (no opacity re-blink).
        if self.isVisible() and not self._hiding:
            return
        self._hiding = False
        self._fade.stop()
        self.show()
        self.raise_()
        if prefers_reduce_motion():
            self._clear_opacity_effect()
        else:
            # Opacity only — Cancel stays hittable for the whole fade.
            effect = self._ensure_opacity_effect()
            effect.setOpacity(0.0)
            self._fade.setTargetObject(effect)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        self._grab_focus()

    def hide_overlay(self) -> None:
        if not self.isVisible() and not self._hiding:
            return
        self._fade.stop()
        if prefers_reduce_motion() or self._opacity_effect is None:
            self._finish_hide()
            return
        self._hiding = True
        effect = self._opacity_effect
        start = float(effect.opacity())
        self._fade.setTargetObject(effect)
        self._fade.setStartValue(start)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _ensure_opacity_effect(self) -> QGraphicsOpacityEffect:
        if self._opacity_effect is None:
            # Unparented: setGraphicsEffect owns the effect.
            effect = QGraphicsOpacityEffect()
            self.setGraphicsEffect(effect)
            self._opacity_effect = effect
        return self._opacity_effect

    def _clear_opacity_effect(self) -> None:
        self._fade.stop()
        if self._opacity_effect is None:
            return
        self.setGraphicsEffect(None)
        self._opacity_effect = None

    def _on_fade_finished(self) -> None:
        if self._hiding:
            self._finish_hide()

    def _finish_hide(self) -> None:
        self._hiding = False
        self._clear_opacity_effect()
        self.hide()

    def hideEvent(self, event) -> None:  # noqa: N802
        # Drop effect before Qt tears the tree down (avoids exit SIGSEGV).
        self._hiding = False
        if getattr(self, "_fade", None) is not None:
            self._clear_opacity_effect()
        super().hideEvent(event)

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

        # 0 = resting; 1 = slid below + faded out (enter/exit share this axis).
        # Init motion fields before hide() — hideEvent clears effects.
        self._motion_t = 0.0
        self._opacity_effect: QGraphicsOpacityEffect | None = None
        self._motion_anim = QPropertyAnimation(self, b"motion_t", self)
        self._motion_anim.setDuration(_MOTION_MS)
        self._motion_anim.setEasingCurve(_EASE_OUT)
        self._motion_anim.finished.connect(self._on_motion_finished)
        self._exiting = False
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter
        )
        layout.setContentsMargins(*_TOAST_MARGINS)

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
        self._timer.timeout.connect(self._dismiss)
        self._on_undo: Callable[[], None] | None = None

        if parent is not None:
            parent.installEventFilter(self)

    def _ensure_opacity_effect(self) -> QGraphicsOpacityEffect:
        if self._opacity_effect is None:
            effect = QGraphicsOpacityEffect()
            self._card.setGraphicsEffect(effect)
            self._opacity_effect = effect
        return self._opacity_effect

    def _clear_opacity_effect(self) -> None:
        self._motion_anim.stop()
        if self._opacity_effect is None:
            return
        self._card.setGraphicsEffect(None)
        self._opacity_effect = None

    def _get_motion_t(self) -> float:
        return self._motion_t

    def _set_motion_t(self, value: float) -> None:
        self._motion_t = float(value)
        if self._opacity_effect is not None:
            self._opacity_effect.setOpacity(
                max(0.0, min(1.0, 1.0 - self._motion_t))
            )
        left, top, right, bottom = _TOAST_MARGINS
        # AlignBottom: smaller bottom margin sits the card lower (enter from below).
        self.layout().setContentsMargins(
            left,
            top,
            right,
            int(bottom - _TOAST_SLIDE_PX * self._motion_t),
        )

    motion_t = pyqtProperty(float, _get_motion_t, _set_motion_t)

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

        self._exiting = False
        self._motion_anim.stop()
        self._sync_geometry()
        self.show()
        self.raise_()
        if prefers_reduce_motion():
            self._clear_opacity_effect()
            self.motion_t = 0.0
        else:
            self._ensure_opacity_effect()
            self.motion_t = 1.0
            self._motion_anim.setStartValue(1.0)
            self._motion_anim.setEndValue(0.0)
            self._motion_anim.start()
        self._timer.start(timeout_ms)

    def _dismiss(self) -> None:
        if not self.isVisible():
            return
        self._timer.stop()
        if prefers_reduce_motion() or self._opacity_effect is None:
            self.hide()
            return
        self._exiting = True
        self._motion_anim.stop()
        start = self._motion_t
        self._motion_anim.setStartValue(start)
        self._motion_anim.setEndValue(1.0)
        self._motion_anim.start()

    def _on_motion_finished(self) -> None:
        if self._exiting:
            self._exiting = False
            self.hide()
            self.motion_t = 0.0

    def _on_undo_clicked(self) -> None:
        callback = self._on_undo
        self._on_undo = None
        self._exiting = False
        self._timer.stop()
        self.hide()
        self.motion_t = 0.0
        if callback is not None:
            callback()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._exiting = False
        if getattr(self, "_motion_anim", None) is not None and hasattr(
            self, "_card"
        ):
            self._clear_opacity_effect()
        super().hideEvent(event)

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
