"""Phase 4 unit tests — ThumbnailGrid."""

from __future__ import annotations

from PyQt6.QtWidgets import QProgressBar

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.page_card import PageCard
from pagedrop.ui.thumbnail_grid import ThumbnailGrid


def _all_cards_have_thumbnails(cards) -> bool:
    for card in cards:
        pixmap = card._thumbnail_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return False
    return bool(cards)


def test_load_pdf_creates_cards(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)
    assert len(grid._cards) == 5
    assert all(isinstance(card, PageCard) for card in grid._cards)
    qtbot.waitSignal(grid.rendering_finished, timeout=15000)
    loader.close()


def test_load_pdf_clears_previous(qtbot, one_page_pdf, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)

    loader_a = PdfLoader(str(one_page_pdf))
    loader_b = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader_a)
    assert len(grid._cards) == 1
    qtbot.waitUntil(
        lambda: _all_cards_have_thumbnails(grid._cards),
        timeout=15000,
    )

    grid.load_pdf(loader_b)
    assert len(grid._cards) == 5
    qtbot.waitUntil(
        lambda: _all_cards_have_thumbnails(grid._cards),
        timeout=15000,
    )


def test_page_ready_populates_card(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)
    qtbot.waitUntil(
        lambda: _all_cards_have_thumbnails(grid._cards),
        timeout=15000,
    )

    for card in grid._cards:
        pixmap = card._thumbnail_label.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()

    loader.close()


def test_progress_bar_visible_during_load(qtbot, five_page_pdf):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    progress = QProgressBar()
    progress.hide()

    grid.rendering_started.connect(
        lambda total: (progress.setRange(0, total), progress.show())
    )
    grid.rendering_finished.connect(progress.hide)

    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)
    qtbot.waitUntil(lambda: progress.isVisible(), timeout=5000)
    qtbot.waitSignal(grid.rendering_finished, timeout=15000)
    qtbot.waitUntil(lambda: not progress.isVisible(), timeout=5000)
    loader.close()
