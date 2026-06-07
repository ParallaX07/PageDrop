"""Phase 15 UI tests — Save As and unsaved-changes prompts."""

from __future__ import annotations

from PyQt6.QtWidgets import QFileDialog

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from tests.conftest import wait_for_pdf_loaded


def _active_tab(window: MainWindow) -> PdfTab:
    tab = window._tab_manager.active_tab
    assert tab is not None
    return tab


def _load_and_dirty(window: MainWindow, qtbot, pdf_path) -> PdfTab:
    window.showMinimized()
    window._load_pdf(str(pdf_path))
    wait_for_pdf_loaded(qtbot, window)
    tab = _active_tab(window)
    tab.thumbnail_grid.selection_manager.select_single(0)
    assert tab.delete_selected_pages()
    assert tab.is_dirty
    return tab


def test_save_as_never_writes_original_path(
    main_window, five_page_pdf, monkeypatch, qtbot
):
    original_bytes = five_page_pdf.read_bytes()
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(five_page_pdf), "PDF Files (*.pdf)"),
    )

    assert main_window._save_as(tab) is False
    assert five_page_pdf.read_bytes() == original_bytes
    assert tab.is_dirty


def test_dirty_flag_cleared_after_save(
    main_window, five_page_pdf, tmp_path, monkeypatch, qtbot
):
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    output = tmp_path / "saved.pdf"

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF Files (*.pdf)"),
    )

    assert main_window._save_as(tab) is True
    assert output.is_file()
    assert not tab.is_dirty
    assert tab.edit_model is not None
    assert tab.edit_model.save_path == str(output)
    assert tab.tab_title == "saved.pdf"
    assert "*" not in main_window._tab_manager.tabText(0)


def test_close_dirty_tab_shows_prompt(main_window, five_page_pdf, monkeypatch, qtbot):
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    prompt_calls: list[PdfTab] = []

    def fake_prompt(target: PdfTab) -> str:
        prompt_calls.append(target)
        return "cancel"

    monkeypatch.setattr(main_window, "_prompt_unsaved_changes", fake_prompt)

    count_before = main_window._tab_manager.count()
    main_window._close_tab()

    assert prompt_calls == [tab]
    assert main_window._tab_manager.count() == count_before
    assert tab.is_dirty
