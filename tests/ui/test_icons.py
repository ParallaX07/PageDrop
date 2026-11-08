"""R4: Phosphor SVG icon helper — load, tint, theme refresh."""

from __future__ import annotations

import gc
from weakref import WeakMethod, ref

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QIcon, QImage


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
        "check-bold",
        "caret-down-bold",
        "caret-up-bold",
        "circle-fill",
        "square",
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

    class _WidgetCallback:
        def refresh(self) -> None:
            pytest.fail("Destroyed widget callback was retained")

    register_refresh(_on_refresh)
    stale = _WidgetCallback()
    stale_ref = ref(stale)
    register_refresh(stale.refresh)
    del stale
    gc.collect()
    try:
        dark = icon("folder-open")
        assert not dark.isNull()
        set_light_theme(True)
        refresh_themed_widgets()
        assert calls == [1]
        assert stale_ref() is None
        light = icon("folder-open")
        assert not light.isNull()
        # Fresh QIcon after theme swap (cache was cleared).
        assert light is not dark
    finally:
        unregister_refresh(_on_refresh)
        set_light_theme(False)


def test_refresh_icons_prunes_widget_with_deleted_cpp_object(qapp, isolated_settings):
    from PyQt6 import sip
    from PyQt6.QtWidgets import QWidget

    from pagedrop.ui.accessibility import refresh_themed_widgets
    from pagedrop.ui.icons import _refresh_callbacks, register_refresh, unregister_refresh

    class _Owner(QWidget):
        def refresh(self) -> None:
            pytest.fail("Callback of a deleted widget was invoked")

    calls: list[int] = []

    def _alive() -> None:
        calls.append(1)

    owner = _Owner()
    register_refresh(owner.refresh)
    register_refresh(_alive)
    sip.delete(owner)
    try:
        refresh_themed_widgets()
        assert calls == [1]
        assert not any(
            isinstance(registered, WeakMethod)
            and getattr(registered(), "__self__", None) is owner
            for registered in _refresh_callbacks
        )
    finally:
        unregister_refresh(_alive)


def test_zoom_controls_is_collectable_after_delete(qapp):
    from pagedrop.ui.zoom_controls import ZoomControls

    controls = ZoomControls(min_width=100, max_width=400, step=20, initial=200)
    controls_ref = ref(controls)
    controls.deleteLater()
    del controls
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    assert controls_ref() is None


def _reference_render(name: str, tint: str, pixels: int):
    """Independent render of the tinted SVG straight at ``pixels`` square."""
    from PyQt6.QtCore import QByteArray, Qt
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    from pagedrop.ui.icons import _load_svg

    svg = _load_svg(name).replace("currentColor", tint).encode()
    image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    QSvgRenderer(QByteArray(svg)).render(painter)
    painter.end()
    return image


def test_device_pixel_ratios_include_one_and_dedupe(monkeypatch, qapp):
    from pagedrop.ui import icons

    class _Screen:
        def __init__(self, ratio):
            self._ratio = ratio

        def devicePixelRatio(self):  # noqa: N802
            return self._ratio

    class _App:
        @staticmethod
        def screens():
            return [_Screen(2.0), _Screen(1.5), _Screen(2.0)]

    monkeypatch.setattr(icons, "QGuiApplication", _App)
    assert icons._device_pixel_ratios() == (1.0, 1.5, 2.0)

    _App.screens = staticmethod(lambda: [])
    assert icons._device_pixel_ratios() == (1.0,)


