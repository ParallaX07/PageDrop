"""Window & tab management UX — titles, geometry, Open Recent."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QByteArray
from PyQt6.QtWidgets import QMessageBox

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.settings import (
    load_window_geometry,
    recent_files,
    remember_recent_file,
    remember_window_geometry,
    save_window_geometry,
    set_remember_window_geometry,
)
from tests.conftest import wait_for_pdf_loaded
from tests.ui.test_save_as import _load_and_dirty


def _file_menu(window: MainWindow):
    for action in window.menuBar().actions():
        if action.text().replace("&", "") == "File":
            return action.menu()
    raise AssertionError("File menu not found")


def _open_recent_menu(window: MainWindow):
    for action in _file_menu(window).actions():
        if action.text().replace("&", "") == "Open recent":
            return action.menu()
    raise AssertionError("Open recent menu not found")


def test_window_title_includes_dirty_star(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    assert (
        main_window.windowTitle()
        == f"PageDrop: {five_page_pdf.name} (5 pages)"
    )

    tab = main_window._tab_manager.active_tab
    tab.thumbnail_grid.selection_manager.select_single(0)
    assert tab.delete_selected_pages()
    assert (
        main_window.windowTitle()
        == f"PageDrop: {five_page_pdf.name}* (4 pages)"
    )


def test_unsaved_prompt_uses_custom_tab_title(
    main_window, five_page_pdf, monkeypatch, qtbot
):
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    assert tab.set_custom_tab_title("Working Copy")

    seen: dict[str, str] = {}

    class FakeBox(QMessageBox):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._text = ""

        def setText(self, text: str) -> None:
            self._text = text
            seen["text"] = text
            super().setText(text)

        def exec(self) -> int:
            return 0

        def clickedButton(self):
            return None

        def addButton(self, *args, **kwargs):
            return super().addButton(*args, **kwargs)

    monkeypatch.delenv("PAGEDROP_TESTING", raising=False)
    monkeypatch.setattr(
        "pagedrop.ui.dialogs.QMessageBox",
        FakeBox,
    )
    monkeypatch.setattr(
        "pagedrop.ui.dialogs.fit_message_box_buttons",
        lambda _msg: None,
    )

    assert main_window._prompt_unsaved_changes(tab) == "cancel"
    assert seen["text"] == '"Working Copy" has unsaved changes.'


def test_recent_files_round_trip(isolated_settings, tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"%PDF")
    b.write_bytes(b"%PDF")

    remember_recent_file(a)
    remember_recent_file(b)
    paths = recent_files()
    assert [Path(p).name for p in paths] == ["b.pdf", "a.pdf"]

    remember_recent_file(a)
    assert [Path(p).name for p in recent_files()] == ["a.pdf", "b.pdf"]


def test_open_recent_menu_and_blank_tab_policy(
    main_window, five_page_pdf, one_page_pdf, isolated_settings, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    assert recent_files()
    assert Path(recent_files()[0]).resolve() == five_page_pdf.resolve()

    menu = _open_recent_menu(main_window)
    menu.aboutToShow.emit()
    actions = [a for a in menu.actions() if a.isEnabled()]
    assert actions
    assert five_page_pdf.name in actions[0].text().replace("&", "")

    # Occupied tab → recent open creates a new tab.
    main_window._open_recent_path(str(one_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    assert main_window._tab_manager.count() == 2
    assert Path(main_window._tab_manager.active_tab.pdf_path).resolve() == (
        one_page_pdf.resolve()
    )

    # Blank tab → recent open reuses it.
    blank = main_window._tab_manager.add_blank_tab()
    main_window._tab_manager.setCurrentWidget(blank)
    before = main_window._tab_manager.count()
    main_window._open_recent_path(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    assert main_window._tab_manager.count() == before
    assert Path(main_window._tab_manager.active_tab.pdf_path).resolve() == (
        five_page_pdf.resolve()
    )


def test_window_geometry_pref_and_round_trip(isolated_settings, qtbot):
    assert remember_window_geometry() is True
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(842, 631)
    geom = window.saveGeometry()
    assert isinstance(geom, QByteArray)
    assert not geom.isEmpty()

    save_window_geometry(geom)
    loaded = load_window_geometry()
    assert loaded is not None
    assert bytes(loaded) == bytes(geom)

    set_remember_window_geometry(False)
    assert load_window_geometry() is None
    save_window_geometry(geom)  # preference off → no overwrite required
    assert remember_window_geometry() is False

    other = MainWindow()
    qtbot.addWidget(other)
    set_remember_window_geometry(True)
    assert other.restore_saved_geometry() is True
