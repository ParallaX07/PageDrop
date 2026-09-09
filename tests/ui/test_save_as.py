"""Phase 15 UI tests — Save As and unsaved-changes prompts."""

from __future__ import annotations

import hashlib

import fitz
from PyQt6.QtCore import QMimeData
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from pagedrop.core.drag_mime import PAGE_TRANSFER_MIME, encode_page_refs
from pagedrop.core.annotations import AnnotationOp
from pagedrop.core.forms import FormCreateOp, list_form_fields
from pagedrop.core.pdf_editor import PageRef
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.settings import remember_directory
from tests.conftest import wait_for_pdf_loaded
from tests.core.test_jobs import _encrypted_pdf


def _file_hash(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def test_save_as_rejects_imported_source_and_keeps_tab_dirty(
    main_window, five_page_pdf, tmp_path, monkeypatch, qtbot
):
    imported = tmp_path / "imported.pdf"
    doc = fitz.open()
    try:
        doc.new_page()
        doc.save(str(imported))
    finally:
        doc.close()
    imported_bytes = imported.read_bytes()
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    assert tab.edit_model is not None
    tab.edit_model.insert_pages(0, [PageRef(str(imported), 0)])

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(imported), "PDF Files (*.pdf)"),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)

    assert main_window._save_as(tab) is False
    assert imported.read_bytes() == imported_bytes
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


def test_failed_second_save_keeps_previous_baseline_and_pending_markup(
    main_window, five_page_pdf, tmp_path, monkeypatch, qtbot
):
    tab = _load_and_dirty(main_window, qtbot, five_page_pdf)
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    outputs = iter((first, second))
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(next(outputs)), "PDF Files (*.pdf)"),
    )
    assert main_window._save_as(tab)
    tab.markup_session.push_annotation(
        AnnotationOp(kind="comment", page_index=0, points=((40, 80),), text="Keep")
    )
    tab._sync_dirty_from_model()
    monkeypatch.setattr(
        "pagedrop.ui.main_window.write_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("simulated write failure")),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)

    assert not main_window._save_as(tab)
    assert not second.exists()
    assert tab.is_dirty
    assert tab.edit_model is not None
    assert {page.source_path for page in tab.edit_model.iter_pages()} == {str(first)}
    assert [entry.annotation.text for entry in tab.peek_markup_ops() if entry.annotation] == ["Keep"]


def test_repeated_save_preserves_forms_page_order_and_rotation(
    main_window, tmp_path, monkeypatch, qtbot
):
    source = tmp_path / "source.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=300)
        doc.new_page(width=400, height=300)
        doc.save(str(source))
    finally:
        doc.close()
    source_hash = _file_hash(source)
    main_window.showMinimized()
    main_window._load_pdf(str(source))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = _active_tab(main_window)
    assert tab.edit_model is not None
    tab.edit_model.move_pages([1], 0)
    tab.edit_model.rotate_pages([0], 90)
    tab.markup_session.push_form_create(FormCreateOp(0, "Name"))
    tab._sync_dirty_from_model()
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    outputs = iter((first, second))
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(next(outputs)), "PDF Files (*.pdf)"),
    )

    assert main_window._save_as(tab)
    assert main_window._save_as(tab)

    saved = fitz.open(str(second))
    try:
        assert [page.rotation for page in saved] == [90, 0]
        assert [round(page.rect.width) for page in saved] == [300, 200]
    finally:
        saved.close()
    assert [field.name for field in list_form_fields(str(second))] == ["Name"]
    assert _file_hash(source) == source_hash


def _drop_init_blank_tab(main_window, five_page_pdf, qtbot) -> PdfTab:
    main_window.showMinimized()
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    source = main_window._tab_manager.active_tab.thumbnail_grid
    blank = main_window._tab_manager.add_blank_tab()
    ref = source._model.page_at(0)
    mime = QMimeData()
    mime.setData(PAGE_TRANSFER_MIME, encode_page_refs([ref]))
    assert blank.thumbnail_grid.handle_tab_bar_page_drop(
        [ref], move=False, source_grid=source, mime=mime
    )
    return blank


def test_drop_init_tab_title_shows_source_filename(
    main_window, five_page_pdf, qtbot
):
    blank = _drop_init_blank_tab(main_window, five_page_pdf, qtbot)
    blank_idx = main_window._tab_manager.indexOf(blank)

    assert blank.original_path == str(five_page_pdf)
    assert blank.tab_title == f"{five_page_pdf.name}*"
    assert main_window._tab_manager.tabText(blank_idx) == blank.tab_title


def test_drop_init_save_as_updates_tab_title_and_stays_editable(
    main_window, five_page_pdf, tmp_path, monkeypatch, qtbot
):
    blank = _drop_init_blank_tab(main_window, five_page_pdf, qtbot)
    blank_idx = main_window._tab_manager.indexOf(blank)
    output = tmp_path / "saved.pdf"

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF Files (*.pdf)"),
    )

    assert main_window._save_as(blank) is True
    assert output.is_file()
    assert not blank.is_dirty
    assert blank.tab_title == "saved.pdf"
    assert main_window._tab_manager.tabText(blank_idx) == "saved.pdf"
    assert blank.edit_model is not None
    assert blank.edit_model.save_path == str(output)

    blank.thumbnail_grid.selection_manager.select_single(0)
    assert blank.delete_selected_pages()
    assert blank.is_dirty


def test_drop_init_default_save_as_path_uses_untitled_in_last_directory(
    main_window, five_page_pdf, tmp_path, isolated_settings, qtbot
):
    # Set last-dir after drop-init setup so earlier opens cannot clobber it.
    blank = _drop_init_blank_tab(main_window, five_page_pdf, qtbot)
    remember_directory(str(tmp_path))

    assert blank.is_drop_initialized
    assert main_window._default_save_as_path(blank) == str(tmp_path / "untitled.pdf")


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


def test_encrypted_save_as_uses_runtime_credentials(
    main_window, tmp_path, monkeypatch, qtbot
):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = _file_hash(enc)
    output = tmp_path / "copy.pdf"

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("secret", True),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF Files (*.pdf)"),
    )

    main_window.showMinimized()
    main_window._load_pdf(str(enc))
    assert main_window._loader is not None
    tab = _active_tab(main_window)

    assert tab.credentials.get(str(enc)) == "secret"
    # Simulate loader cache miss — reopen must still authenticate via credentials.
    tab._loader_cache.pop(str(enc)).close()
    reopened = tab.get_loader(str(enc))
    assert reopened.page_count == 1

    assert main_window._save_as(tab) is True
    assert output.is_file()
    assert _file_hash(enc) == source_hash
    out = fitz.open(str(output))
    try:
        assert out.page_count == 1
        assert not out.needs_pass
    finally:
        out.close()

    tab.close_loader()
    assert len(tab.credentials) == 0
