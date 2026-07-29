"""Phase 6 UI tests — drag-and-drop preparation on PageCard."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QInputDialog

from pagedrop.core.drag_mime import INTERNAL_PAGE_MIME, decode_page_indices
from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.ui.page_card import PageCard
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import wait_for_pdf_loaded
from tests.core.test_jobs import _encrypted_pdf


def _make_card(
    qtbot,
    pdf_path,
    page_index: int = 0,
) -> tuple[PageCard, PdfLoader, SelectionManager, TempManager]:
    loader = PdfLoader(str(pdf_path))
    model = PdfEditModel(loader.path, loader.page_count)
    selection_manager = SelectionManager()
    selection_manager.set_page_count(model.logical_count())
    temp_manager = TempManager()

    card = PageCard(page_index)
    qtbot.addWidget(card)
    card.resize(200, 200)
    card.show()
    card.set_drag_context(model, selection_manager, temp_manager)
    return card, loader, selection_manager, temp_manager


def _patch_drag_exec(monkeypatch, on_exec):
    def fake_exec(self, *args, **kwargs):
        on_exec(self)
        return Qt.DropAction.IgnoreAction

    monkeypatch.setattr(QDrag, "exec", fake_exec)


def test_drag_without_selection_auto_selects(qtbot, five_page_pdf, monkeypatch):
    card, loader, selection_manager, _ = _make_card(qtbot, five_page_pdf, page_index=2)
    selection_manager.select_single(0)
    assert selection_manager.selection == {0}

    _patch_drag_exec(monkeypatch, lambda _drag: None)

    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(card, pos=QPoint(200, 200))

    assert selection_manager.selection == {2}
    loader.close()


def test_mime_data_contains_file_urls(qtbot, five_page_pdf, monkeypatch):
    card, loader, selection_manager, _ = _make_card(qtbot, five_page_pdf, page_index=0)
    selection_manager.select_single(0)
    selection_manager.toggle(2)

    captured_urls: list[Path] = []

    def capture_mime(drag: QDrag) -> None:
        mime = drag.mimeData()
        assert mime is not None
        assert mime.hasFormat(INTERNAL_PAGE_MIME)
        assert decode_page_indices(mime.data(INTERNAL_PAGE_MIME)) == [0, 2]
        urls = mime.urls()
        assert len(urls) == 2
        for url in urls:
            assert url.isLocalFile()
            local_path = Path(url.toLocalFile())
            assert local_path.exists()
            assert local_path.suffix == ".pdf"
            captured_urls.append(local_path)

    _patch_drag_exec(monkeypatch, capture_mime)

    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(card, pos=QPoint(200, 200))

    assert len(captured_urls) == 2
    loader.close()


def test_drag_threshold_respected(qtbot, five_page_pdf, monkeypatch):
    card, loader, _, _ = _make_card(qtbot, five_page_pdf, page_index=0)
    drag_started: list[bool] = []

    def spy_start_drag() -> None:
        drag_started.append(True)

    monkeypatch.setattr(card, "_start_drag", spy_start_drag)

    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(card, pos=QPoint(52, 50))

    assert drag_started == []
    loader.close()


def test_outbound_drag_reflects_edit_model_order(
    qtbot, five_page_pdf, monkeypatch
):
    """Outbound drag extracts pages in logical (edited) order, not source order."""
    import fitz

    card, loader, selection_manager, _ = _make_card(
        qtbot, five_page_pdf, page_index=0
    )
    model = card._model
    assert model is not None
    model.move_pages([3, 4], 0)

    selection_manager.set_page_count(model.logical_count())
    selection_manager.select_single(0)
    selection_manager.toggle(1)

    verified_sources: list[int] = []

    def _page_size(path, page_index: int = 0) -> tuple[float, float]:
        doc = fitz.open(str(path))
        try:
            rect = doc[page_index].rect
            return (float(rect.width), float(rect.height))
        finally:
            doc.close()

    def capture_mime(drag: QDrag) -> None:
        mime = drag.mimeData()
        assert mime is not None
        assert decode_page_indices(mime.data(INTERNAL_PAGE_MIME)) == [0, 1]
        for url, source_index in zip(mime.urls(), [3, 4], strict=True):
            path = Path(url.toLocalFile())
            doc = fitz.open(str(path))
            try:
                assert doc.page_count == 1
                assert _page_size(path) == _page_size(five_page_pdf, source_index)
            finally:
                doc.close()
            verified_sources.append(source_index)

    _patch_drag_exec(monkeypatch, capture_mime)

    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(card, pos=QPoint(200, 200))

    assert verified_sources == [3, 4]

    loader.close()


def test_page_card_drag_encrypted(main_window, tmp_path, monkeypatch, qtbot):
    """Unlock → drag-out uses grid credentials; source unchanged, output openable."""
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = hashlib.sha256(enc.read_bytes()).hexdigest()

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("secret", True),
    )

    main_window.showMinimized()
    main_window._load_pdf(str(enc))
    wait_for_pdf_loaded(qtbot, main_window)
    grid = main_window._thumbnail_grid
    card = grid._cards[0]

    assert card._source_passwords() == grid._source_passwords()
    assert card._source_passwords() is not None

    extracted_ok = {"value": False}

    def capture_mime(drag: QDrag) -> None:
        mime = drag.mimeData()
        assert mime is not None
        urls = mime.urls()
        assert len(urls) == 1
        path = Path(urls[0].toLocalFile())
        assert path.exists()
        # Verify before _start_drag finally cleans drag temps.
        out = fitz.open(str(path))
        try:
            assert out.page_count == 1
            assert not out.needs_pass
        finally:
            out.close()
        extracted_ok["value"] = True

    _patch_drag_exec(monkeypatch, capture_mime)

    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(card, pos=QPoint(200, 200))

    assert extracted_ok["value"]
    assert hashlib.sha256(enc.read_bytes()).hexdigest() == source_hash