def test_icon_renders_natively_at_each_device_pixel_ratio(monkeypatch, qapp, isolated_settings):
    from PyQt6.QtCore import QSize

    from pagedrop.ui import icons
    from pagedrop.ui.theme import TEXT_PRIMARY

    monkeypatch.setattr(icons, "_device_pixel_ratios", lambda: (1.0, 2.0))
    icons.refresh_icons()
    result = icons.icon("folder-open")

    assert QSize(32, 32) in result.availableSizes()
    one = result.pixmap(QSize(16, 16), 1.0)
    two = result.pixmap(QSize(16, 16), 2.0)
    assert (one.width(), one.height()) == (16, 16)
    assert (two.width(), two.height()) == (32, 32)
    assert two.devicePixelRatio() == 2.0
    # Rendered from the vector at 32 px, not a 16 px bitmap scaled up.
    rendered = two.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    assert rendered == _reference_render("folder-open", TEXT_PRIMARY, 32)
    icons.refresh_icons()


def test_icon_supports_fractional_device_pixel_ratio(monkeypatch, qapp, isolated_settings):
    from PyQt6.QtCore import QSize

    from pagedrop.ui import icons

    monkeypatch.setattr(icons, "_device_pixel_ratios", lambda: (1.0, 1.5))
    icons.refresh_icons()
    result = icons.icon("folder-open")
    for logical, pixels in ((16, 24), (20, 30), (24, 36), (32, 48)):
        pixmap = result.pixmap(QSize(logical, logical), 1.5)
        assert (pixmap.width(), pixmap.height()) == (pixels, pixels)
        assert pixmap.devicePixelRatio() == 1.5

    # Non-integer products round up so the pixmap always covers the logical size.
    odd = icons._render_pixmap(icons._load_svg("x").encode(), 16, 1.1)
    assert odd.width() == 18
    assert odd.devicePixelRatio() == 1.1
    icons.refresh_icons()


def test_icon_cache_is_keyed_by_ratios_and_tint(monkeypatch, qapp, isolated_settings):
    from PyQt6.QtCore import QSize

    from pagedrop.ui import icons

    icons.refresh_icons()
    monkeypatch.setattr(icons, "_device_pixel_ratios", lambda: (1.0,))
    low = icons.icon("x")
    assert icons.icon("x") is low
    assert icons.icon("x", color="#FF0000") is not low

    monkeypatch.setattr(icons, "_device_pixel_ratios", lambda: (1.0, 2.0))
    high = icons.icon("x")
    assert high is not low
    assert icons.icon("x") is high
    assert QSize(40, 40) in high.availableSizes()
    assert QSize(40, 40) not in low.availableSizes()

    icons.refresh_icons()
    assert icons._cache == {}


# --- Style sheet indicator images ------------------------------------------


def _image_urls(sheet: str) -> list[str]:
    import re

    return re.findall(r'image: url\("([^"]+)"\)', sheet)


def test_indicator_path_writes_one_and_two_x_files(qapp):
    from pathlib import Path

    from pagedrop.ui.icons import indicator_path

    path = Path(indicator_path("check-bold", color="#FFFFFF", size=12))
    retina = path.with_name("check-bold-12-ffffff@2x.png")
    assert path.name == "check-bold-12-ffffff.png"
    assert path.is_file() and retina.is_file()
    assert (QImage(str(path)).width(), QImage(str(retina)).width()) == (12, 24)
    # Same tint, same file; no new directory per call.
    assert Path(indicator_path("check-bold", color="#ffffff", size=12)) == path


def test_indicator_canvas_centres_the_mark(qapp):
    from pathlib import Path

    from pagedrop.ui.icons import indicator_path

    path = Path(indicator_path("circle-fill", color="#FF0000", size=8, canvas=16))
    image = QImage(str(path))
    assert image.width() == 16
    assert image.pixelColor(8, 8).alpha() == 255
    assert image.pixelColor(1, 1).alpha() == 0
    assert image.pixelColor(8, 3).alpha() == 0  # circle spans 4..12 only


