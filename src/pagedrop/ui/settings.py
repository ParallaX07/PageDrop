"""Persistent user preferences via QSettings."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings

ORGANIZATION = "PageDrop"
APPLICATION = "PageDrop"
KEY_LAST_DIRECTORY = "files/lastDirectory"
KEY_REDUCE_MOTION = "accessibility/reduce_motion"


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


def reduce_motion() -> bool:
    """User preference to minimize non-essential motion (default: False)."""
    return _settings().value(KEY_REDUCE_MOTION, False, type=bool)


def set_reduce_motion(enabled: bool) -> None:
    _settings().setValue(KEY_REDUCE_MOTION, bool(enabled))
