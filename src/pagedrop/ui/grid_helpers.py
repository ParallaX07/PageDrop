from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QWidget

from pagedrop.ui.accessibility import prefers_reduce_motion
from pagedrop.ui.theme import ZOOM_WHEEL_STEP

# Show/hide only — reposition while visible stays instant (R10d / Emil).
_DROP_FADE_MS = 120
_DROP_EASE = QEasingCurve.Type.OutCubic


class DropIndicator(QFrame):
    """Vertical insertion bar; opacity fade on first show / final hide only."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropIndicator")
        self.setFixedWidth(3)
        # Lazy effect — permanent QGraphicsOpacityEffect can segfault on teardown.
        self._opacity_effect: QGraphicsOpacityEffect | None = None
        self._fade = QPropertyAnimation(self)
        self._fade.setPropertyName(b"opacity")
        self._fade.setDuration(_DROP_FADE_MS)
        self._fade.setEasingCurve(_DROP_EASE)
        self._fade.finished.connect(self._on_fade_finished)
        self._hiding = False
        self.hide()

    def place(self, rect: QRect) -> None:
        """Move to ``rect``; fade in only when becoming visible."""
        self.setGeometry(rect)
        if self.isVisible() and not self._hiding:
            self.raise_()
            return
        was_hiding = self._hiding
        self._hiding = False
        self._fade.stop()
        self.show()
        self.raise_()
        if prefers_reduce_motion():
            self._clear_opacity_effect()
            return
        effect = self._ensure_opacity_effect()
        if was_hiding:
            start = float(effect.opacity())
        else:
            start = 0.0
            effect.setOpacity(0.0)
        self._fade.setTargetObject(effect)
        self._fade.setStartValue(start)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def dismiss(self) -> None:
        """Fade out then hide; instant under reduce-motion."""
        if not self.isVisible() and not self._hiding:
            return
        self._fade.stop()
        if prefers_reduce_motion() or self._opacity_effect is None:
            self._finish_hide()
            return
        self._hiding = True
        effect = self._opacity_effect
        self._fade.setTargetObject(effect)
        self._fade.setStartValue(float(effect.opacity()))
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _ensure_opacity_effect(self) -> QGraphicsOpacityEffect:
        if self._opacity_effect is None:
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
        self._hiding = False
        if getattr(self, "_fade", None) is not None:
            self._clear_opacity_effect()
        super().hideEvent(event)


def drop_index_at_pos(cards: Sequence[QWidget], pos: QPoint) -> int:
    """Return the logical insertion index (0…N) for a point in container coords."""
    if not cards:
        return 0

    for index, card in enumerate(cards):
        rect = card.geometry()
        if not rect.contains(pos):
            continue
        local_x = pos.x() - rect.x()
        if local_x < rect.width() / 2:
            return index
        return index + 1

    nearest_index = 0
    nearest_distance = float("inf")
    for index, card in enumerate(cards):
        rect = card.geometry()
        center = rect.center()
        distance = (pos.x() - center.x()) ** 2 + (pos.y() - center.y()) ** 2
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_index = index if pos.x() < center.x() else index + 1

    return min(max(nearest_index, 0), len(cards))


def drop_indicator_rect(
    cards: Sequence[QWidget],
    spacing: int,
    insertion_index: int,
) -> QRect | None:
    """Geometry for a vertical drop bar between cards, or None if empty."""
    if not cards:
        return None

    gap = max(spacing // 2, 2)
    if insertion_index >= len(cards):
        card = cards[-1]
        x = card.x() + card.width() + gap
    else:
        card = cards[insertion_index]
        x = max(card.x() - gap, 0)

    return QRect(x, card.y(), 3, card.height())


def ctrl_wheel_zoom_step(event, step: int = ZOOM_WHEEL_STEP) -> int | None:
    """Return zoom delta for Ctrl+wheel, or None if the event should scroll normally."""
    if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
        return None
    delta = event.angleDelta().y()
    if delta == 0:
        return None
    return step if delta > 0 else -step
