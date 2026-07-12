from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import QWidget

from pagedrop.ui.theme import ZOOM_WHEEL_STEP


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
