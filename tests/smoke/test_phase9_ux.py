"""Phase 9 smoke tests — UX polish regression checks."""

from __future__ import annotations


from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.theme import DEFAULT_THUMBNAIL_WIDTH
from tests.conftest import wait_for_grid_loaded, wait_for_pdf_loaded


def test_smoke_window_title_includes_page_count(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)

    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window, timeout=15000)

    expected = f"PageDrop: {five_page_pdf.name} (5 pages)"
    assert window.windowTitle() == expected

    window.close()


def test_smoke_toolbar_buttons_enabled_states(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)

    preview = window._actions["preview"]
    select_all = window._actions["select_all"]
    deselect_all = window._actions["deselect_all"]

    assert not preview.isEnabled()
    assert not select_all.isEnabled()
    assert not deselect_all.isEnabled()

    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window, timeout=15000)

    assert preview.isEnabled()
    assert select_all.isEnabled()
    assert not deselect_all.isEnabled()

    select_all.trigger()
    assert deselect_all.isEnabled()
    assert len(window._thumbnail_grid.selection_manager.selection) == 5

    window.close()


def test_smoke_card_visual_states_differ(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window, timeout=15000)

    card = window._thumbnail_grid._cards[0]
    card.set_selected(False)
    card.set_keyboard_focused(False)
    assert card.property("selected") is False
    assert card.property("focused") is False
    assert not card.styleSheet()

    card.set_selected(True)
    assert card.property("selected") is True

    card.set_selected(False)
    card.set_keyboard_focused(True)
    assert card.property("focused") is True
    assert card.property("selected") is False

    from pagedrop.ui.theme import app_stylesheet

    sheet = app_stylesheet()
    assert 'QFrame#PageCard[selected="true"]' in sheet
    assert "QFrame#PageCard:hover" in sheet

    window.close()


def test_smoke_zoom_autofit_after_load(qtbot, five_page_pdf, isolated_settings):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    qtbot.waitExposed(window)
    grid = window._thumbnail_grid
    window._load_pdf(str(five_page_pdf))
    # Fitted to the viewport the grid ends up with, not the one it had at load.
    qtbot.waitUntil(
        lambda: grid.thumbnail_width_px == grid.fitted_thumbnail_width()
        and grid.thumbnail_width_px != DEFAULT_THUMBNAIL_WIDTH,
        timeout=5000,
    )
    wait_for_grid_loaded(qtbot, grid, timeout=15000)

    assert grid.thumbnail_width_px == grid.fitted_thumbnail_width()
    assert not grid.manual_zoom
    assert grid._cards[0].width() == grid.card_width
    assert grid.card_width <= grid.viewport().width()

    window.close()
