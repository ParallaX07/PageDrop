"""Visual & platform accessibility — contrast, motion, focus, labels."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtWidgets import QToolButton

from pagedrop.ui.accessibility import contrast_ratio, prefers_reduce_motion
from pagedrop.ui.base_file_card import BaseFileCard
from pagedrop.ui.merge_file_card import MergeFileCard
from pagedrop.ui.preferences_dialog import PreferencesDialog
from pagedrop.ui.settings import reduce_motion, set_reduce_motion
from pagedrop.ui.theme import BG_BASE, TEXT_MUTED, app_stylesheet
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.ui.zoom_controls import ZoomControls


def test_text_muted_meets_wcag_aa_on_bg_base():
    assert contrast_ratio(TEXT_MUTED, BG_BASE) >= 4.5


def test_light_text_muted_meets_wcag_aa_on_bg_grid():
    # Keep in sync with app_stylesheet(light=True) text_muted_tok / bg_grid.
    light_muted = "#5A5D68"
    light_bg_grid = "#F0F1F4"
    assert contrast_ratio(light_muted, light_bg_grid) >= 4.5
    assert light_muted in app_stylesheet(light=True)


def test_high_contrast_stylesheet_strengthens_chrome():
    normal = app_stylesheet(high_contrast=False)
    high = app_stylesheet(high_contrast=True)
    assert "QToolBar QToolButton:focus" in normal
    assert "border: 2px solid" in normal
    assert "border: 3px solid" in high
    assert high != normal


def test_reduce_motion_setting_gates_shadow_hover(qtbot, isolated_settings):
    set_reduce_motion(True)
    assert reduce_motion() is True
    assert prefers_reduce_motion() is True

    card = MergeFileCard(0, "/tmp/a.pdf", 1)
    qtbot.addWidget(card)
    # Shadows are hover-only — resting cards carry no graphics effect.
    assert card._shadow is None

    pos = QPointF(8, 8)
    card.enterEvent(QEnterEvent(pos, pos, pos))
    # Reduce-motion: no shadow installed on hover either.
    assert card._shadow is None

    card.leaveEvent(None)
    set_reduce_motion(False)
    assert prefers_reduce_motion() is False
    card.enterEvent(QEnterEvent(pos, pos, pos))
    assert card._shadow is not None
    assert card._shadow.blurRadius() > 14
    card.leaveEvent(None)
    assert card._shadow is None


def test_preferences_reduce_motion_persists(qtbot, isolated_settings):
    assert reduce_motion() is False
    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    assert dialog._reduce_motion.isChecked() is False

    dialog._reduce_motion.setChecked(True)
    dialog._on_accept()
    assert reduce_motion() is True
    assert prefers_reduce_motion() is True

    dialog2 = PreferencesDialog()
    qtbot.addWidget(dialog2)
    assert dialog2._reduce_motion.isChecked() is True
    dialog2._reduce_motion.setChecked(False)
    dialog2._on_accept()
    assert reduce_motion() is False


def test_skeleton_pulse_skipped_when_reduce_motion(qtbot, isolated_settings):
    set_reduce_motion(True)
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid._skeleton_count = 1
    grid._start_skeleton_pulse()
    assert not grid._skeleton_pulse_timer.isActive()

    set_reduce_motion(False)
    grid._start_skeleton_pulse()
    assert grid._skeleton_pulse_timer.isActive()
    grid._stop_skeleton_pulse()


def test_stylesheet_includes_focus_rings_for_controls():
    sheet = app_stylesheet()
    assert "QToolBar QToolButton:focus" in sheet
    assert "QToolButton:checked" in sheet
    assert "QMenuBar::item:selected" in sheet
    # Menubar ::item:focus highlights every item under Qt — do not use it.
    assert "QMenuBar::item:focus" not in sheet
    assert "QMenu::item:selected" in sheet
    assert "QDialog {" in sheet
    assert "QListWidget," in sheet
    assert "QTreeWidget {" in sheet
    assert "QPushButton {" in sheet
    assert "QComboBox {" in sheet
    assert "QSpinBox {" in sheet
    assert "QCheckBox," in sheet
    assert "QLineEdit {" in sheet
    assert "QSlider#ZoomSlider:focus" in sheet
    assert "QPushButton#ZoomButton:focus" in sheet
    assert "QTabWidget#PdfViewerSide::pane" in sheet


def test_light_stylesheet_styles_dialogs(isolated_settings):
    light = app_stylesheet(light=True)
    assert "#F7F8FA" in light
    assert "QDialog {" in light
    assert "QListWidget::item:selected" in light
    assert "QTreeWidget::item:selected" in light
    assert "QTabWidget#PdfViewerSide::pane" in light
    # Viewer QToolButtons sit outside QToolBar — must still get light surfaces.
    assert "QToolButton," in light
    assert "background-color: #FFFFFF" in light
    assert "color: #1A1A1F" in light
    assert "QFrame#WatermarkOptionsCard" in light
    assert "QPushButton#ToolbarPrimary" in light


def test_theme_smoke_light_dark_and_high_contrast():
    """O8: tokens + objectName chrome present in dark, light, and HC sheets."""
    from pagedrop.ui.theme import (
        STATUS_SUCCESS,
        STATUS_WARNING,
        VIEWER_PAGE_BG,
        token_qcolor,
    )

    dark = app_stylesheet()
    light = app_stylesheet(light=True)
    high = app_stylesheet(high_contrast=True)

    for sheet in (dark, light, high):
        assert "QFrame#DropIndicator" in sheet
        assert "QLabel#ToolsErrorHint" in sheet
        assert "QLabel#ComparePaneTitle" in sheet
        assert "QLabel#CompareModeLabel" in sheet
        assert "QLabel#CompareSummary" in sheet
        assert VIEWER_PAGE_BG in sheet

    assert high != dark
    assert "border: 3px solid" in high
    assert STATUS_SUCCESS.startswith("#")
    assert STATUS_WARNING.startswith("#")
    assert token_qcolor(STATUS_SUCCESS, 90).alpha() == 90


def test_drop_indicator_uses_object_name_not_inline_stylesheet(qtbot):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    assert grid._drop_indicator.objectName() == "DropIndicator"
    # Theme stylesheet owns the accent fill so theme refresh stays coherent.
    assert not grid._drop_indicator.styleSheet()


def test_progress_and_empty_state_accessible_names(main_window, qtbot):
    assert main_window._progress_bar.accessibleName() == "Page rendering progress"

    grid = main_window._thumbnail_grid
    assert isinstance(grid, ThumbnailGrid)
    assert grid._empty_state.accessibleName()
    assert grid._empty_logo.accessibleName() == "PageDrop logo"

    new_tab = main_window._tab_manager.cornerWidget(Qt.Corner.TopRightCorner)
    assert isinstance(new_tab, QToolButton)
    assert new_tab.accessibleName() == "New tab"

    zoom = main_window._zoom_controls
    assert isinstance(zoom, ZoomControls)
    assert zoom.accessibleName() == "Thumbnail zoom"
    assert zoom._slider.accessibleName() == "Thumbnail size"
    assert zoom._zoom_out.accessibleName() == "Zoom out"
    assert zoom._zoom_in.accessibleName() == "Zoom in"


def test_base_file_card_is_not_imported_cycle():
    assert issubclass(MergeFileCard, BaseFileCard)
