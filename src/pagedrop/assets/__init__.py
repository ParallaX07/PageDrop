"""Bundled static assets (logo, etc.)."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
_EMPTY_LOGO_LOGICAL_PX = 128


def logo_path() -> Path:
    return Path(files(__package__).joinpath("logo.svg"))


def _render_logo(physical: int) -> QPixmap:
    """Render the SVG logo at an exact physical size; null if it cannot load."""
    renderer = QSvgRenderer(str(logo_path()))
    if not renderer.isValid() or physical <= 0:
        return QPixmap()
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return pixmap


def logo_pixmap(*, logical_size: int, device_pixel_ratio: float = 1.0) -> QPixmap:
    """Return a crisp pixmap rendered for the given logical size and DPR."""
    pixmap = _render_logo(max(1, round(logical_size * device_pixel_ratio)))
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap


def empty_state_logo_pixmap(device_pixel_ratio: float = 1.0) -> QPixmap:
    return logo_pixmap(
        logical_size=_EMPTY_LOGO_LOGICAL_PX,
        device_pixel_ratio=device_pixel_ratio,
    )


def app_icon() -> QIcon:
    """Multi-resolution icon so title bar and taskbar stay sharp."""
    icon = QIcon()
    for size in _ICON_SIZES:
        pixmap = _render_logo(size)
        if pixmap.isNull():
            return QIcon()
        icon.addPixmap(pixmap)
    return icon
