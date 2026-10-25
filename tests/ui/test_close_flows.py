"""Closing a tab or window never discards edits or tears down a running job."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from pagedrop.core.jobs import SerializedJobRunner
from pagedrop.ui.tool_shell import ToolShellWindow, run_tool_job
from tests.conftest import file_sha256, wait_for_pdf_loaded
from tests.ui.test_open_in_new_window import _open_single
from tests.ui.test_save_as import _load_and_dirty, _stub_save_dialog


def test_close_tab_save_that_fails_keeps_tab_dirty_with_draft(
    request, main_window, five_page_pdf, tmp_path, monkeypatch, qtbot, unsaved_answer
):
    source_hash = file_sha256(five_page_pdf)
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    draft = tab.recovery_path
    assert draft is not None and draft.is_file()
    locked = tmp_path / "locked"
    locked.mkdir()
    output = locked / "out.pdf"
    locked.chmod(0o500)
    request.addfinalizer(lambda: locked.chmod(0o700))
    if os.access(locked, os.W_OK):
        pytest.skip("directory permissions are not enforced for this user")
    _stub_save_dialog(monkeypatch, output)
    errors: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *args, **kwargs: errors.append(args)
    )
    unsaved_answer.answer = "save"
    index = main_window._tab_manager.indexOf(tab)

    assert main_window._try_close_tab(index) is False

    assert errors, "the failed save must be reported"
    assert main_window._tab_manager.indexOf(tab) >= 0
    assert tab.is_dirty
    assert draft.is_file()
    assert not output.exists()
    assert file_sha256(five_page_pdf) == source_hash


def test_close_tab_save_waits_for_the_output(
    main_window, five_page_pdf, tmp_path, monkeypatch, qtbot, unsaved_answer
):
    source_hash = file_sha256(five_page_pdf)
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    output = tmp_path / "saved.pdf"
    _stub_save_dialog(monkeypatch, output)
    unsaved_answer.answer = "save"
    existed_when_removed: list[bool] = []
    real_close_tab = main_window._tab_manager.close_tab

    def close_tab(index: int) -> None:
        existed_when_removed.append(output.is_file())
        real_close_tab(index)

    monkeypatch.setattr(main_window._tab_manager, "close_tab", close_tab)

    assert main_window._try_close_tab(main_window._tab_manager.indexOf(tab)) is True

    assert existed_when_removed == [True]
    assert output.is_file()
    assert output != five_page_pdf
    assert file_sha256(five_page_pdf) == source_hash


def test_close_clean_tab_during_editor_job_is_refused(
    main_window, five_page_pdf, qtbot
):
    window = main_window
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)
    tab = window._tab_manager.active_tab
    assert tab is not None and not tab.is_dirty
    window._begin_editor_job(tab, "Exporting pages…")

    assert window._try_close_tab(window._tab_manager.indexOf(tab)) is False
    assert window._tab_manager.indexOf(tab) >= 0
    assert window.statusBar().currentMessage() == (
        "Wait for the running task to finish before closing"
    )

    window._end_editor_job(tab)
    assert tab not in window._editor_busy
    assert window._try_close_tab(window._tab_manager.indexOf(tab)) is True


def test_window_close_during_tool_job_asks_and_keeps_staging(
    main_window, monkeypatch, qtbot
):
    main_window.showMinimized()
    shell = ToolShellWindow(title="Test tool", description="Running tool")
    main_window.open_tool_page(shell, page_id="test-tool")
    shell.begin_job("Working…")
    staging = main_window._temp_manager.create_job_dir()
    (staging / "partial.pdf").write_bytes(b"%PDF-1.7")
    asked: list[object] = []
    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.prompt_cancel_running_job",
        lambda *args, **kwargs: asked.append(args) or False,
    )

    main_window.close()

    assert len(asked) == 1
    assert main_window.isVisible()
    assert shell.is_job_running()
    assert (staging / "partial.pdf").is_file()


def test_window_close_with_dirty_tab_waits_for_save(
    main_window, five_page_pdf, tmp_path, monkeypatch, qtbot, unsaved_answer
):
    source_hash = file_sha256(five_page_pdf)
    _load_and_dirty(main_window, qtbot, five_page_pdf)
    output = tmp_path / "saved.pdf"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF files (*.pdf)"),
    )
    unsaved_answer.answer = "save"
    main_window.show()

    main_window.close()

    assert unsaved_answer.calls
    assert output.is_file()
    assert not main_window.isVisible()
    assert file_sha256(five_page_pdf) == source_hash
    assert output != five_page_pdf


def test_window_close_is_refused_while_an_editor_job_runs(
    main_window, five_page_pdf, qtbot
):
    main_window.showMinimized()
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = main_window._tab_manager.active_tab
    assert tab is not None
    main_window._begin_editor_job(tab, "Exporting pages…")
    staging = main_window._temp_manager.create_job_dir()

    main_window.close()

    assert main_window.isVisible()
    assert main_window.statusBar().currentMessage() == (
        "Wait for the running task to finish before closing"
    )
    assert staging.is_dir()
    main_window._end_editor_job(tab)


def test_open_into_current_tab_is_refused_while_it_is_busy(
    main_window, five_page_pdf, one_page_pdf, monkeypatch, qtbot, unsaved_answer
):
    main_window.showMinimized()
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = main_window._tab_manager.active_tab
    assert tab is not None
    main_window._begin_editor_job(tab, "Saving PDF…")

    _open_single(main_window, one_page_pdf, monkeypatch, target="current")

    assert main_window.statusBar().currentMessage() == (
        "Wait for the running task to finish before opening"
    )
    assert tab.pdf_path == str(five_page_pdf)
    assert not unsaved_answer.calls
    main_window._end_editor_job(tab)


def test_window_close_waits_for_a_cancelled_tool_worker(
    main_window, one_page_pdf, tmp_path, monkeypatch, qtbot
):
    entered = threading.Event()
    release = threading.Event()
    staging: list[Path] = []

    def gated(ctx):
        staging.append(ctx.staged_output.parent)
        entered.set()
        assert release.wait(timeout=10), "test never released the worker"
        ctx.staged_output.write_bytes(one_page_pdf.read_bytes())
        return ctx.staged_output

    main_window.showMinimized()
    shell = ToolShellWindow(title="Test tool", description="Gated tool")
    main_window.open_tool_page(shell, page_id="test-tool")
    runner = SerializedJobRunner(main_window._temp_manager)
    runner.register("gated", gated, holds_fitz=False)
    shell._job_runner = runner
    output = tmp_path / "out.pdf"
    source_hash = file_sha256(one_page_pdf)
    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.prompt_cancel_running_job", lambda *a, **k: True
    )
    run_tool_job(
        shell,
        job_type="gated",
        inputs=[str(one_page_pdf)],
        output=str(output),
        existing_paths=[],
    )
    qtbot.waitUntil(entered.is_set, timeout=10_000)

    main_window.close()

    assert main_window.isVisible()
    assert staging[0].is_dir()
    assert main_window.statusBar().currentMessage() == "Cancelling the running task…"
    assert shell.worker_pending()

    release.set()
    qtbot.waitUntil(lambda: not main_window.isVisible(), timeout=10_000)
    assert not staging[0].exists()
    assert not output.exists()
    assert file_sha256(one_page_pdf) == source_hash
