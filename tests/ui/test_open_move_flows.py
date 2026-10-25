"""Open and move flows never discard dirty edits or move a busy tab."""

from __future__ import annotations

import fitz
from PyQt6.QtWidgets import QMessageBox

from pagedrop.core.pdf_loader import PdfPasswordRequiredError
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from tests.conftest import file_sha256, wait_for_pdf_loaded
from tests.core.test_jobs import _encrypted_pdf
from tests.ui.test_open_in_new_window import _open_single
from tests.ui.test_save_as import _load_and_dirty


def test_open_into_dirty_tab_asks_and_cancel_keeps_document(
    main_window, five_page_pdf, one_page_pdf, monkeypatch, qtbot, unsaved_answer
):
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    assert tab.edit_model is not None
    before = tab.edit_model.logical_count()
    unsaved_answer.answer = "cancel"

    _open_single(main_window, one_page_pdf, monkeypatch, target="current")

    assert unsaved_answer.calls == [tab.tab_title]
    assert tab.pdf_path == str(five_page_pdf)
    assert tab.is_dirty
    assert tab.edit_model.logical_count() == before


def test_open_into_dirty_tab_discard_loads_new_document(
    main_window, five_page_pdf, one_page_pdf, monkeypatch, qtbot, unsaved_answer
):
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    unsaved_answer.answer = "discard"

    _open_single(main_window, one_page_pdf, monkeypatch, target="current")

    assert len(unsaved_answer.calls) == 1
    assert tab.pdf_path == str(one_page_pdf)
    assert not tab.is_dirty


def test_cancelled_password_keeps_previous_document_and_draft(
    main_window, five_page_pdf, tmp_path, monkeypatch, qtbot, unsaved_answer
):
    locked = tmp_path / "locked.pdf"
    _encrypted_pdf(locked, password="secret")
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    assert tab.edit_model is not None
    before = tab.edit_model.logical_count()
    draft = tab.recovery_path
    assert draft is not None and draft.is_file()
    unsaved_answer.answer = "discard"
    monkeypatch.setattr(main_window, "_prompt_pdf_password", lambda *a, **k: None)

    _open_single(main_window, locked, monkeypatch, target="current")

    assert tab.pdf_path == str(five_page_pdf)
    assert tab.edit_model.logical_count() == before
    assert tab.is_dirty
    assert tab.loader is not None
    assert draft.is_file()


def test_failed_load_keeps_previous_document(qtbot, five_page_pdf, tmp_path):
    from pagedrop.utils.temp_manager import TempManager

    locked = tmp_path / "locked.pdf"
    _encrypted_pdf(locked, password="secret")
    tab = PdfTab(TempManager())
    qtbot.addWidget(tab)
    tab.load_pdf(str(five_page_pdf))
    model = tab.edit_model

    try:
        tab.load_pdf(str(locked))
    except PdfPasswordRequiredError:
        pass
    else:
        raise AssertionError("expected a password error")

    assert tab.edit_model is model
    assert tab.pdf_path == str(five_page_pdf)
    assert tab.loader is not None and tab.loader.page_count == 5


def test_detach_busy_tab_is_refused(main_window, five_page_pdf, qtbot):
    window: MainWindow = main_window
    window.showMinimized()
    window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, window)
    tab = window._tab_manager.active_tab
    assert tab is not None
    window._begin_editor_job(tab, "Exporting pages…")
    index = window._tab_manager.indexOf(tab)

    window._detach_tab_to_new_window(index)

    assert window._tab_manager.indexOf(tab) == index
    assert window.statusBar().currentMessage() == (
        "Wait for the running task to finish before moving"
    )
    window._end_editor_job(tab)


def _locked_draft(qtbot, window, tmp_path):
    from pagedrop.utils.temp_manager import TempManager

    locked = tmp_path / "locked.pdf"
    doc = fitz.open()
    try:
        for _ in range(3):
            doc.new_page(width=200, height=200)
        doc.save(str(locked), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret")
    finally:
        doc.close()
    source = PdfTab(TempManager(), recovery_dir=window._recovery_dir)
    qtbot.addWidget(source)
    source.load_pdf(str(locked), password="secret")
    assert source.edit_model is not None
    source.edit_model.remove_pages([0])
    source._sync_dirty_from_model()
    draft = source.recovery_path
    assert draft is not None and draft.is_file()
    return locked, draft


def test_recovery_of_protected_source_retries_wrong_password(
    main_window, tmp_path, monkeypatch, qtbot
):
    locked, draft = _locked_draft(qtbot, main_window, tmp_path)
    source_hash = file_sha256(locked)
    answers = iter(["wrong", "secret"])
    asked: list[bool] = []

    def prompt(filename, *, incorrect=False):
        asked.append(incorrect)
        return next(answers)

    monkeypatch.setattr(main_window, "_prompt_pdf_password", prompt)
    monkeypatch.setattr("pagedrop.ui.main_window.process_is_alive", lambda pid: False)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )

    assert main_window.restore_recovery_drafts() == 1

    assert asked == [False, True]
    tab = main_window._tab_manager.active_tab
    assert tab is not None and tab.is_dirty
    assert tab.edit_model is not None and tab.edit_model.logical_count() == 2
    assert file_sha256(locked) == source_hash
    assert "secret" not in draft.read_text()


def test_recovery_cancelled_password_reports_failure_and_keeps_draft(
    main_window, tmp_path, monkeypatch, qtbot
):
    locked, draft = _locked_draft(qtbot, main_window, tmp_path)
    warnings: list[str] = []
    monkeypatch.setattr(main_window, "_prompt_pdf_password", lambda *a, **k: None)
    monkeypatch.setattr("pagedrop.ui.main_window.process_is_alive", lambda pid: False)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _p, _t, text, *a, **k: warnings.append(text)
    )

    assert main_window.restore_recovery_drafts() == 0

    assert draft.is_file()
    assert len(warnings) == 1 and "locked.pdf" in warnings[0]
