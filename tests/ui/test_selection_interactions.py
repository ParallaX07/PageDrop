"""Phase 5 UI tests — page selection interactions."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QMenu, QPushButton

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from tests.conftest import wait_for_grid_loaded, wait_for_pdf_loaded


def _load_grid(qtbot, pdf_path) -> ThumbnailGrid:
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(900, 650)
    loader = PdfLoader(str(pdf_path))
    grid.load_pdf(loader)
    wait_for_grid_loaded(qtbot, grid)
    loader.close()
    return grid


def _selected_indices(cards) -> set[int]:
    return {card.page_index for card in cards if card.is_selected}


def test_click_selects_single(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards

    qtbot.mouseClick(cards[0], Qt.MouseButton.LeftButton)
    assert _selected_indices(cards) == {0}

    qtbot.mouseClick(cards[2], Qt.MouseButton.LeftButton)
    assert _selected_indices(cards) == {2}
    assert not cards[0].is_selected


def test_ctrl_click_toggles(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards

    qtbot.mouseClick(
        cards[0],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    qtbot.mouseClick(
        cards[2],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    qtbot.mouseClick(
        cards[4],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    assert _selected_indices(cards) == {0, 2, 4}
    assert all(cards[index].is_selected for index in (0, 2, 4))


def _ctrl_click(qtbot, card):
    qtbot.mouseClick(
        card,
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )


def _ranks(cards) -> dict[int, int]:
    return {
        card.page_index: card.selection_rank
        for card in cards
        if card.selection_rank is not None
    }


def _shown_numbers(cards) -> dict[int, int]:
    """Numbers the chips actually show, by page index."""
    return {
        card.page_index: card._order_chip._rank
        for card in cards
        if not card._order_chip.isHidden()
    }


def test_ctrl_click_in_reverse_numbers_pages_by_page_order(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards

    for index in (4, 2, 0):
        _ctrl_click(qtbot, cards[index])

    assert grid.selection_manager.selection == {0, 2, 4}
    assert _ranks(cards) == {0: 1, 2: 2, 4: 3}
    assert _shown_numbers(cards) == {0: 1, 2: 2, 4: 3}
    assert "number 2" in cards[2].accessibleDescription()


def test_selecting_an_earlier_page_renumbers_later_ones(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards

    _ctrl_click(qtbot, cards[3])
    _ctrl_click(qtbot, cards[4])
    assert _ranks(cards) == {3: 1, 4: 2}

    _ctrl_click(qtbot, cards[1])
    assert _ranks(cards) == {1: 1, 3: 2, 4: 3}
    assert _shown_numbers(cards) == {1: 1, 3: 2, 4: 3}

    # Dropping one from the middle closes the gap; deselected cards clear.
    _ctrl_click(qtbot, cards[3])
    assert _ranks(cards) == {1: 1, 4: 2}
    assert cards[3].selection_rank is None
    assert cards[3]._order_chip.isHidden()


def test_unchanged_ranks_are_not_pushed_again(qtbot, five_page_pdf, monkeypatch):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards
    _ctrl_click(qtbot, cards[0])
    _ctrl_click(qtbot, cards[1])

    pushed: list[int] = []
    for card in cards:
        original = card.set_selection_rank

        def spy(rank, _card=card, _original=original):
            pushed.append(_card.page_index)
            _original(rank)

        monkeypatch.setattr(card, "set_selection_rank", spy)

    _ctrl_click(qtbot, cards[4])  # joins at the end: nothing else renumbers
    assert pushed == [4]
    pushed.clear()
    _ctrl_click(qtbot, cards[4])  # leaves the end: nobody else renumbers
    assert pushed == []
    _ctrl_click(qtbot, cards[0])  # leaves the front: page 2 becomes number 1
    assert pushed == [1]
    assert _ranks(cards) == {1: 1}


def test_ranks_after_select_all_delete_and_reorder(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards

    grid.selection_manager.select_all()
    assert _ranks(cards) == {i: i + 1 for i in range(5)}

    grid.selection_manager.set_selection({1, 3})
    assert grid.delete_selected_pages()
    cards = grid._cards
    assert len(cards) == 3
    assert grid.selection_manager.selection == set()
    assert _ranks(cards) == {}
    assert all(card._order_chip.isHidden() for card in cards)

    grid.selection_manager.select_all()
    assert _ranks(grid._cards) == {0: 1, 1: 2, 2: 3}

    grid.selection_manager.clear()
    grid.selection_manager.set_selection({0, 2})
    assert grid.reorder_pages_by_drop([0, 2], 1)
    cards = grid._cards
    selection = grid.selection_manager.selection
    assert len(selection) == 2
    assert _ranks(cards) == {
        index: rank for rank, index in enumerate(sorted(selection), start=1)
    }
    assert _shown_numbers(cards) == _ranks(cards)


def test_selection_manager_stays_an_unordered_set(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards
    for index in (3, 0, 2):
        _ctrl_click(qtbot, cards[index])

    selection = grid.selection_manager.selection
    assert selection == {0, 2, 3}
    assert type(selection) is set
    public = {name for name in dir(grid.selection_manager) if not name.startswith("_")}
    assert not {name for name in public if "order" in name or "rank" in name}


def test_shift_click_selects_range(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)
    cards = grid._cards

    qtbot.mouseClick(cards[1], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(
        cards[3],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ShiftModifier,
    )
    assert _selected_indices(cards) == {1, 2, 3}


def test_ctrl_a_selects_all(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)
    assert window._page_jump_action.text() == "Select pages"
    assert window._page_jump_action.shortcut().isEmpty()

    qtbot.keyClick(
        window,
        Qt.Key.Key_A,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    assert _selected_indices(window._thumbnail_grid._cards) == {0, 1, 2, 3, 4}
    window.close()


def test_escape_clears_selection(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    qtbot.mouseClick(
        window._thumbnail_grid._cards[0],
        Qt.MouseButton.LeftButton,
    )
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert _selected_indices(window._thumbnail_grid._cards) == set()
    window.close()


def test_selection_label_matches_selection(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    cards = window._thumbnail_grid._cards
    qtbot.mouseClick(cards[0], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._selection_toolbar_label.text() == "Page 1 selected",
        timeout=1000,
    )

    qtbot.mouseClick(
        cards[2],
        Qt.MouseButton.LeftButton,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    qtbot.waitUntil(
        lambda: window._selection_toolbar_label.text() == "2 pages selected",
        timeout=1000,
    )

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    qtbot.waitUntil(
        lambda: window._selection_toolbar_label.text() == "No selection",
        timeout=1000,
    )
    window.close()


def test_selection_toolbar_coalesces_storm(qtbot, five_page_pdf) -> None:
    """Rapid selection emits in one turn → one toolbar flush for the final set."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    updates: list[set[int]] = []
    real_sync = window._sync_contextual_toolbar

    def tracking_sync(selection: set[int]) -> None:
        updates.append(set(selection))
        real_sync(selection)

    window._sync_contextual_toolbar = tracking_sync  # type: ignore[method-assign]
    updates.clear()

    grid = window._thumbnail_grid
    # Simulate a selection storm in one turn (timer already armed after first).
    grid.selection_manager.select_single(0)
    assert updates == [{0}]
    assert window._selection_coalesce_timer.isActive()
    grid.selection_manager.select_range(0, 2)
    grid.selection_manager.select_range(0, 4)
    # Coalesced — no extra status update until the 0ms timer fires.
    assert updates == [{0}]
    qtbot.waitUntil(lambda: not window._selection_coalesce_timer.isActive(), timeout=1000)
    assert updates == [{0}, {0, 1, 2, 3, 4}]
    assert window._selection_toolbar_label.text() == "Pages 1–5 selected"
    assert window._deselect_all_action.isEnabled()
    window.close()


