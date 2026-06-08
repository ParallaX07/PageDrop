"""UI tests — rename unsaved tabs."""

from __future__ import annotations

from PyQt6.QtCore import QMimeData
from PyQt6.QtWidgets import QInputDialog

from pagedrop.core.drag_mime import PAGE_TRANSFER_MIME, encode_page_refs
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab, sanitize_tab_title_stem
from tests.conftest import wait_for_pdf_loaded
from tests.ui.test_save_as import _drop_init_blank_tab, _load_and_dirty


def _active_tab(window: MainWindow) -> PdfTab:
    tab = window._tab_manager.active_tab
    assert tab is not None
    return tab


def test_sanitize_tab_title_stem():
    assert sanitize_tab_title_stem("My Report") == "My Report"
    assert sanitize_tab_title_stem("draft.pdf") == "draft"
    assert sanitize_tab_title_stem('bad/name') == "bad_name"
    assert sanitize_tab_title_stem("   ") == "untitled"


def test_rename_blank_tab(main_window, monkeypatch):
    tab = _active_tab(main_window)
    assert tab.is_blank
    assert tab.can_rename_tab

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Project Notes", True),
    )

    main_window._rename_tab(0)
    assert tab.custom_tab_title == "Project Notes"
    assert main_window._tab_manager.tabText(0) == "Project Notes"


def test_rename_unsaved_dirty_tab(main_window, five_page_pdf, monkeypatch, qtbot):
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    assert tab.can_rename_tab

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Working Copy", True),
    )

    main_window._rename_tab(0)
    assert tab.custom_tab_title == "Working Copy"
    assert tab.tab_title == "Working Copy*"
    assert main_window._tab_manager.tabText(0) == "Working Copy*"


def test_rename_drop_init_tab(main_window, five_page_pdf, monkeypatch, qtbot):
    blank = _drop_init_blank_tab(main_window, five_page_pdf, qtbot)
    blank_idx = main_window._tab_manager.indexOf(blank)

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Imported Pages", True),
    )

    main_window._rename_tab(blank_idx)
    assert blank.custom_tab_title == "Imported Pages"
    assert blank.tab_title == "Imported Pages*"
    assert main_window._tab_manager.tabText(blank_idx) == "Imported Pages*"


def test_rename_cannot_rename_after_save(
    main_window, five_page_pdf, tmp_path, monkeypatch, qtbot
):
    from PyQt6.QtWidgets import QFileDialog

    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    tab.set_custom_tab_title("Temporary Name")
    output = tmp_path / "saved.pdf"

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF Files (*.pdf)"),
    )

    assert main_window._save_as(tab) is True
    assert tab.custom_tab_title is None
    assert not tab.can_rename_tab
    assert tab.tab_title == "saved.pdf"


def test_custom_title_used_for_default_save_as_path(
    main_window, five_page_pdf, tmp_path, qtbot
):
    from tests.ui.test_save_as import remember_directory

    remember_directory(str(tmp_path))
    blank = _drop_init_blank_tab(main_window, five_page_pdf, qtbot)
    blank.set_custom_tab_title("Quarterly Report")

    assert main_window._default_save_as_path(blank) == str(
        tmp_path / "Quarterly Report.pdf"
    )


def test_rename_tab_cancelled_leaves_title(main_window, monkeypatch):
    tab = _active_tab(main_window)

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Ignored", False),
    )

    main_window._rename_tab(0)
    assert tab.custom_tab_title is None
    assert tab.tab_title == "New Tab"
