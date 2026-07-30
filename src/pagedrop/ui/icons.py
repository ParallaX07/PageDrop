"""Theme-aware Phosphor SVG toolbar icons.

Vendored regular-weight SVGs live under ``pagedrop/assets/icons/``. Tint uses
chrome text (dark/light) or ``ACCENT``; call ``refresh_icons()`` after a theme
swap so cached pixmaps and registered toolbar rebuilds stay in sync.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from pagedrop.ui.theme import ACCENT, TEXT_PRIMARY

# Matches app_stylesheet(light=True) text_primary (module TEXT_PRIMARY is dark-only).
_TEXT_PRIMARY_LIGHT = "#1A1A1F"
_ICON_SIZES = (16, 20, 24, 32)

_cache: dict[tuple[str, str], QIcon] = {}
_refresh_callbacks: list[Callable[[], None]] = []


def available_names() -> frozenset[str]:
    """Stem names of vendored SVGs (e.g. ``folder-open``)."""
    root = _icons_dir()
    if not root.is_dir():
        return frozenset()
    return frozenset(p.stem for p in root.glob("*.svg"))


def icon(name: str, *, accent: bool = False, color: str | None = None) -> QIcon:
    """Load a vendored Phosphor SVG as a tinted ``QIcon``.

    Default tint is chrome ``TEXT_PRIMARY`` (light-aware). Pass ``accent=True``
    for ``ACCENT``, or ``color`` for an explicit ``#RRGGBB`` override.
    """
    tint = color or (ACCENT if accent else _chrome_text_hex())
    key = (name, tint.lower())
    cached = _cache.get(key)
    if cached is not None:
        return cached

    svg = _load_svg(name)
    tinted = svg.replace("currentColor", tint).encode("utf-8")
    result = QIcon()
    for size in _ICON_SIZES:
        result.addPixmap(_render_pixmap(tinted, size))
    _cache[key] = result
    return result


def refresh_icons() -> None:
    """Drop tinted pixmap cache and notify toolbar rebuild listeners.

    Wired from ``refresh_themed_widgets`` after a light/dark (or HC) swap.
    Call sites that keep ``QIcon`` on actions should ``register_refresh`` and
    re-``setIcon(icon(...))`` so existing toolbars pick up the new tint.
    """
    _cache.clear()
    for callback in list(_refresh_callbacks):
        callback()


def register_refresh(callback: Callable[[], None]) -> None:
    """Register a no-arg callback invoked from ``refresh_icons``."""
    if callback not in _refresh_callbacks:
        _refresh_callbacks.append(callback)


def unregister_refresh(callback: Callable[[], None]) -> None:
    try:
        _refresh_callbacks.remove(callback)
    except ValueError:
        pass


def _chrome_text_hex() -> str:
    from pagedrop.ui.settings import light_theme

    return _TEXT_PRIMARY_LIGHT if light_theme() else TEXT_PRIMARY


def _icons_dir() -> Path:
    return Path(files("pagedrop.assets").joinpath("icons"))


def _load_svg(name: str) -> str:
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"invalid icon name: {name!r}")
    path = _icons_dir() / f"{name}.svg"
    if not path.is_file():
        raise FileNotFoundError(f"unknown toolbar icon: {name!r}")
    return path.read_text(encoding="utf-8")


def _render_pixmap(svg_utf8: bytes, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_utf8))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return pixmap
