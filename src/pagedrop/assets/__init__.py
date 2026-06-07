"""Bundled static assets (logo, etc.)."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QIcon, QImage, QPainter, QPainterPath, QPixmap

_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
_EMPTY_LOGO_LOGICAL_PX = 128
_CORNER_RADIUS_RATIO = 0.22


def logo_path() -> Path:
    return Path(files(__package__).joinpath("logo.png"))


def _load_source_pixmap() -> QPixmap:
    pixmap = QPixmap(str(logo_path()))
    if pixmap.isNull():
        return pixmap
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    return QPixmap.fromImage(image)


def _apply_round_clip(pixmap: QPixmap) -> QPixmap:
    """Clip to a rounded rect so icons look correct on dark UI and Windows."""
    if pixmap.isNull():
        return pixmap
    side = min(pixmap.width(), pixmap.height())
    radius = side * _CORNER_RADIUS_RATIO
    rounded = QPixmap(pixmap.size())
    rounded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(pixmap.rect()), radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return rounded


def _scale_pixmap(source: QPixmap, physical: int) -> QPixmap:
    """Downscale in steps so large sources stay sharp."""
    if source.isNull() or physical <= 0:
        return source

    result = source
    width = result.width()
    height = result.height()
    while max(width, height) > physical * 2:
        width = max(physical, width // 2)
        height = max(physical, height // 2)
        result = result.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    scaled = result.scaled(
        physical,
        physical,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return _apply_round_clip(scaled)


def logo_pixmap(*, logical_size: int, device_pixel_ratio: float = 1.0) -> QPixmap:
    """Return a crisp pixmap scaled for the given logical size and DPR."""
    source = _load_source_pixmap()
    if source.isNull():
        return source
    physical = max(1, round(logical_size * device_pixel_ratio))
    scaled = _scale_pixmap(source, physical)
    scaled.setDevicePixelRatio(device_pixel_ratio)
    return scaled


def empty_state_logo_pixmap(device_pixel_ratio: float = 1.0) -> QPixmap:
    return logo_pixmap(
        logical_size=_EMPTY_LOGO_LOGICAL_PX,
        device_pixel_ratio=device_pixel_ratio,
    )


def app_icon() -> QIcon:
    """Multi-resolution icon so title bar and taskbar stay sharp."""
    source = _load_source_pixmap()
    icon = QIcon()
    if source.isNull():
        return icon
    for size in _ICON_SIZES:
        icon.addPixmap(_scale_pixmap(source, size))
    return icon
