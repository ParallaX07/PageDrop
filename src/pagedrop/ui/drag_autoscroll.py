"""Auto-scroll a QScrollArea while dragging near viewport edges or with the wheel."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QPoint, QTimer
from PyQt6.QtWidgets import QScrollArea


class DragAutoScroller:
    """Scroll *area* when the drag cursor sits in edge zones or the wheel is used."""

    EDGE_MARGIN_PX = 48
    TICK_MS = 16
    MIN_SPEED = 3
    MAX_SPEED = 28

    def __init__(self, area: QScrollArea) -> None:
        self._area = area
        self._timer = QTimer(area)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._direction = 0
        self._speed = 0
        self._last_pos: QPoint | None = None
        self._on_scroll: Callable[[QPoint], None] | None = None

    def set_scroll_callback(self, callback: Callable[[QPoint], None]) -> None:
        self._on_scroll = callback

    def update(self, pos_in_area: QPoint) -> None:
        """Call from dragMoveEvent with the cursor position in scroll-area coordinates."""
        self._last_pos = pos_in_area
        viewport = self._area.viewport()
        vp_pos = viewport.mapFrom(self._area, pos_in_area)
        vp_height = viewport.height()

        if vp_pos.y() < self.EDGE_MARGIN_PX:
            self._direction = -1
            self._speed = self._speed_for_distance(self.EDGE_MARGIN_PX - vp_pos.y())
            if not self._timer.isActive():
                self._timer.start()
            return

        if vp_pos.y() > vp_height - self.EDGE_MARGIN_PX:
            self._direction = 1
            self._speed = self._speed_for_distance(
                vp_pos.y() - (vp_height - self.EDGE_MARGIN_PX)
            )
            if not self._timer.isActive():
                self._timer.start()
            return

        self._stop_timer()

    def handle_wheel(self, angle_delta_y: int) -> bool:
        """Scroll vertically from a wheel event; return True if handled."""
        if angle_delta_y == 0:
            return False

        bar = self._area.verticalScrollBar()
        step = bar.singleStep() * angle_delta_y // 120
        if step == 0:
            step = 1 if angle_delta_y > 0 else -1
        bar.setValue(bar.value() - step)
        self._notify_scrolled()
        return True

    def stop(self) -> None:
        self._stop_timer()
        self._last_pos = None

    def _speed_for_distance(self, distance: float) -> int:
        ratio = min(1.0, max(0.0, distance / self.EDGE_MARGIN_PX))
        return int(self.MIN_SPEED + ratio * (self.MAX_SPEED - self.MIN_SPEED))

    def _stop_timer(self) -> None:
        self._direction = 0
        self._speed = 0
        self._timer.stop()

    def _tick(self) -> None:
        if self._direction == 0:
            return
        bar = self._area.verticalScrollBar()
        bar.setValue(bar.value() + self._direction * self._speed)
        self._notify_scrolled()

    def _notify_scrolled(self) -> None:
        if self._on_scroll is not None and self._last_pos is not None:
            self._on_scroll(self._last_pos)
