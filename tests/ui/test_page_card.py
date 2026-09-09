"""Phase 4 unit tests — PageCard."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QApplication

from pagedrop.ui.accessibility import apply_app_stylesheet
from pagedrop.ui.page_card import PageCard
from pagedrop.ui.settings import set_light_theme
from pagedrop.ui.theme import app_stylesheet


def test_set_thumbnail(qtbot):
    card = PageCard(0)
    qtbot.addWidget(card)

    pixmap = QPixmap(80, 100)
    pixmap.fill(QColor("red"))
    card.set_thumbnail(pixmap)

    thumbnail_label = card._thumbnail_label
    shown = thumbnail_label.pixmap()
    assert shown is not None
    assert not shown.isNull()


def test_set_selected_styles(qtbot):
    card = PageCard(0)
    qtbot.addWidget(card)

    card.set_selected(False)
    assert card.property("selected") is False
    assert not card.styleSheet()

    card.set_selected(True)
    assert card.property("selected") is True
    assert card.property("focused") is False
    assert not card._selection_indicator.isHidden()
    assert "selected" in card.accessibleDescription().casefold()

    card.set_keyboard_focused(True)
    assert card.property("focused") is True
    assert not card._focus_ring.isHidden()

    sheet = app_stylesheet()
    assert 'QFrame#PageCard[selected="true"] QLabel#PageCardThumbnail' in sheet
    assert "QFrame#PageCard:hover" in sheet
    assert "QLabel#PageCardFocusRing" in sheet
    assert "QLabel#PageCardSelectionIndicator" in sheet


def test_thumbnail_frame_is_stable_for_mixed_page_shapes(qtbot):
    """Loading a landscape page must not move its caption or reflow the grid."""
    card = PageCard(0)
    qtbot.addWidget(card)
    card.set_card_width(176)
    final_height = card._thumbnail_label.height()

    landscape = QPixmap(200, 100)
    landscape.fill(QColor("red"))
    card.set_thumbnail(landscape)

    shown = card._thumbnail_label.pixmap()
    assert shown is not None
    assert card._thumbnail_label.height() == final_height
    assert shown.width() <= card._thumbnail_label.width()
    assert shown.height() <= final_height


def test_theme_toggle_keeps_property_based_card_chrome(qtbot, isolated_settings):
    """O3 residual: light/dark restyle must not push inline styles onto cards."""
    app = QApplication.instance()
    assert app is not None

    card = PageCard(0)
    qtbot.addWidget(card)
    card.set_selected(True)
    assert card.property("selected") is True
    assert not card.styleSheet()

    set_light_theme(True)
    apply_app_stylesheet(app)
    assert card.property("selected") is True
    assert not card.styleSheet()
    light = app.styleSheet()
    assert 'QFrame#PageCard[selected="true"]' in light
    assert "#F7F8FA" in light

    set_light_theme(False)
    apply_app_stylesheet(app)
    assert card.property("selected") is True
    assert not card.styleSheet()
    dark = app.styleSheet()
    assert 'QFrame#PageCard[selected="true"]' in dark
    assert "#131316" in dark


def test_page_card_accessible_name(qtbot):
    card = PageCard(2)
    qtbot.addWidget(card)
    assert card.accessibleName() == "Page 3"
    assert "select" in card.accessibleDescription().casefold()

    card.set_logical_index(0)
    assert card.accessibleName() == "Page 1"

    card.set_page_tooltip(210, 297)
    assert card.accessibleName() == "Page 1"
    assert "210×297" in card.accessibleDescription()