def test_indicator_path_needs_no_gui_application():
    """The style sheet is built before (and without) any QGuiApplication."""
    import subprocess
    import sys

    code = (
        "from pagedrop.ui.theme import app_stylesheet\n"
        "sheet = app_stylesheet(light=True)\n"
        "print('image: url(' in sheet)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_light_dark_and_high_contrast_sheets_use_different_existing_images(qapp):
    from pathlib import Path

    from pagedrop.ui.theme import app_stylesheet

    sheets = {
        "dark": app_stylesheet(light=False),
        "light": app_stylesheet(light=True),
        "dark-hc": app_stylesheet(light=False, high_contrast=True),
        "light-hc": app_stylesheet(light=True, high_contrast=True),
    }
    urls = {name: set(_image_urls(sheet)) for name, sheet in sheets.items()}
    for name, found in urls.items():
        assert found, name
        for url in found:
            assert Path(url).is_file(), url
            assert Path(url.replace(".png", "@2x.png")).is_file(), url
    assert urls["dark"] != urls["light"]
    # High contrast restyles the arrows (muted text becomes full text).
    assert urls["dark"] != urls["dark-hc"]
    assert urls["light"] != urls["light-hc"]


def test_deleted_indicator_is_rendered_again(qapp):
    from pathlib import Path

    from pagedrop.ui.theme import app_stylesheet

    url = Path(_image_urls(app_stylesheet(light=True))[0])
    url.unlink()
    again = _image_urls(app_stylesheet(light=True))
    assert url.as_posix() in again
    assert url.is_file()
    url.with_name(url.stem + "@2x.png").unlink()
    app_stylesheet(light=True)
    assert url.with_name(url.stem + "@2x.png").is_file()


def test_failed_indicator_write_warns_and_the_sheet_still_builds(qapp, monkeypatch, tmp_path, caplog):
    import logging

    from pagedrop.ui import icons
    from pagedrop.ui.theme import app_stylesheet

    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x")
    monkeypatch.setattr(icons, "_indicator_dir", lambda: blocker / "inside")
    with caplog.at_level(logging.WARNING, logger="pagedrop"):
        sheet = app_stylesheet(light=True)
    assert "QCheckBox::indicator:checked" in sheet
    assert "QComboBox::down-arrow" in sheet
    assert _image_urls(sheet) == []
    assert any("indicator image" in r.message for r in caplog.records)


def test_theme_change_points_the_sheet_at_new_images(qapp, isolated_settings):
    from PyQt6.QtWidgets import QApplication

    from pagedrop.ui.accessibility import refresh_themed_widgets
    from pagedrop.ui.settings import set_light_theme

    app = QApplication.instance()
    previous = app.styleSheet()
    try:
        set_light_theme(False)
        refresh_themed_widgets()
        dark = set(_image_urls(app.styleSheet()))
        set_light_theme(True)
        refresh_themed_widgets()
        light = set(_image_urls(app.styleSheet()))
        assert dark and light and dark != light
    finally:
        set_light_theme(False)
        app.setStyleSheet(previous)


def test_removed_indicator_directory_is_recreated_with_images(qapp):
    import shutil
    from pathlib import Path

    from pagedrop.ui import icons
    from pagedrop.ui.theme import app_stylesheet

    app_stylesheet(light=True)
    old = icons._indicator_dir()
    shutil.rmtree(old)

    urls = _image_urls(app_stylesheet(light=True))
    assert urls
    for url in urls:
        assert Path(url).is_file()
        assert Path(url.replace(".png", "@2x.png")).is_file()
    fresh = icons._indicator_dir()
    assert fresh != old and fresh.is_dir()
    assert (fresh / ".pagedrop_owner").is_file()


def test_indicator_files_present_reports_a_loss_once(qapp):
    from pathlib import Path

    from pagedrop.ui import icons
    from pagedrop.ui.theme import app_stylesheet

    url = Path(_image_urls(app_stylesheet(light=True))[0])
    icons.indicator_files_present()  # forget files lost in earlier tests
    assert icons.indicator_files_present() is True

    url.unlink()
    assert icons.indicator_files_present() is False
    # The loss is forgotten, so an unused tint cannot report it again.
    assert icons.indicator_files_present() is True

    app_stylesheet(light=True)
    assert url.is_file()
    assert icons.indicator_files_present() is True
