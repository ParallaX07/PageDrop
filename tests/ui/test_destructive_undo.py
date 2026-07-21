"""Destructive actions, confirm prefs, and undo/redo."""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QMessageBox

from pagedrop.ui.dialogs import confirm_delete_pages
from pagedrop.ui.settings import (
    DELETE_CONFIRM_THRESHOLD,
    confirm_before_closing_dirty_tabs,
    confirm_before_deleting_multiple_pages,
    set_confirm_before_closing_dirty_tabs,
    set_confirm_before_deleting_multiple_pages,
)
from pagedrop.ui.window_manager import WindowManager
from tests.conftest import load_pdf_in_active_tab, wait_for_pdf_loaded
from tests.ui.test_cross_window_page_drag import _cross_window_drop, _model_refs


def test_confirm_prefs_default_true(isolated_settings):
    assert confirm_before_deleting_multiple_pages() is True
    assert confirm_before_closing_dirty_tabs() is True


def test_confirm_prefs_round_trip(isolated_settings):
    set_confirm_before_deleting_multiple_pages(False)
    set_confirm_before_closing_dirty_tabs(False)
    assert confirm_before_deleting_multiple_pages() is False
    assert confirm_before_closing_dirty_tabs() is False


def test_confirm_delete_pages_skips_small_selection(isolated_settings):
    assert confirm_delete_pages(None, DELETE_CONFIRM_THRESHOLD) is True
    assert confirm_delete_pages(None, 1) is True


def test_confirm_delete_pages_respects_preference(isolated_settings, monkeypatch):
    set_confirm_before_deleting_multiple_pages(False)
    called = []

    def boom(*_args, **_kwargs):
        called.append(True)
        return QMessageBox.StandardButton.No

    monkeypatch.delenv("PAGEDROP_TESTING", raising=False)
    monkeypatch.setattr(QMessageBox, "question", boom)
    assert confirm_delete_pages(None, DELETE_CONFIRM_THRESHOLD + 1) is True
    assert not called


def test_confirm_delete_pages_prompts_when_enabled(isolated_settings, monkeypatch):
    answers = []

    def fake_question(*_args, **_kwargs):
        answers.append(True)
        return QMessageBox.StandardButton.No

    monkeypatch.delenv("PAGEDROP_TESTING", raising=False)
    monkeypatch.setattr(QMessageBox, "question", fake_question)
    assert confirm_delete_pages(None, DELETE_CONFIRM_THRESHOLD + 1) is False
    assert answers == [True]


def test_undo_redo_via_main_window(main_window, qtbot, five_page_pdf):
    load_pdf_in_active_tab(main_window, five_page_pdf)
    wait_for_pdf_loaded(qtbot, main_window)
    tab = main_window._active_tab()
    assert tab is not None

    tab.thumbnail_grid.selection_manager.set_selection({1, 2})
    main_window._delete_selected_pages()
    assert tab.edit_model.logical_count() == 3
    assert main_window._undo_action.isEnabled()

    main_window._undo()
    assert tab.edit_model.logical_count() == 5
    assert main_window._redo_action.isEnabled()

    main_window._redo()
    assert tab.edit_model.logical_count() == 3


def test_dirty_close_skips_prompt_when_pref_off(
    main_window, qtbot, five_page_pdf, isolated_settings, monkeypatch
):
    set_confirm_before_closing_dirty_tabs(False)
    load_pdf_in_active_tab(main_window, five_page_pdf)
    wait_for_pdf_loaded(qtbot, main_window)
    tab = main_window._active_tab()
    assert tab is not None
    tab.thumbnail_grid.selection_manager.set_selection({0})
    assert tab.delete_selected_pages()
    assert tab.is_dirty

    prompted = []

    def fake_prompt(_tab):
        prompted.append(True)
        return "cancel"

    monkeypatch.setattr(main_window, "_prompt_unsaved_changes", fake_prompt)
    main_window._tab_manager.add_blank_tab()
    index = main_window._tab_manager.indexOf(tab)
    assert main_window._try_close_tab(index)
    assert not prompted


def test_shift_move_offers_transient_undo(
    main_window, qtbot, five_page_pdf, one_page_pdf
):
    app = QApplication.instance()
    manager = WindowManager(app)
    manager._register(main_window)
    main_window._window_manager = manager
    main_window.show()

    load_pdf_in_active_tab(main_window, five_page_pdf)
    wait_for_pdf_loaded(qtbot, main_window)
    source = main_window._active_tab()
    assert source is not None

    other = manager.open_new_window()
    qtbot.addWidget(other)
    load_pdf_in_active_tab(other, one_page_pdf)
    wait_for_pdf_loaded(qtbot, other)
    target = other._active_tab()
    assert target is not None

    source_before = _model_refs(source.thumbnail_grid)
    target_before = _model_refs(target.thumbnail_grid)

    assert _cross_window_drop(
        target.thumbnail_grid,
        source.thumbnail_grid,
        [2],
        shift=True,
        drop_index=1,
    )
    assert main_window._pending_move_undo is not None
    assert "1 page moved" in main_window._move_undo_label.text()
    assert main_window._move_undo_timer.isActive()

    main_window._on_transient_move_undo()
    assert _model_refs(source.thumbnail_grid) == source_before
    assert _model_refs(target.thumbnail_grid) == target_before
    assert main_window._pending_move_undo is None
    assert not main_window._move_undo_timer.isActive()
