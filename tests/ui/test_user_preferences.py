"""User preferences + command palette (Phase E)."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QCheckBox, QDialogButtonBox, QScrollArea, QWidget

from pagedrop.ui.accessibility import apply_app_stylesheet
from pagedrop.ui.command_palette import (
    action_label,
    collect_actions,
    fuzzy_match,
)
from pagedrop.ui.preferences_dialog import PreferencesDialog, open_preferences
from pagedrop.ui import settings as settings_mod
from pagedrop.ui.settings import (
    KEY_CONFIRM_CLOSE_DIRTY,
    KEY_CONFIRM_DELETE_MULTIPLE,
    KEY_REMEMBER_GEOMETRY,
    KEY_VIEWER_PANEL_STATE,
    chrome_visible,
    confirm_before_closing_dirty_tabs,
    confirm_before_deleting_multiple_pages,
    light_theme,
    remember_window_geometry,
    set_chrome_visible,
    set_confirm_before_closing_dirty_tabs,
    set_confirm_before_deleting_multiple_pages,
    set_light_theme,
    set_remember_window_geometry,
    set_thumbnail_quality,
    set_thumbnail_zoom,
    set_viewer_panel_collapsed,
    thumbnail_quality,
    thumbnail_render_width,
    thumbnail_zoom,
    viewer_panel_collapsed,
)
from datetime import UTC, datetime
from pagedrop.ui.theme import (
    DEFAULT_THUMBNAIL_WIDTH,
    DARK,
    LIGHT,
    MAX_THUMBNAIL_WIDTH,
    app_stylesheet,
)
from tests.conftest import wait_for_pdf_loaded


def test_light_theme_stylesheet_differs(isolated_settings):
    dark = app_stylesheet(light=False)
    light = app_stylesheet(light=True)
    assert dark != light
    assert LIGHT.chrome in light
    assert DARK.chrome in dark


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


def test_viewer_panel_preference_round_trip(isolated_settings):
    assert viewer_panel_collapsed("navigation") is False
    assert viewer_panel_collapsed("markup") is True
    set_viewer_panel_collapsed("navigation", True)
    set_viewer_panel_collapsed("markup", False)
    assert viewer_panel_collapsed("navigation") is True
    assert viewer_panel_collapsed("markup") is False
    assert settings_mod._settings().value(KEY_VIEWER_PANEL_STATE, type=int) == 1


def test_update_preferences_use_strict_utc_timestamps(isolated_settings):
    moment = datetime(2026, 9, 8, 1, 2, 3, 999, tzinfo=UTC)
    settings_mod.set_automatic_update_checks_enabled(False)
    settings_mod.set_last_check_attempt_utc(moment)
    settings_mod.set_last_successful_check_utc(moment)
    settings_mod.set_update_retry_after_utc(moment)
    settings_mod.set_update_remind_after_utc(moment)
    settings_mod.set_skipped_update_version("1.2.3")
    settings_mod.set_pending_update_target_version("1.2.4")

    store = settings_mod._settings()
    assert settings_mod.automatic_update_checks_enabled() is False
    assert store.value(settings_mod.KEY_UPDATES_LAST_CHECK_ATTEMPT_UTC) == "2026-09-08T01:02:03Z"
    assert settings_mod.last_successful_check_utc() == moment.replace(microsecond=0)
    assert settings_mod.update_retry_after_utc() == moment.replace(microsecond=0)
    assert settings_mod.update_remind_after_utc() == moment.replace(microsecond=0)
    assert settings_mod.skipped_update_version() == "1.2.3"
    assert settings_mod.pending_update_target_version() == "1.2.4"
    store.setValue(settings_mod.KEY_UPDATES_LAST_SUCCESSFUL_CHECK_UTC, "not-a-timestamp")
    assert settings_mod.last_successful_check_utc() is None


def test_preferences_exposes_automatic_update_checks(qtbot, isolated_settings):
    dialog = PreferencesDialog()
    checkbox = dialog.findChild(QCheckBox, "PreferencesAutomaticUpdates")
    assert checkbox is not None
    assert checkbox.toolTip() == "Checks once a day while PageDrop is open."
    checkbox.setChecked(False)
    dialog._on_accept()
    assert settings_mod.automatic_update_checks_enabled() is False


def _fake_soffice(tmp_path, name="soffice"):
    path = tmp_path / name
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return str(path)


def _registry_matches_saved(caps) -> bool:
    return (
        caps.configured_soffice_path() == (settings_mod.office_soffice_path() or None)
        and caps.configured_office_backend() == settings_mod.office_preferred_backend()
        and caps.configured_tessdata_path() == (settings_mod.tessdata_path() or None)
    )


def _type_unsaved_values(dialog, tmp_path):
    soffice = _fake_soffice(tmp_path)
    tess = str(tmp_path / "tess")
    dialog._soffice.setText(soffice)
    dialog._backend.setCurrentIndex(dialog._backend.findData("libreoffice"))
    dialog._tessdata.setText(tess)
    return soffice, tess


def test_recheck_then_cancel_keeps_saved_values_and_registry(
    qtbot, capability_registry, tmp_path
):
    settings_mod.set_office_soffice_path("/saved/soffice")
    settings_mod.set_office_preferred_backend("com")
    settings_mod.set_tessdata_path("/saved/tess")
    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    soffice, tess = _type_unsaved_values(dialog, tmp_path)

    dialog._on_recheck()
    assert capability_registry.configured_soffice_path() == soffice

    dialog.reject()

    assert settings_mod.office_soffice_path() == "/saved/soffice"
    assert settings_mod.office_preferred_backend() == "com"
    assert settings_mod.tessdata_path() == "/saved/tess"
    assert _registry_matches_saved(capability_registry)


def test_closing_preferences_window_restores_registry(
    qtbot, capability_registry, tmp_path
):
    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    soffice, _ = _type_unsaved_values(dialog, tmp_path)
    dialog._on_recheck()
    assert capability_registry.configured_soffice_path() == soffice

    dialog.close()

    assert settings_mod.office_soffice_path() == ""
    assert _registry_matches_saved(capability_registry)
    assert capability_registry.configured_soffice_path() is None


def test_recheck_probes_unsaved_values_and_shows_them(
    qtbot, capability_registry, tmp_path, monkeypatch
):
    settings_mod.set_office_soffice_path("/saved/soffice")
    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    soffice, tess = _type_unsaved_values(dialog, tmp_path)
    seen: list[tuple] = []

    def fake_probe_all(*, refresh=False):
        seen.append(
            (
                capability_registry.configured_soffice_path(),
                capability_registry.configured_office_backend(),
                capability_registry.configured_tessdata_path(),
            )
        )
        return {}

    monkeypatch.setattr("pagedrop.ui.preferences_dialog.probe_all", fake_probe_all)

    dialog._on_recheck()

    assert seen == [(soffice, "libreoffice", tess)]
    assert soffice in dialog._backend_detail.text()
    assert "/saved/soffice" not in dialog._backend_detail.text()
    assert settings_mod.office_soffice_path() == "/saved/soffice"


def test_recheck_then_ok_saves_typed_values(qtbot, capability_registry, tmp_path):
    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    soffice, tess = _type_unsaved_values(dialog, tmp_path)

    dialog._on_recheck()
    assert settings_mod.office_soffice_path() == ""
    dialog._on_accept()

    assert settings_mod.office_soffice_path() == soffice
    assert settings_mod.office_preferred_backend() == "libreoffice"
    assert settings_mod.tessdata_path() == tess
    assert _registry_matches_saved(capability_registry)


def test_last_successful_check_is_shown_in_local_time(qtbot, isolated_settings):
    import os
    import time

    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available")
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Tokyo"
    time.tzset()
    try:
        settings_mod.set_last_successful_check_utc(
            datetime(2026, 9, 8, 15, 30, tzinfo=UTC)
        )
        dialog = PreferencesDialog()
        qtbot.addWidget(dialog)
        text = dialog._update_status.text()
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()

    assert "2026-09-09 00:30" in text
    assert "UTC" not in text


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
    assert "Preferences…" in labels
    assert "Check for updates…" in labels
    # Safety / geometry toggles live in Preferences only (no Edit-menu duplicates).
    assert "Confirm before deleting multiple pages" not in labels
    assert "Confirm before closing dirty tabs" not in labels
    assert "Remember window size and position" not in labels


def test_preferences_safety_geometry_persist_same_keys(qtbot, isolated_settings):
    """UI move keeps QSettings keys; existing values load into Preferences."""
    set_confirm_before_deleting_multiple_pages(False)
    set_confirm_before_closing_dirty_tabs(False)
    set_remember_window_geometry(False)

    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    margins = dialog.layout().contentsMargins()
    assert margins.left() >= 12
    assert margins.top() >= 12
    assert margins.right() >= 12
    assert margins.bottom() >= 12
    assert dialog._confirm_delete.isChecked() is False
    assert dialog._confirm_close_dirty.isChecked() is False
    assert dialog._remember_geometry.isChecked() is False

    dialog._confirm_delete.setChecked(True)
    dialog._confirm_close_dirty.setChecked(True)
    dialog._remember_geometry.setChecked(True)
    dialog._on_accept()

    assert confirm_before_deleting_multiple_pages() is True
    assert confirm_before_closing_dirty_tabs() is True
    assert remember_window_geometry() is True

    store = settings_mod._settings()
    assert store.value(KEY_CONFIRM_DELETE_MULTIPLE, type=bool) is True
    assert store.value(KEY_CONFIRM_CLOSE_DIRTY, type=bool) is True
    assert store.value(KEY_REMEMBER_GEOMETRY, type=bool) is True

    dialog2 = PreferencesDialog()
    qtbot.addWidget(dialog2)
    assert dialog2._confirm_delete.isChecked() is True
    assert dialog2._confirm_close_dirty.isChecked() is True
    assert dialog2._remember_geometry.isChecked() is True


def test_preferences_scrolls_content_with_a_persistent_footer(qtbot, isolated_settings):
    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    scroll = dialog.findChild(QScrollArea, "PreferencesScroll")
    footer = dialog.findChild(QDialogButtonBox)
    assert scroll is not None
    assert footer is not None
    assert dialog.layout().indexOf(footer) > dialog.layout().indexOf(scroll)
    assert "dirty tabs" not in dialog._confirm_close_dirty.text().lower()
    assert dialog._download_eng_btn.text() == "Download English language data…"
    assert dialog._soffice.placeholderText() == "Find automatically"
    assert dialog._advanced.isHidden()
    dialog._advanced_button.click()
    assert dialog._advanced.isVisible()


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
    wait_for_pdf_loaded(qtbot, main_window, timeout=15000)
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


def test_open_preferences_releases_dialog_and_coordinator_connections(
    qtbot, isolated_settings, monkeypatch
):
    class Coordinator(QObject):
        check_failed = pyqtSignal()
        check_succeeded = pyqtSignal()
        last_error = ""

    coordinator = Coordinator()
    parent = QWidget()
    qtbot.addWidget(parent)
    connected_during_exec: list[int] = []

    def fake_exec(self) -> int:
        connected_during_exec.append(coordinator.receivers(coordinator.check_failed))
        return 0

    monkeypatch.setattr(PreferencesDialog, "exec", fake_exec)

    for _ in range(3):
        dialog = open_preferences(parent, coordinator=coordinator)
        assert connected_during_exec[-1] > 0
        assert dialog.windowTitle() == "Preferences"  # still readable after exec
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert parent.findChildren(PreferencesDialog) == []
    assert coordinator.receivers(coordinator.check_failed) == 0
    assert coordinator.receivers(coordinator.check_succeeded) == 0


def _stub_color_scheme(monkeypatch, scheme):
    from PyQt6.QtGui import QGuiApplication

    class Hints:
        @staticmethod
        def colorScheme():  # noqa: N802
            return scheme

    monkeypatch.setattr(QGuiApplication, "styleHints", staticmethod(lambda: Hints))


@pytest.mark.parametrize(
    ("scheme", "expected"),
    [
        (Qt.ColorScheme.Light, True),
        (Qt.ColorScheme.Dark, False),
        (Qt.ColorScheme.Unknown, False),
    ],
)
def test_light_theme_follows_the_os_scheme_until_chosen(
    qtbot, isolated_settings, monkeypatch, scheme, expected
):
    _stub_color_scheme(monkeypatch, scheme)
    assert light_theme() is expected
    # Reading never stores a choice.
    assert not settings_mod._settings().contains(settings_mod.KEY_LIGHT_THEME)


def test_explicit_light_theme_choice_beats_the_os_scheme(
    qtbot, isolated_settings, monkeypatch
):
    _stub_color_scheme(monkeypatch, Qt.ColorScheme.Light)
    set_light_theme(False)
    assert light_theme() is False
    _stub_color_scheme(monkeypatch, Qt.ColorScheme.Dark)
    set_light_theme(True)
    assert light_theme() is True


def test_light_theme_menu_action_starts_in_step_with_the_os_scheme(
    qtbot, isolated_settings, monkeypatch
):
    from pagedrop.ui.main_window import MainWindow

    _stub_color_scheme(monkeypatch, Qt.ColorScheme.Light)
    window = MainWindow()
    qtbot.addWidget(window)
    try:
        assert window._light_theme_action.isChecked()
    finally:
        window._temp_manager.cleanup()
