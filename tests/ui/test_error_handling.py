"""Phase 8 UI tests — error handling and edge cases."""

from __future__ import annotations

from unittest.mock import patch

import fitz
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.ui.page_card import PageCard
from pagedrop.utils.temp_manager import TempManager


def _encrypted_pdf(path, *, password: str = "secret") -> None:
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw="owner",
        )
    finally:
        doc.close()


def test_open_corrupt_shows_message_box(main_window, corrupt_pdf, monkeypatch):
    captured: list[tuple[str, str]] = []

    def fake_critical(parent, title, text):
        captured.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", fake_critical)

    main_window._load_pdf(str(corrupt_pdf))

    assert len(captured) == 1
    title, text = captured[0]
    assert title == "Open PDF"
    assert corrupt_pdf.name in text
    assert main_window._loader is None
    assert len(main_window._thumbnail_grid._cards) == 0


def test_open_empty_pdf_shows_warning_no_grid(main_window, empty_pdf, monkeypatch):
    captured: list[tuple[str, str]] = []

    def fake_warning(parent, title, text):
        captured.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)

    main_window._load_pdf(str(empty_pdf))

    assert len(captured) == 1
    assert empty_pdf.name in captured[0][1]
    assert main_window._loader is None
    assert len(main_window._thumbnail_grid._cards) == 0


def test_open_password_pdf_prompts_retries_then_opens(
    main_window, tmp_path, monkeypatch, qtbot
):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")

    prompts: list[str] = []
    replies = iter([("wrong", True), ("secret", True)])

    def fake_get_text(parent, title, label, *args, **kwargs):
        prompts.append(label)
        return next(replies)

    monkeypatch.setattr(QInputDialog, "getText", fake_get_text)

    main_window._load_pdf(str(enc))

    assert len(prompts) == 2
    assert "password-protected" in prompts[0]
    assert "Incorrect password" in prompts[1]
    assert main_window._loader is not None
    assert main_window._loader.page_count == 1
    qtbot.waitUntil(
        lambda: len(main_window._thumbnail_grid._cards) == 1,
        timeout=15000,
    )


def test_open_password_pdf_cancel_leaves_blank(main_window, tmp_path, monkeypatch):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc)

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("", False),
    )

    main_window._load_pdf(str(enc))

    assert main_window._loader is None
    assert main_window._active_tab() is not None
    assert main_window._active_tab().is_blank


def test_page_transfer_failed_shows_warning(main_window, five_page_pdf, monkeypatch):
    main_window._load_pdf(str(five_page_pdf))
    captured: list[tuple[str, str]] = []

    def fake_warning(parent, title, text):
        captured.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)

    main_window._thumbnail_grid.page_transfer_failed.emit("Could not move pages")

    assert captured == [("Page Transfer", "Could not move pages")]
    assert main_window.statusBar().currentMessage() == "Could not move pages"


def test_drag_without_pdf_shows_status_message(main_window, qtbot):
    card = PageCard(0, main_window._thumbnail_grid._container)
    qtbot.addWidget(card)
    card.resize(200, 200)
    card.show()
    main_window.show()

    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(card, pos=QPoint(200, 200))

    assert main_window.statusBar().currentMessage() == "Open a PDF first"


def test_disk_full_oserror(qtbot, five_page_pdf, monkeypatch):
    loader = PdfLoader(str(five_page_pdf))
    model = PdfEditModel(loader.path, loader.page_count)
    selection_manager = SelectionManager()
    selection_manager.set_page_count(model.logical_count())
    temp_manager = TempManager()

    card = PageCard(0)
    qtbot.addWidget(card)
    card.resize(200, 200)
    card.show()
    card.set_drag_context(model, selection_manager, temp_manager)
    selection_manager.select_single(0)

    captured: list[tuple[str, str]] = []

    def fake_critical(parent, title, text):
        captured.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", fake_critical)

    def fake_exec(self, *args, **kwargs):
        return Qt.DropAction.IgnoreAction

    monkeypatch.setattr(QDrag, "exec", fake_exec)

    with patch(
        "pagedrop.ui.page_card.extract_page_refs_to_files",
        side_effect=OSError(28, "No space left on device"),
    ):
        qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        qtbot.mouseMove(card, pos=QPoint(200, 200))

    assert len(captured) == 1
    assert "disk full" in captured[0][1].lower() or "write error" in captured[0][1].lower()
    loader.close()


def test_rapid_reopen_cancels_worker(main_window, five_page_pdf, one_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    assert len(main_window._thumbnail_grid._cards) == 5

    main_window._load_pdf(str(one_page_pdf))
    assert len(main_window._thumbnail_grid._cards) == 1
    assert one_page_pdf.name in main_window.windowTitle()

    qtbot.waitUntil(
        lambda: "Loaded" in main_window.statusBar().currentMessage(),
        timeout=15000,
    )
    assert len(main_window._thumbnail_grid._cards) == 1
    assert five_page_pdf.name not in main_window.windowTitle()


def test_rapid_reopen_shows_cancelled_toast(main_window, five_page_pdf, one_page_pdf, monkeypatch):
    main_window._load_pdf(str(five_page_pdf))
    monkeypatch.setattr(
        main_window._thumbnail_grid,
        "has_pending_work",
        lambda: True,
    )
    toasts: list[str] = []
    monkeypatch.setattr(main_window, "_show_toast", toasts.append)

    main_window._load_pdf(str(one_page_pdf))

    assert toasts == ["Cancelled previous load"]
    assert len(main_window._thumbnail_grid._cards) == 1


def test_single_page_pdf_selection_and_drag(qtbot, one_page_pdf, monkeypatch):
    loader = PdfLoader(str(one_page_pdf))
    model = PdfEditModel(loader.path, loader.page_count)
    selection_manager = SelectionManager()
    selection_manager.set_page_count(model.logical_count())
    temp_manager = TempManager()

    card = PageCard(0)
    qtbot.addWidget(card)
    card.resize(200, 200)
    card.show()
    card.set_drag_context(model, selection_manager, temp_manager)

    drag_started: list[bool] = []

    def fake_exec(self, *args, **kwargs):
        drag_started.append(True)
        return Qt.DropAction.IgnoreAction

    monkeypatch.setattr(QDrag, "exec", fake_exec)

    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(card, pos=QPoint(200, 200))

    assert selection_manager.selection == {0}
    assert drag_started == [True]
    loader.close()
