from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)


class ZoomControls(QWidget):
    """Compact thumbnail zoom cluster: −, slider, +, and pixel readout."""

    zoom_requested = pyqtSignal(int)

    def __init__(
        self,
        *,
        min_width: int,
        max_width: int,
        step: int,
        initial: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._min_width = min_width
        self._max_width = max_width
        self._step = step
        self._syncing = False
        self._current = initial

        self.setObjectName("ZoomControls")
        self.setToolTip("Thumbnail size (Ctrl+scroll)")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 8, 4)
        layout.setSpacing(6)

        self._caption = QLabel("Zoom")
        self._caption.setObjectName("ZoomCaption")

        self._zoom_out = QPushButton("−")
        self._zoom_out.setObjectName("ZoomButton")
        self._zoom_out.setToolTip("Zoom out (−)")
        self._zoom_out.setFixedSize(28, 28)
        self._zoom_out.clicked.connect(self._on_zoom_out)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("ZoomSlider")
        self._slider.setFixedWidth(128)
        self._slider.setRange(0, (max_width - min_width) // step)
        self._slider.valueChanged.connect(self._on_slider_changed)

        self._zoom_in = QPushButton("+")
        self._zoom_in.setObjectName("ZoomButton")
        self._zoom_in.setToolTip("Zoom in (+)")
        self._zoom_in.setFixedSize(28, 28)
        self._zoom_in.clicked.connect(self._on_zoom_in)

        self._value_label = QLabel()
        self._value_label.setObjectName("ZoomValueLabel")
        self._value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._value_label.setFixedWidth(44)

        layout.addWidget(self._caption)
        layout.addWidget(self._zoom_out)
        layout.addWidget(self._slider)
        layout.addWidget(self._zoom_in)
        layout.addWidget(self._value_label)

        self.set_value(initial)
        self.setEnabled(False)

    def set_value(self, width_px: int) -> None:
        clamped = max(self._min_width, min(self._max_width, width_px))
        self._current = clamped
        self._syncing = True
        step_index = (clamped - self._min_width) // self._step
        self._slider.setValue(step_index)
        self._value_label.setText(f"{clamped}px")
        self._update_button_states(clamped)
        self._syncing = False

    def _on_slider_changed(self, step_index: int) -> None:
        if self._syncing:
            return
        width_px = self._min_width + step_index * self._step
        if width_px != self._current:
            self.zoom_requested.emit(width_px)

    def _on_zoom_out(self) -> None:
        self.zoom_requested.emit(max(self._min_width, self._current - self._step))

    def _on_zoom_in(self) -> None:
        self.zoom_requested.emit(min(self._max_width, self._current + self._step))

    def _update_button_states(self, width_px: int) -> None:
        self._zoom_out.setEnabled(width_px > self._min_width)
        self._zoom_in.setEnabled(width_px < self._max_width)