def test_selection_context_is_compact_and_accessible(qtbot, five_page_pdf) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    grid = window._thumbnail_grid
    grid.selection_manager.set_selection({2, 3, 4})
    qtbot.waitUntil(
        lambda: window._selection_toolbar_label.text() == "Pages 3–5 selected"
    )

    grid.selection_manager.set_selection({0, 2, 3})
    qtbot.waitUntil(
        lambda: window._selection_toolbar_label.text() == "3 pages selected"
    )
    expected = "3 pages selected: Pages 1, 3–4"
    assert window._selection_toolbar_label.toolTip() == expected
    assert window._selection_toolbar_label.accessibleName() == expected
    window.close()


def test_context_menu_projects_registered_page_actions(
    qtbot, five_page_pdf, monkeypatch
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)
    grid = window._thumbnail_grid
    assert window._toolbar.widgetForAction(window._select_all_action) is None
    assert window._toolbar.widgetForAction(window._deselect_all_action) is None
    command_buttons = [
        window._toolbar.widgetForAction(action)
        for action in (
            window._rotate_cw_action,
            window._duplicate_pages_action,
            window._extract_selected_action,
            window._delete_pages_action,
        )
    ]
    assert all(button is not None for button in command_buttons)
    stable_positions = [button.pos() for button in command_buttons]

    captured: list[QMenu] = []

    def capture(menu: QMenu, _position: QPoint):
        captured.append(menu)
        return None

    monkeypatch.setattr(QMenu, "exec", capture)
    grid._show_context_menu(QPoint())
    assert [
        action for action in captured[0].actions() if not action.isSeparator()
    ] == [
        window._select_all_action,
        window._deselect_all_action,
        window._move_up_action,
        window._move_down_action,
        window._move_to_action,
        window._duplicate_pages_action,
        window._rotate_cw_action,
        window._rotate_ccw_action,
        window._delete_pages_action,
        window._page_jump_action,
        window._extract_selected_action,
        window._extract_selected_to_tab_action,
        window._extract_selected_to_window_action,
    ]
    assert [a.text() for a in captured[0].actions()[:2]] == [
        "Select all",
        "Clear selection",
    ]
    grid.selection_manager.select_single(0)
    qtbot.waitUntil(lambda: window._deselect_all_action.isEnabled())
    assert [button.pos() for button in command_buttons] == stable_positions
    assert window._deselect_all_action.text() == "Clear selection"
    window.close()


def test_select_pages_dialog_validates_and_applies_logical_selection(
    qtbot, five_page_pdf, monkeypatch
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)

    def fill_and_accept(dialog: QDialog) -> int:
        page_input = dialog.findChild(QLineEdit, "SelectPagesInput")
        error = dialog.findChild(QLabel, "SelectPagesError")
        select = dialog.findChild(QPushButton, "SelectPagesConfirm")
        assert page_input is not None and error is not None and select is not None
        page_input.setText("bad input")
        assert "1 to 5" in error.text()
        assert not select.isEnabled()
        page_input.setText("4,1-2,2")
        assert select.isEnabled()
        select.click()
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", fill_and_accept)
    window._page_range_jump_dialog()

    assert window._thumbnail_grid.selection_manager.selection == {0, 1, 3}
    assert window._thumbnail_grid.focused_index == 0
    window.close()
