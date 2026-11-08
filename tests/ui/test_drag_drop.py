"""Phase 6 UI tests — drag-and-drop preparation on PageCard."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from pagedrop.core.drag_mime import (
    INTERNAL_PAGE_MIME,
    PAGE_TRANSFER_MIME,
    decode_page_indices,
    decode_page_refs,
)
from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import PdfLoader, PdfPasswordRequiredError
from pagedrop.core.selection_manager import SelectionManager
from pagedrop.ui.page_card import PageCard
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import file_sha256, wait_for_grid_loaded, wait_for_pdf_loaded
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


def test_drag_after_reverse_ctrl_selection_carries_pages_in_page_order(
    qtbot, five_page_pdf, monkeypatch
):
    from PyQt6.QtCore import QPoint
    from pagedrop.ui.thumbnail_grid import ThumbnailGrid

    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(900, 650)
    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)
    wait_for_grid_loaded(qtbot, grid)
    loader.close()
    cards = grid._cards

    for index in (3, 1):
        qtbot.mouseClick(
            cards[index],
            Qt.MouseButton.LeftButton,
            modifier=Qt.KeyboardModifier.ControlModifier,
        )
    assert grid.selection_manager.selection == {1, 3}
    assert (cards[1].selection_rank, cards[3].selection_rank) == (1, 2)

    captured: dict[str, object] = {}

    def capture(drag: QDrag) -> None:
        mime = drag.mimeData()
        assert mime is not None
        captured["indices"] = decode_page_indices(mime.data(INTERNAL_PAGE_MIME))
        assert mime.hasFormat(PAGE_TRANSFER_MIME)
        captured["refs"] = decode_page_refs(mime.data(PAGE_TRANSFER_MIME))
        captured["urls"] = [url.toLocalFile() for url in mime.urls()]

    _patch_drag_exec(monkeypatch, capture)

    qtbot.mousePress(cards[3], Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(cards[3], pos=QPoint(200, 200))

    assert captured["indices"] == [1, 3]
    assert [ref.source_index for ref in captured["refs"]] == [1, 3]
    urls = captured["urls"]
    assert len(urls) == 2
    assert all(Path(url).suffix == ".pdf" and Path(url).exists() for url in urls)
    # Dragging does not reorder or renumber the selection.
    assert grid.selection_manager.selection == {1, 3}
    assert (cards[1].selection_rank, cards[3].selection_rank) == (1, 2)


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
    source_hash = file_sha256(enc)

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
    assert file_sha256(enc) == source_hash


def test_drag_temp_files_survive_after_drag_returns(qtbot, five_page_pdf, monkeypatch):
    """A drop target may read the file:// URLs after exec() returns."""
    source_hash = file_sha256(five_page_pdf)
    card, loader, selection_manager, temp_manager = _make_card(
        qtbot, five_page_pdf, page_index=0
    )
    selection_manager.select_single(0)
    selection_manager.toggle(1)
    dropped: list[Path] = []

    def capture(drag: QDrag) -> None:
        dropped.extend(Path(url.toLocalFile()) for url in drag.mimeData().urls())

    _patch_drag_exec(monkeypatch, capture)
    try:
        qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        qtbot.mouseMove(card, pos=QPoint(200, 200))

        assert len(dropped) == 2
        assert all(path.is_file() for path in dropped)
        assert all(path != five_page_pdf for path in dropped)
        assert file_sha256(five_page_pdf) == source_hash
    finally:
        loader.close()
        temp_manager.cleanup()


def test_drag_dropped_inside_the_app_removes_its_files(
    qtbot, five_page_pdf, monkeypatch
):
    card, loader, selection_manager, temp_manager = _make_card(
        qtbot, five_page_pdf, page_index=0
    )
    selection_manager.select_single(0)
    dropped: list[Path] = []

    def capture(drag: QDrag) -> None:
        dropped.extend(Path(url.toLocalFile()) for url in drag.mimeData().urls())
        assert all(path.is_file() for path in dropped)

    _patch_drag_exec(monkeypatch, capture)
    monkeypatch.setattr(QDrag, "target", lambda self: card)
    try:
        qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        qtbot.mouseMove(card, pos=QPoint(200, 200))

        assert len(dropped) == 1
        assert not dropped[0].exists()
        assert list(temp_manager.get_dir().glob("drag_*")) == []
    finally:
        loader.close()
        temp_manager.cleanup()


def test_drag_with_no_target_keeps_its_files(qtbot, five_page_pdf, monkeypatch):
    card, loader, selection_manager, temp_manager = _make_card(
        qtbot, five_page_pdf, page_index=0
    )
    selection_manager.select_single(0)
    dropped: list[Path] = []
    _patch_drag_exec(
        monkeypatch,
        lambda drag: dropped.extend(
            Path(url.toLocalFile()) for url in drag.mimeData().urls()
        ),
    )
    monkeypatch.setattr(QDrag, "target", lambda self: None)
    try:
        qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        qtbot.mouseMove(card, pos=QPoint(200, 200))

        assert len(dropped) == 1
        assert dropped[0].is_file()
    finally:
        loader.close()
        temp_manager.cleanup()


def test_deleted_drag_counts_as_no_target(qtbot, five_page_pdf, monkeypatch):
    card, loader, selection_manager, temp_manager = _make_card(
        qtbot, five_page_pdf, page_index=0
    )
    selection_manager.select_single(0)
    dropped: list[Path] = []
    restored: list[bool] = []
    card._restore_document_status = lambda: restored.append(True)

    def target_of_freed_drag(self):
        raise RuntimeError("wrapped C/C++ object of type QDrag has been deleted")

    real_isdeleted = sip.isdeleted
    monkeypatch.setattr(
        sip, "isdeleted", lambda obj: isinstance(obj, QDrag) or real_isdeleted(obj)
    )
    monkeypatch.setattr(QDrag, "target", target_of_freed_drag)
    _patch_drag_exec(
        monkeypatch,
        lambda drag: dropped.extend(
            Path(url.toLocalFile()) for url in drag.mimeData().urls()
        ),
    )
    try:
        qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        qtbot.mouseMove(card, pos=QPoint(200, 200))

        assert len(dropped) == 1
        assert dropped[0].is_file()
        assert restored == [True]
    finally:
        loader.close()
        temp_manager.cleanup()


@pytest.mark.parametrize(
    "error",
    [OSError("disk full"), RuntimeError("boom"), PdfPasswordRequiredError("locked")],
)
def test_failed_drag_extract_removes_partial_output(
    qtbot, five_page_pdf, monkeypatch, error
):
    source_hash = file_sha256(five_page_pdf)
    card, loader, _, temp_manager = _make_card(qtbot, five_page_pdf, page_index=0)
    shown: list[str] = []

    def partial_then_fail(refs, output_dir, base_name, **kwargs):
        (output_dir / f"{base_name}_page_0001.pdf").write_bytes(b"partial")
        raise error

    monkeypatch.setattr("pagedrop.ui.page_card.extract_page_refs_to_files", partial_then_fail)
    monkeypatch.setattr(
        QMessageBox, "critical", lambda _parent, _title, text: shown.append(text)
    )
    dragged: list[bool] = []
    _patch_drag_exec(monkeypatch, lambda _drag: dragged.append(True))
    try:
        qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        qtbot.mouseMove(card, pos=QPoint(200, 200))

        assert dragged == []
        assert len(shown) == 1 and str(error) in shown[0]
        assert list(temp_manager.get_dir().glob("drag_*")) == []
        assert file_sha256(five_page_pdf) == source_hash
    finally:
        loader.close()
        temp_manager.cleanup()
