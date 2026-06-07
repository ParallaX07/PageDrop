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
    assert "Open PDF..." in labels
    assert "Close PDF" in labels
    assert "Exit" in labels


def test_toolbar_open_button(main_window):
    open_action = None
    for toolbar in main_window.findChildren(QToolBar):
        for action in toolbar.actions():
            if action.text() == "Open":
                open_action = action
                break
    assert open_action is not None
    assert open_action.isEnabled()


def test_open_pdf_updates_title(main_window, five_page_pdf, monkeypatch, qtbot):
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(five_page_pdf), "PDF Files (*.pdf)"),
    )
    main_window._open_pdf()
    qtbot.waitUntil(
        lambda: main_window.windowTitle() == f"PageDrop — {five_page_pdf.name}",
        timeout=5000,
    )


def test_status_bar_shows_page_count(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(
        lambda: "Loaded" in main_window.statusBar().currentMessage(),
        timeout=30000,
    )
    message = main_window.statusBar().currentMessage()
    assert "5" in message


def test_exit_action_closes(main_window, qtbot):
    main_window.show()
    exit_action = _find_action_by_text(_file_menu_actions(main_window), "E&xit", "Exit")
    exit_action.trigger()
    qtbot.waitUntil(lambda: not main_window.isVisible(), timeout=5000)
