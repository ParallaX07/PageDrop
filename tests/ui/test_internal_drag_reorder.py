"""Phase 13 UI tests — internal drag-and-drop page reorder."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, Qt

from pagedrop.core.drag_mime import INTERNAL_PAGE_MIME, decode_page_indices
from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from tests.conftest import wait_for_grid_loaded


def _load_grid(qtbot, pdf_path) -> ThumbnailGrid:
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(900, 650)
    grid.show()
    loader = PdfLoader(str(pdf_path))
    grid.load_pdf(loader)
    wait_for_grid_loaded(qtbot, grid)
    grid._reflow_grid(force=True)
    return grid


def _source_indices(grid: ThumbnailGrid) -> list[int]:
    assert grid._model is not None
    return [
        grid._model.page_at(i).source_index
        for i in range(grid._model.logical_count())
    ]


def _container_point(grid: ThumbnailGrid, card_index: int, *, left_half: bool) -> QPoint:
    card = grid._cards[card_index]
    x = card.x() + (card.width() // 4 if left_half else 3 * card.width() // 4)
    y = card.y() + card.height() // 2
    return QPoint(x, y)


def test_drop_indicator_index(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)

    assert grid.drop_index_at_pos(_container_point(grid, 0, left_half=True)) == 0
    assert grid.drop_index_at_pos(_container_point(grid, 0, left_half=False)) == 1
    assert grid.drop_index_at_pos(_container_point(grid, 2, left_half=True)) == 2
    assert grid.drop_index_at_pos(_container_point(grid, 2, left_half=False)) == 3

    grid._update_drop_indicator(1)
    assert grid._drop_insertion_index == 1
    assert grid._drop_indicator.isVisible()

    grid._hide_drop_indicator()
    assert grid._drop_insertion_index is None
    qtbot.waitUntil(lambda: not grid._drop_indicator.isVisible(), timeout=1000)


def test_multi_select_internal_move(qtbot, five_page_pdf):
    grid = _load_grid(qtbot, five_page_pdf)

    grid.selection_manager.select_single(2)
    grid.selection_manager.toggle(4)
    assert grid.reorder_pages_by_drop([2, 4], 0)

    assert _source_indices(grid) == [2, 4, 0, 1, 3]
    assert grid.selection_manager.selection == {0, 1}
    assert grid._model is not None
    assert grid._model.is_dirty()
    assert grid._last_clicked_index is None


def test_outbound_drag_still_uses_file_urls(qtbot, five_page_pdf, monkeypatch):
    from PyQt6.QtCore import QPoint as QtPoint
    from PyQt6.QtGui import QDrag

    grid = _load_grid(qtbot, five_page_pdf)
    card = grid._cards[0]
    grid.selection_manager.select_single(0)
    grid.selection_manager.toggle(2)

    captured_urls: list[Path] = []
    captured_internal: list[int] = []

    def capture_mime(drag: QDrag) -> None:
        mime = drag.mimeData()
        assert mime is not None
        assert mime.hasFormat(INTERNAL_PAGE_MIME)
        captured_internal.extend(
            decode_page_indices(mime.data(INTERNAL_PAGE_MIME))
        )
        urls = mime.urls()
        assert len(urls) == 2
        for url in urls:
            assert url.isLocalFile()
            local_path = Path(url.toLocalFile())
            assert local_path.exists()
            assert local_path.suffix == ".pdf"
            captured_urls.append(local_path)

    def fake_exec(self, *args, **kwargs):
        capture_mime(self)
        return Qt.DropAction.IgnoreAction

    monkeypatch.setattr(QDrag, "exec", fake_exec)

    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QtPoint(50, 50))
    qtbot.mouseMove(card, pos=QtPoint(200, 200))

    assert captured_internal == [0, 2]
    assert len(captured_urls) == 2
