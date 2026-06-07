"""Phase 8 UI tests — error handling and edge cases."""

from __future__ import annotations

from unittest.mock import patch

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QMessageBox

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.ui.page_card import PageCard
from pagedrop.utils.temp_manager import TempManager


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
    selection_manager = SelectionManager()
    selection_manager.set_page_count(loader.page_count)
    temp_manager = TempManager()

    card = PageCard(0)
    qtbot.addWidget(card)
    card.resize(200, 200)
    card.show()
    card.set_drag_context(loader, selection_manager, temp_manager)
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
        "pagedrop.ui.page_card.extract_pages_to_files",
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


def test_single_page_pdf_selection_and_drag(qtbot, one_page_pdf, monkeypatch):
    loader = PdfLoader(str(one_page_pdf))
    selection_manager = SelectionManager()
    selection_manager.set_page_count(loader.page_count)
    temp_manager = TempManager()

    card = PageCard(0)
    qtbot.addWidget(card)
    card.resize(200, 200)
    card.show()
    card.set_drag_context(loader, selection_manager, temp_manager)

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
