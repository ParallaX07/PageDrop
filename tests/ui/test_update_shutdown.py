"""Phase U5 — process-wide document preparation before installer handoff."""

from __future__ import annotations

import hashlib

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from pagedrop.ui.update_checker import UpdateState
from pagedrop.ui.window_manager import WindowManager
from pagedrop.ui.settings import set_confirm_before_closing_dirty_tabs
from tests.ui.test_save_as import _drop_init_blank_tab, _load_and_dirty


def _manager(qapp) -> WindowManager:
    manager = WindowManager(qapp)
    manager.update_coordinator._set_state(UpdateState.READY)
    return manager


def _quiet_messages(monkeypatch) -> None:
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)


def test_preparation_blocks_jobs_in_an_inactive_window(qapp, monkeypatch):
    manager = _manager(qapp)
    first = manager.create_window()
    second = manager.create_window()
    blocker = QWidget(second)
    blocker.is_job_running = lambda: True
    _quiet_messages(monkeypatch)

    assert not manager.prepare_for_installation(first)
    assert manager.update_coordinator.state is UpdateState.READY
    assert first.isEnabled() and second.isEnabled()


def test_discard_keeps_dirty_documents_intact_and_blocks_reentry(
    qapp, five_page_pdf, qtbot, monkeypatch
):
    manager = _manager(qapp)
    first = manager.create_window()
    second = manager.create_window()
    first.showMinimized()
    second.showMinimized()
    first_tab = _load_and_dirty(first, qtbot, five_page_pdf)
    second_tab = _load_and_dirty(second, qtbot, five_page_pdf)
    monkeypatch.setattr(first, "_prompt_unsaved_changes", lambda tab: "discard")
    monkeypatch.setattr(second, "_prompt_unsaved_changes", lambda tab: "discard")

    assert manager.prepare_for_installation(first)
    assert manager.preparing_installation
    assert first_tab.is_dirty and second_tab.is_dirty
    assert manager.open_new_window() is None
    assert not first._try_close_tab(first._tab_manager.indexOf(first_tab))
    before = first._tab_manager.count()
    first.open_tool_page(QWidget(), page_id="test-tool")
    assert first._tab_manager.count() == before

    manager.cancel_installation_preparation()
    assert first.isEnabled() and second.isEnabled()
    assert first_tab.is_dirty and second_tab.is_dirty
    assert manager.update_coordinator.state is UpdateState.READY


def test_preparation_collects_a_dirty_drop_initialized_blank_tab(
    qapp, five_page_pdf, qtbot, monkeypatch, isolated_settings
):
    manager = _manager(qapp)
    window = manager.create_window()
    blank = _drop_init_blank_tab(window, five_page_pdf, qtbot)
    assert blank.is_dirty and blank.is_drop_initialized
    prompts = []
    set_confirm_before_closing_dirty_tabs(False)
    monkeypatch.setattr(
        window, "_prompt_unsaved_changes", lambda tab: prompts.append(tab) or "discard"
    )

    assert manager.prepare_for_installation(window)
    assert prompts == [blank]
    assert blank.is_dirty
    manager.cancel_installation_preparation()


def test_cancel_after_an_earlier_save_keeps_other_windows_usable(
    qapp, five_page_pdf, tmp_path, qtbot, monkeypatch
):
    manager = _manager(qapp)
    first = manager.create_window()
    second = manager.create_window()
    first.showMinimized()
    second.showMinimized()
    source_hash = hashlib.sha256(five_page_pdf.read_bytes()).hexdigest()
    saved_tab = _load_and_dirty(first, qtbot, five_page_pdf)
    cancelled_tab = _load_and_dirty(second, qtbot, five_page_pdf)
    output = tmp_path / "saved-before-cancel.pdf"
    monkeypatch.setattr(first, "_prompt_unsaved_changes", lambda tab: "save")
    monkeypatch.setattr(second, "_prompt_unsaved_changes", lambda tab: "cancel")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(output), "PDF files (*.pdf)")
    )

    assert not manager.prepare_for_installation(first)
    assert output.is_file()
    assert hashlib.sha256(five_page_pdf.read_bytes()).hexdigest() == source_hash
    assert not saved_tab.is_dirty
    assert cancelled_tab.is_dirty
    assert first.isEnabled() and second.isEnabled()
    assert manager.update_coordinator.state is UpdateState.READY


def test_failed_save_restores_interaction_without_discarding(qapp, five_page_pdf, qtbot, monkeypatch):
    manager = _manager(qapp)
    window = manager.create_window()
    window.showMinimized()
    tab = _load_and_dirty(window, qtbot, five_page_pdf)
    monkeypatch.setattr(window, "_prompt_unsaved_changes", lambda target: "save")
    monkeypatch.setattr(window, "_save_as", lambda target: False)

    assert not manager.prepare_for_installation(window)
    assert tab.is_dirty and window.isEnabled()
    assert manager.update_coordinator.state is UpdateState.READY
