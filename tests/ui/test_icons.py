"""R4: Phosphor SVG icon helper — load, tint, theme refresh."""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QIcon


def test_available_names_cover_toolbar_set():
    from pagedrop.ui.icons import available_names

    names = available_names()
    for expected in (
        "folder-open",
        "folder",
        "trash",
        "arrow-up",
        "arrow-down",
        "arrow-left",
        "arrow-clockwise",
        "arrow-counter-clockwise",
        "arrows-down-up",
        "copy",
        "floppy-disk",
        "list",
        "selection-all",
        "selection-slash",
        "x",
        "check",
        "minus",
        "plus",
        "stack",
        "scissors",
        "lock",
    ):
        assert expected in names


def test_tab_close_icon_uses_phosphor_x(qapp):
    from pagedrop.ui.theme import tab_close_icon

    icon = tab_close_icon()
    assert not icon.isNull()
    # Explicit tint still works (destructive red path).
    tinted = tab_close_icon(color="#E85D5D")
    assert not tinted.isNull()


def test_tab_close_button_is_toolbutton_with_icon(qapp):
    """Qt's built-in CloseButton ignores setIcon; we replace it with QToolButton."""
    from PyQt6.QtWidgets import QTabBar, QToolButton

    from pagedrop.ui.tab_manager import TabManager
    from pagedrop.utils.temp_manager import TempManager

    tabs = TabManager(TempManager())
    tabs.add_blank_tab()
    btn = tabs.tabBar().tabButton(0, QTabBar.ButtonPosition.RightSide)
    assert isinstance(btn, QToolButton)
    assert btn.objectName() == "TabCloseButton"
    assert not btn.icon().isNull()
    assert btn.accessibleName() == "Close tab"


def test_catalogue_icons_are_vendored():
    from pagedrop.ui.icons import available_names
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    names = available_names()
    for entry in TOOL_CATALOGUE:
        assert entry.icon, f"{entry.id} missing icon"
        assert entry.icon in names, f"{entry.id} → unknown icon {entry.icon!r}"


def test_icon_returns_non_null_for_each_vendored_name(qapp):
    from pagedrop.ui.icons import available_names, icon

    for name in sorted(available_names()):
        result = icon(name)
        assert isinstance(result, QIcon)
        assert not result.isNull(), name


def test_icon_accent_and_unknown_name(qapp):
    from pagedrop.ui.icons import icon

    accented = icon("trash", accent=True)
    assert not accented.isNull()
    with pytest.raises(FileNotFoundError):
        icon("not-a-real-glyph")


def test_refresh_icons_clears_cache_and_notifies(qapp, isolated_settings):
    from pagedrop.ui.accessibility import refresh_themed_widgets
    from pagedrop.ui.icons import icon, register_refresh, unregister_refresh
    from pagedrop.ui.settings import set_light_theme

    calls: list[int] = []

    def _on_refresh() -> None:
        calls.append(1)

    register_refresh(_on_refresh)
    try:
        dark = icon("folder-open")
        assert not dark.isNull()
        set_light_theme(True)
        refresh_themed_widgets()
        assert calls == [1]
        light = icon("folder-open")
        assert not light.isNull()
        # Fresh QIcon after theme swap (cache was cleared).
        assert light is not dark
    finally:
        unregister_refresh(_on_refresh)
        set_light_theme(False)
