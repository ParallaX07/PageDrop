"""User preferences + command palette (Phase E)."""

from __future__ import annotations

from PyQt6.QtGui import QKeySequence

from pagedrop.ui.accessibility import apply_app_stylesheet
from pagedrop.ui.command_palette import (
    action_label,
    collect_actions,
    fuzzy_match,
)
from pagedrop.ui.settings import (
    chrome_visible,
    light_theme,
    set_chrome_visible,
    set_light_theme,
    set_thumbnail_quality,
    set_thumbnail_zoom,
    thumbnail_quality,
    thumbnail_render_width,
    thumbnail_zoom,
)
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_THUMBNAIL_WIDTH,
    app_stylesheet,
)


def test_light_theme_stylesheet_differs(isolated_settings):
    dark = app_stylesheet(light=False)
    light = app_stylesheet(light=True)
    assert dark != light
    assert "#F7F8FA" in light
    assert "#131316" in dark


def test_light_theme_pref_round_trip(isolated_settings):
    assert light_theme() is False
    set_light_theme(True)
    assert light_theme() is True
    apply_app_stylesheet()


def test_chrome_visible_pref_round_trip(isolated_settings):
    assert chrome_visible() is True
    set_chrome_visible(False)
    assert chrome_visible() is False
    set_chrome_visible(True)
    assert chrome_visible() is True


def test_thumbnail_quality_caps_render_width(isolated_settings):
    set_thumbnail_quality("high")
    assert thumbnail_quality() == "high"
    assert thumbnail_render_width(480) == 480

    set_thumbnail_quality("medium")
    assert thumbnail_render_width(480) == 320
    assert thumbnail_render_width(200) == 200

    set_thumbnail_quality("low")
    assert thumbnail_render_width(400) == 160


def test_thumbnail_zoom_pref_round_trip(isolated_settings):
    assert thumbnail_zoom() == DEFAULT_THUMBNAIL_WIDTH
    set_thumbnail_zoom(240)
    assert thumbnail_zoom() == 240
    set_thumbnail_zoom(MAX_THUMBNAIL_WIDTH + 50)
    assert thumbnail_zoom() == MAX_THUMBNAIL_WIDTH


def test_fuzzy_match_substring_and_subsequence():
    assert fuzzy_match("", "Open PDF")
    assert fuzzy_match("open", "Open PDF")
    assert fuzzy_match("opdf", "Open PDF")
    assert not fuzzy_match("xyz", "Open PDF")


def test_command_palette_collects_menu_actions(main_window):
    actions = collect_actions(main_window)
    labels = {action_label(a) for a in actions}
    assert "Open PDF" in labels
    assert "Toggle light theme" in labels
    assert "Command palette…" in labels


def test_view_menu_theme_and_quality(isolated_settings, main_window, qtbot):
    # MainWindow may init before isolated_settings; force a known starting point.
    set_light_theme(False)
    main_window._light_theme_action.blockSignals(True)
    main_window._light_theme_action.setChecked(False)
    main_window._light_theme_action.blockSignals(False)

    main_window._light_theme_action.trigger()
    assert light_theme() is True
    assert main_window._light_theme_action.isChecked() is True

    low = next(
        a for a in main_window._quality_action_group.actions() if a.data() == "low"
    )
    low.trigger()
    assert thumbnail_quality() == "low"


def test_chrome_toggle_hides_menu_and_toolbar(isolated_settings, main_window, qtbot):
    set_chrome_visible(True)
    main_window._set_chrome_visible(True)

    assert not main_window.menuBar().isHidden()
    assert not main_window._toolbar.isHidden()
    assert main_window._chrome_visible_action.isChecked()
    assert main_window._chrome_toggle_btn.text() == "⌃"
    assert main_window._chrome_toggle_btn.toolTip() == "Hide menu and toolbar"

    main_window._chrome_toggle_btn.click()
    assert main_window.menuBar().isHidden()
    assert main_window._toolbar.isHidden()
    assert not main_window._chrome_visible_action.isChecked()
    assert chrome_visible() is False
    assert main_window._chrome_toggle_btn.text() == "⌄"
    assert main_window._chrome_toggle_btn.toolTip() == "Show menu and toolbar"

    main_window._chrome_visible_action.trigger()
    assert not main_window.menuBar().isHidden()
    assert not main_window._toolbar.isHidden()
    assert main_window._chrome_visible_action.isChecked()
    assert chrome_visible() is True


def test_zoom_persisted_on_change(main_window, five_page_pdf, isolated_settings, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)
    main_window._on_zoom_requested(200)
    assert thumbnail_zoom() == 200


def test_autofit_on_open_fills_columns(main_window, five_page_pdf, qtbot):
    main_window.showMinimized()
    qtbot.waitExposed(main_window)
    grid = main_window._thumbnail_grid
    expected = grid.fitted_thumbnail_width()
    main_window._load_pdf(str(five_page_pdf))
    assert grid.thumbnail_width_px == expected
    assert not grid.manual_zoom
    # Auto-fit must not clobber the remembered preference.
    assert thumbnail_zoom() == DEFAULT_THUMBNAIL_WIDTH


def test_autofit_skips_after_manual_zoom(main_window, five_page_pdf, qtbot):
    main_window.showMinimized()
    qtbot.waitExposed(main_window)
    main_window._on_zoom_requested(200)
    assert main_window._thumbnail_grid.manual_zoom
    main_window._load_pdf(str(five_page_pdf))
    assert main_window._thumbnail_grid.thumbnail_width_px == 200


def test_new_blank_tab_uses_saved_zoom(main_window, isolated_settings):
    set_thumbnail_zoom(200)
    main_window._new_blank_tab()
    tab = main_window._tab_manager.active_tab
    assert tab is not None
    assert tab.zoom_level == 200


def test_command_palette_shortcut_registered(main_window):
    assert main_window._command_palette_action.shortcut() == QKeySequence(
        "Ctrl+Shift+P"
    )
