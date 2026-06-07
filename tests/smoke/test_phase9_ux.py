"""Phase 9 smoke tests — UX polish regression checks."""

from __future__ import annotations

from PyQt6.QtWidgets import QToolBar

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.theme import DEFAULT_THUMBNAIL_WIDTH


def _toolbar_action(window: MainWindow, label: str):
    for toolbar in window.findChildren(QToolBar):
        for action in toolbar.actions():
            if action.text() == label:
                return action
    raise AssertionError(f"Toolbar action {label!r} not found")


def test_smoke_window_title_includes_page_count(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)

    window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(window._thumbnail_grid.rendering_finished, timeout=15000)

    expected = f"PageDrop — {five_page_pdf.name} (5 pages)"
    assert window.windowTitle() == expected

    window.close()


def test_smoke_toolbar_buttons_enabled_states(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)

    preview = _toolbar_action(window, "Preview")
    select_all = _toolbar_action(window, "Select All")
    deselect_all = _toolbar_action(window, "Deselect All")

    assert not preview.isEnabled()
    assert not select_all.isEnabled()
    assert not deselect_all.isEnabled()

    window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(window._thumbnail_grid.rendering_finished, timeout=15000)

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
    qtbot.waitSignal(window._thumbnail_grid.rendering_finished, timeout=15000)

    card = window._thumbnail_grid._cards[0]
    card.set_selected(False)
    card.set_keyboard_focused(False)
    default_style = card.styleSheet()

    card.set_selected(True)
    selected_style = card.styleSheet()
    assert default_style != selected_style
    assert "3px" in selected_style

    card.set_selected(False)
    card.set_keyboard_focused(True)
    focused_style = card.styleSheet()
    assert focused_style != default_style

    card.set_selected(False)
    card.set_keyboard_focused(False)
    card._hovered = True
    card._apply_visual_state()
    hover_style = card.styleSheet()
    assert hover_style != default_style

    window.close()


def test_smoke_zoom_default_after_load(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(window._thumbnail_grid.rendering_finished, timeout=15000)

    assert window._thumbnail_grid.thumbnail_width_px == DEFAULT_THUMBNAIL_WIDTH
    assert window._thumbnail_grid._cards[0].width() == window._thumbnail_grid.card_width

    window.close()
