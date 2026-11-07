"""Theme-aware Phosphor SVG toolbar icons.

Vendored regular-weight SVGs live under ``pagedrop/assets/icons/``. Tint uses
chrome text (dark/light) or the theme ink; call ``refresh_icons()`` after a theme
swap so cached pixmaps and registered toolbar rebuilds stay in sync.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from weakref import WeakMethod

from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from pagedrop.ui.theme import current_theme

_ICON_SIZES = (16, 20, 24, 32)

_cache: dict[tuple[str, str, tuple[float, ...]], QIcon] = {}
_refresh_callbacks: list[Callable[[], None] | WeakMethod] = []


def available_names() -> frozenset[str]:
    """Stem names of vendored SVGs (e.g. ``folder-open``)."""
    root = _icons_dir()
    if not root.is_dir():
        return frozenset()
    return frozenset(p.stem for p in root.glob("*.svg"))


def icon(name: str, *, accent: bool = False, color: str | None = None) -> QIcon:
    """Load a vendored Phosphor SVG as a tinted ``QIcon``.

    Default tint is the chrome text colour (light-aware). Pass ``accent=True``
    for the theme ink, or ``color`` for an explicit ``#RRGGBB`` override.
    """
    tint = color or (current_theme().ink if accent else current_theme().text)
    ratios = _device_pixel_ratios()
    key = (name, tint.lower(), ratios)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    svg = _load_svg(name)
    tinted = svg.replace("currentColor", tint).encode("utf-8")
    result = QIcon()
    for size in _ICON_SIZES:
        for ratio in ratios:
            result.addPixmap(_render_pixmap(tinted, size, ratio))
    _cache[key] = result
    return result


def _device_pixel_ratios() -> tuple[float, ...]:
    """Device pixel ratios of the connected screens, always including 1.0."""
    ratios = {1.0}
    ratios.update(float(screen.devicePixelRatio()) for screen in QGuiApplication.screens())
    return tuple(sorted(ratios))


def _owner_deleted(callback: Callable[[], None]) -> bool:
    """True when ``callback`` is bound to a Qt object whose C++ side is gone."""
    owner = getattr(callback, "__self__", None)
    return isinstance(owner, sip.simplewrapper) and sip.isdeleted(owner)


def refresh_icons() -> None:
    """Drop tinted pixmap cache and notify toolbar rebuild listeners.

    Wired from ``refresh_themed_widgets`` after a light/dark (or HC) swap.
    Call sites that keep ``QIcon`` on actions should ``register_refresh`` and
    re-``setIcon(icon(...))`` so existing toolbars pick up the new tint.
    """
    _cache.clear()
    for registered in list(_refresh_callbacks):
        callback = registered() if isinstance(registered, WeakMethod) else registered
        if callback is None or _owner_deleted(callback):
            _refresh_callbacks.remove(registered)
            continue
        callback()


def register_refresh(callback: Callable[[], None]) -> None:
    """Register a no-arg callback invoked from ``refresh_icons``."""
    if any(
        (registered() if isinstance(registered, WeakMethod) else registered) == callback
        for registered in _refresh_callbacks
    ):
        return
    _refresh_callbacks.append(
        WeakMethod(callback) if getattr(callback, "__self__", None) is not None else callback
    )


def unregister_refresh(callback: Callable[[], None]) -> None:
    _refresh_callbacks[:] = [
        registered
        for registered in _refresh_callbacks
        if (registered() if isinstance(registered, WeakMethod) else registered) not in (None, callback)
    ]


def _icons_dir() -> Path:
    return Path(files("pagedrop.assets").joinpath("icons"))


def _load_svg(name: str) -> str:
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"invalid icon name: {name!r}")
    path = _icons_dir() / f"{name}.svg"
    if not path.is_file():
        raise FileNotFoundError(f"unknown toolbar icon: {name!r}")
    return path.read_text(encoding="utf-8")


def _render_pixmap(svg_utf8: bytes, size: int, ratio: float = 1.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_utf8))
    pixels = math.ceil(size * ratio)
    pixmap = QPixmap(pixels, pixels)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    logical = pixels / ratio
    renderer.render(painter, QRectF(0, 0, logical, logical))
    painter.end()
    return pixmap
