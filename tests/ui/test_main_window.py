"""Phase 3 unit tests — MainWindow."""

from __future__ import annotations

from PyQt6.QtWidgets import QFileDialog, QToolBar

from pagedrop.ui.main_window import MainWindow


def _file_menu_actions(window: MainWindow):
    menubar = window.menuBar()
    for action in menubar.actions():
        if action.text().replace("&", "") == "File":
            return list(action.menu().actions())
    raise AssertionError("File menu not found")


def _find_action_by_text(actions, *candidates: str):
    normalized = {text.replace("&", "") for text in candidates}
    for action in actions:
        label = action.text().replace("&", "")
        if label in normalized:
            return action
    raise AssertionError(f"No action matching {candidates}")


def test_window_title_default(main_window):
    assert main_window.windowTitle() == "PageDrop"


def test_menu_actions_exist(main_window):
    actions = _file_menu_actions(main_window)
    labels = {action.text().replace("&", "") for action in actions if not action.isSeparator()}
    assert "Open PDF" in labels
    assert "Close tab" in labels
    assert "Exit" in labels


def test_high_traffic_actions_use_sentence_case(main_window):
    """Menus/toolbar follow project sentence-case (not Title Case)."""
    a = main_window._actions
    assert a["close_tab"].text().replace("&", "") == "Close tab"
    assert a["save_as"].text().replace("&", "") == "Save as"
    assert a["export_all"].text().replace("&", "") == "Export all pages…"
    assert a["new_window"].text().replace("&", "") == "New window"
    assert a["light_theme"].text().replace("&", "") == "Toggle light theme"
    assert a["chrome_visible"].text().replace("&", "") == "Show menu and toolbar"
    assert a["keyboard_shortcuts"].text().replace("&", "") == "Keyboard shortcuts"
    assert a["tips"].text().replace("&", "") == "Show tips"
    assert a["move_up"].text() == "Move up"
    assert a["select_all"].text() == "Select all"
    assert main_window._open_recent_menu.title().replace("&", "") == "Open recent"


def test_toolbar_open_button(main_window):
    open_action = None
    for toolbar in main_window.findChildren(QToolBar):
        for action in toolbar.actions():
            if action.text().replace("&", "") == "Open PDF":
                open_action = action
                break
    assert open_action is not None
    assert open_action is main_window._actions["open"]
    assert open_action.isEnabled()


def test_open_pdf_updates_title(main_window, five_page_pdf, monkeypatch, qtbot):
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(five_page_pdf)], "PDF Files (*.pdf)"),
    )
    monkeypatch.setattr(main_window, "_ask_open_target", lambda path: "current")
    main_window._open_pdf()
    qtbot.waitUntil(
        lambda: main_window.windowTitle()
        == f"PageDrop — {five_page_pdf.name} (5 pages)",
        timeout=5000,
    )


def test_status_bar_shows_page_count(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(
        lambda: "Loaded" in main_window.statusBar().currentMessage(),
        timeout=15000,
    )
    message = main_window.statusBar().currentMessage()
    assert "5" in message


def test_progress_bar_visible_during_preparing(
    main_window, five_page_pdf, monkeypatch, qtbot
):
    import pagedrop.ui.thumbnail_grid as tg

    monkeypatch.setattr(tg, "LARGE_PDF_PAGE_THRESHOLD", 2)
    monkeypatch.setattr(tg, "CARD_CREATE_BATCH", 2)

    grid = main_window._thumbnail_grid
    shown_during_prep: list[bool] = []

    def _on_progress(current: int, total: int) -> None:
        if "loading" in grid._busy_reasons:
            # isHidden() is the local flag; isVisible() needs a shown window.
            shown_during_prep.append(not main_window._progress_bar.isHidden())

    grid.rendering_progress.connect(_on_progress)
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: len(grid._cards) == 5, timeout=10000)
    assert shown_during_prep
    assert any(shown_during_prep)


def test_window_title_uses_logical_count_after_delete(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(
        lambda: "5 pages" in main_window.windowTitle(),
        timeout=15000,
    )
    grid = main_window._thumbnail_grid
    grid.selection_manager.select_single(0)
    grid.selection_manager.toggle(1)
    main_window._delete_selected_pages()
    assert "3 pages" in main_window.windowTitle()
    assert main_window._active_tab().edit_model.logical_count() == 3


def test_exit_action_closes(main_window, qtbot):
    main_window.show()
    exit_action = _find_action_by_text(_file_menu_actions(main_window), "E&xit", "Exit")
    exit_action.trigger()
    qtbot.waitUntil(lambda: not main_window.isVisible(), timeout=5000)
