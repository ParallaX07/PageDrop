"""Persistent user preferences via QSettings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PyQt6.QtCore import QByteArray, QSettings

ORGANIZATION = "PageDrop"
APPLICATION = "PageDrop"
KEY_LAST_DIRECTORY = "files/lastDirectory"
KEY_RECENT_FILES = "files/recent"
KEY_REDUCE_MOTION = "accessibility/reduce_motion"
KEY_CONFIRM_DELETE_MULTIPLE = "safety/confirm_before_deleting_multiple_pages"
KEY_CONFIRM_CLOSE_DIRTY = "safety/confirm_before_closing_dirty_tabs"
KEY_REMEMBER_GEOMETRY = "window/remember_geometry"
KEY_WINDOW_GEOMETRY = "window/geometry"
KEY_LIGHT_THEME = "view/light_theme"
KEY_THUMBNAIL_QUALITY = "view/thumbnail_quality"
KEY_THUMBNAIL_ZOOM = "view/thumbnail_zoom"
KEY_HAS_SEEN_TIPS = "onboarding/has_seen_tips"

# Confirm multi-page delete when selection size exceeds this (instant for ≤3).
DELETE_CONFIRM_THRESHOLD = 3
RECENT_FILES_MAX = 10

ThumbnailQuality = Literal["low", "medium", "high"]
THUMBNAIL_QUALITY_VALUES: tuple[ThumbnailQuality, ...] = ("low", "medium", "high")
# Max PNG render width for each quality band (display zoom may be larger).
THUMBNAIL_QUALITY_CAP_PX: dict[ThumbnailQuality, int] = {
    "low": 160,
    "medium": 320,
    "high": 480,
}


def _settings() -> QSettings:
    return QSettings(ORGANIZATION, APPLICATION)


def last_directory() -> str:
    """Last folder used in the open-file dialog, or empty string."""
    value = _settings().value(KEY_LAST_DIRECTORY, "")
    if not value:
        return ""
    path = Path(str(value))
    if path.is_dir():
        return str(path)
    return ""


def remember_directory(path: str | Path) -> None:
    """Store the parent directory of an opened file (or the path if it is a folder)."""
    resolved = Path(path)
    directory = resolved.parent if resolved.is_file() else resolved
    if directory.is_dir():
        _settings().setValue(KEY_LAST_DIRECTORY, str(directory))


def recent_files() -> list[str]:
    """Most recently opened PDF paths (newest first), missing files omitted."""
    raw = _settings().value(KEY_RECENT_FILES, [])
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        path = Path(str(item))
        key = str(path.resolve()) if path.exists() else ""
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(str(path))
        if len(result) >= RECENT_FILES_MAX:
            break
    return result


def remember_recent_file(path: str | Path) -> None:
    """Prepend *path* to the recent-files list (deduped, capped)."""
    resolved = Path(path)
    if not resolved.is_file():
        return
    key = str(resolved.resolve())
    existing = [
        p
        for p in recent_files()
        if str(Path(p).resolve()) != key
    ]
    _settings().setValue(KEY_RECENT_FILES, [key, *existing][:RECENT_FILES_MAX])


def reduce_motion() -> bool:
    """User preference to minimize non-essential motion (default: False)."""
    return _settings().value(KEY_REDUCE_MOTION, False, type=bool)


def set_reduce_motion(enabled: bool) -> None:
    _settings().setValue(KEY_REDUCE_MOTION, bool(enabled))


def confirm_before_deleting_multiple_pages() -> bool:
    """Ask before deleting more than DELETE_CONFIRM_THRESHOLD pages (default: True)."""
    return _settings().value(KEY_CONFIRM_DELETE_MULTIPLE, True, type=bool)


def set_confirm_before_deleting_multiple_pages(enabled: bool) -> None:
    _settings().setValue(KEY_CONFIRM_DELETE_MULTIPLE, bool(enabled))


def confirm_before_closing_dirty_tabs() -> bool:
    """Ask before closing tabs with unsaved edits (default: True)."""
    return _settings().value(KEY_CONFIRM_CLOSE_DIRTY, True, type=bool)


def set_confirm_before_closing_dirty_tabs(enabled: bool) -> None:
    _settings().setValue(KEY_CONFIRM_CLOSE_DIRTY, bool(enabled))


def remember_window_geometry() -> bool:
    """Restore main-window size/position on launch (default: True)."""
    return _settings().value(KEY_REMEMBER_GEOMETRY, True, type=bool)


def set_remember_window_geometry(enabled: bool) -> None:
    _settings().setValue(KEY_REMEMBER_GEOMETRY, bool(enabled))


def save_window_geometry(geometry: QByteArray) -> None:
    """Persist ``QWidget.saveGeometry()`` bytes when the preference is on."""
    if not remember_window_geometry():
        return
    _settings().setValue(KEY_WINDOW_GEOMETRY, geometry)


def load_window_geometry() -> QByteArray | None:
    """Return saved geometry bytes, or None when unset / preference off."""
    if not remember_window_geometry():
        return None
    value = _settings().value(KEY_WINDOW_GEOMETRY)
    if isinstance(value, QByteArray) and not value.isEmpty():
        return value
    if isinstance(value, (bytes, bytearray)) and value:
        return QByteArray(value)
    return None


def light_theme() -> bool:
    """Use the light app chrome (default: False / dark)."""
    return _settings().value(KEY_LIGHT_THEME, False, type=bool)


def set_light_theme(enabled: bool) -> None:
    _settings().setValue(KEY_LIGHT_THEME, bool(enabled))


def thumbnail_quality() -> ThumbnailQuality:
    """User-visible thumbnail render quality band (default: high)."""
    raw = str(_settings().value(KEY_THUMBNAIL_QUALITY, "high")).lower()
    if raw in THUMBNAIL_QUALITY_CAP_PX:
        return raw  # type: ignore[return-value]
    return "high"


def set_thumbnail_quality(quality: ThumbnailQuality | str) -> None:
    value = str(quality).lower()
    if value not in THUMBNAIL_QUALITY_CAP_PX:
        raise ValueError(f"Unknown thumbnail quality: {quality!r}")
    _settings().setValue(KEY_THUMBNAIL_QUALITY, value)


def thumbnail_render_width(display_width_px: int) -> int:
    """PNG render width for *display_width_px* under the current quality band."""
    from pagedrop.ui.theme import MAX_THUMBNAIL_WIDTH, MIN_THUMBNAIL_WIDTH

    cap = THUMBNAIL_QUALITY_CAP_PX[thumbnail_quality()]
    return max(
        MIN_THUMBNAIL_WIDTH,
        min(int(display_width_px), cap, MAX_THUMBNAIL_WIDTH),
    )


def thumbnail_zoom() -> int:
    """Last-used thumbnail display width in px (global default)."""
    from pagedrop.ui.theme import (
        DEFAULT_THUMBNAIL_WIDTH,
        MAX_THUMBNAIL_WIDTH,
        MIN_THUMBNAIL_WIDTH,
    )

    raw = _settings().value(KEY_THUMBNAIL_ZOOM, DEFAULT_THUMBNAIL_WIDTH)
    try:
        width = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_THUMBNAIL_WIDTH
    return max(MIN_THUMBNAIL_WIDTH, min(width, MAX_THUMBNAIL_WIDTH))


def set_thumbnail_zoom(width_px: int) -> None:
    from pagedrop.ui.theme import MAX_THUMBNAIL_WIDTH, MIN_THUMBNAIL_WIDTH

    clamped = max(MIN_THUMBNAIL_WIDTH, min(int(width_px), MAX_THUMBNAIL_WIDTH))
    _settings().setValue(KEY_THUMBNAIL_ZOOM, clamped)


def has_seen_tips() -> bool:
    """True after the first-run tips overlay has been dismissed."""
    return _settings().value(KEY_HAS_SEEN_TIPS, False, type=bool)


def set_has_seen_tips(seen: bool = True) -> None:
    _settings().setValue(KEY_HAS_SEEN_TIPS, bool(seen))