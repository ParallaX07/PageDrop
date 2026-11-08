"""Theme-aware Phosphor SVG toolbar icons.

Vendored regular-weight SVGs live under ``pagedrop/assets/icons/``. Tint uses
chrome text (dark/light) or the theme ink; call ``refresh_icons()`` after a theme
swap so cached pixmaps and registered toolbar rebuilds stay in sync.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from weakref import WeakMethod

from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from pagedrop.ui.theme import current_theme
from pagedrop.utils.temp_manager import TempManager

_LOG = logging.getLogger("pagedrop")

_ICON_SIZES = (16, 20, 24, 32)

_cache: dict[tuple[str, str, str, tuple[float, ...]], QIcon] = {}
_refresh_callbacks: list[Callable[[], None] | WeakMethod] = []
# Shared by every window and removed at exit; a window's own manager is gone
# once that window closes while the style sheet still points at these files.
_indicator_manager: TempManager | None = None
# Indicator PNGs handed to the style sheet, so a deleted file can be noticed.
_issued_indicators: set[Path] = set()


def available_names() -> frozenset[str]:
    """Stem names of vendored SVGs (e.g. ``folder-open``)."""
    root = _icons_dir()
    if not root.is_dir():
        return frozenset()
    return frozenset(p.stem for p in root.glob("*.svg"))


def icon(
    name: str,
    *,
    accent: bool = False,
    color: str | None = None,
    active_color: str | None = None,
) -> QIcon:
    """Load a vendored Phosphor SVG as a tinted ``QIcon``.

    Default tint is the chrome text colour (light-aware). Pass ``accent=True``
    for the theme ink, or ``color`` for an explicit ``#RRGGBB`` override.
    ``active_color`` adds the tint used while the pointer is over an auto-raise
    tool button.
    """
    tint = color or (current_theme().ink if accent else current_theme().text)
    ratios = _device_pixel_ratios()
    key = (name, tint.lower(), (active_color or "").lower(), ratios)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    svg = _load_svg(name)
    result = QIcon()
    for mode, mode_tint in ((QIcon.Mode.Normal, tint), (QIcon.Mode.Active, active_color)):
        if mode_tint is None:
            continue
        tinted = svg.replace("currentColor", mode_tint).encode("utf-8")
        for size in _ICON_SIZES:
            for ratio in ratios:
                result.addPixmap(_render_pixmap(tinted, size, ratio), mode)
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


def _render_image(
    svg_utf8: bytes, size: int, ratio: float = 1.0, canvas: int | None = None
) -> QImage:
    """Render at ``size`` logical px, centred on a transparent ``canvas`` square."""
    renderer = QSvgRenderer(QByteArray(svg_utf8))
    canvas = canvas or size
    pixels = math.ceil(canvas * ratio)
    image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    logical = pixels / ratio
    inset = (logical - size) / 2
    renderer.render(painter, QRectF(inset, inset, size, size))
    painter.end()
    return image


def _render_pixmap(svg_utf8: bytes, size: int, ratio: float = 1.0) -> QPixmap:
    return QPixmap.fromImage(_render_image(svg_utf8, size, ratio))


def _indicator_dir() -> Path:
    global _indicator_manager
    # A cleaner of /tmp may remove the directory while the app runs; a fresh
    # manager brings back the owner marker and the exit cleanup.
    if _indicator_manager is None or not _indicator_manager.get_dir().is_dir():
        _indicator_manager = TempManager()
    return _indicator_manager.get_dir()


def indicator_files_present() -> bool:
    """False once if an indicator image handed out earlier has gone missing.

    Missing files are forgotten, so a tint no longer in use cannot keep
    reporting a loss; rebuilding the style sheet re-renders the ones in use.
    """
    missing = {
        path
        for path in _issued_indicators
        if not (path.is_file() and path.with_name(f"{path.stem}@2x.png").is_file())
    }
    _issued_indicators.difference_update(missing)
    return not missing


def indicator_path(
    name: str, *, color: str, size: int, canvas: int | None = None
) -> str | None:
    """Path of a tinted PNG for a style sheet ``image:`` rule, rendered on demand.

    A ``<name>-<size>-<hex>.png`` file and its ``@2x`` sibling are written once
    per tint and reused until they go missing. With ``canvas`` the mark keeps
    ``size`` but sits centred on a transparent square of that side, which Qt
    would otherwise stretch to fill a fixed-size indicator on a 2x display.
    Returns ``None`` (after logging a warning) when they cannot be written, so
    the style sheet just omits the image. Works without a ``QGuiApplication``.
    """
    try:
        stem = f"{name}-{size}{f'in{canvas}' if canvas else ''}-{color.lstrip('#').lower()}"
        target = _indicator_dir() / f"{stem}.png"
        retina = target.with_name(f"{stem}@2x.png")
        if not (target.is_file() and retina.is_file()):
            tinted = _load_svg(name).replace("currentColor", color).encode("utf-8")
            for path, ratio in ((target, 1.0), (retina, 2.0)):
                if not _render_image(tinted, size, ratio, canvas).save(str(path), "PNG"):
                    raise OSError(f"could not write {path}")
    except (OSError, ValueError) as exc:
        _LOG.warning("Could not render indicator image %r: %s", name, exc)
        return None
    _issued_indicators.add(target)
    return target.as_posix()
