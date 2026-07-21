"""Visual & platform accessibility — contrast, motion, focus, labels."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtWidgets import QToolButton

from pagedrop.ui.accessibility import contrast_ratio, prefers_reduce_motion
from pagedrop.ui.base_file_card import BaseFileCard
from pagedrop.ui.merge_file_card import MergeFileCard
from pagedrop.ui.settings import reduce_motion, set_reduce_motion
from pagedrop.ui.theme import BG_BASE, TEXT_MUTED, app_stylesheet
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.ui.zoom_controls import ZoomControls


def test_text_muted_meets_wcag_aa_on_bg_base():
    assert contrast_ratio(TEXT_MUTED, BG_BASE) >= 4.5


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
    resting_blur = card._shadow.blurRadius()

    pos = QPointF(8, 8)
    card.enterEvent(QEnterEvent(pos, pos, pos))
    assert card._hovered is True
    assert card._shadow.blurRadius() == resting_blur

    card.leaveEvent(None)
    set_reduce_motion(False)
    assert prefers_reduce_motion() is False
    card.enterEvent(QEnterEvent(pos, pos, pos))
    assert card._shadow.blurRadius() > resting_blur


def test_stylesheet_includes_focus_rings_for_controls():
    sheet = app_stylesheet()
    assert "QToolBar QToolButton:focus" in sheet
    assert "QMenuBar::item:focus" in sheet
    assert "QMenu::item:focus" in sheet
    assert "QSlider#ZoomSlider:focus" in sheet
    assert "QPushButton#ZoomButton:focus" in sheet


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
