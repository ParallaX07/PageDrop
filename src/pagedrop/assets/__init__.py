"""Bundled static assets (logo, etc.)."""

from __future__ import annotations

import logging
from importlib.resources import files
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
_EMPTY_LOGO_LOGICAL_PX = 128


def logo_path() -> Path:
    return Path(files(__package__).joinpath("logo.svg"))


def fonts_dir() -> Path:
    return Path(files(__package__).joinpath("fonts"))


def register_fonts() -> int:
    """Register the bundled UI fonts; return how many loaded.

    A missing or unreadable font only logs a warning so startup never blocks.
    """
    log = logging.getLogger("pagedrop")
    loaded = 0
    try:
        paths = sorted(fonts_dir().glob("*.ttf"))
    except Exception as exc:
        log.warning("Bundled fonts unavailable: %s", exc)
        return 0
    if not paths:
        log.warning("Bundled fonts not found in %s", fonts_dir())
    for path in paths:
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            log.warning("Could not load bundled font %s", path.name)
        else:
            loaded += 1
    return loaded


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
