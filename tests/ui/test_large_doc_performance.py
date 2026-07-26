"""Large-document performance regressions — count work, not wall clock."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.pdf_viewer import PdfViewerWidget, ViewerLayout
from pagedrop.ui.thumbnail_grid import (
    RETAIN_WINDOW_ROWS,
    ThumbnailGrid,
)


def _blank_pdf(path: Path, page_count: int) -> None:
    doc = fitz.open()
    try:
        for _ in range(page_count):
            doc.new_page(width=300, height=400)
        doc.save(str(path))
    finally:
        doc.close()


@pytest.fixture
def large_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "large_800.pdf"
    _blank_pdf(path, 800)
    return path


def test_viewer_set_model_avoids_per_page_opens(
    qtbot, large_pdf: Path, monkeypatch
) -> None:
    """Page sizes must come from the open loader — not 800 fitz.open cycles."""
    open_calls = {"n": 0}
    real_open = fitz.open

    def counting_open(*args, **kwargs):
        open_calls["n"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", counting_open)

    loader = PdfLoader(str(large_pdf))
    model = PdfEditModel(str(large_pdf), loader.page_count)
    cache = {loader.path: loader}

    def get_loader(path: str) -> PdfLoader:
        if path not in cache:
            cache[path] = PdfLoader(path)
        return cache[path]

    # PdfLoader already opened once; reset counter around set_model.
    open_calls["n"] = 0
    viewer = PdfViewerWidget()
    qtbot.addWidget(viewer)
    viewer.resize(700, 500)
    viewer.show()
    viewer.set_model(model, get_loader)

    assert len(viewer._page_sizes) == 800
    # Page sizes must not open once-per-page. Layers/attachments open once each.
    assert open_calls["n"] < 10
    qtbot.waitUntil(lambda: not viewer._side_panel_dirty, timeout=5000)
    # Outline may open once more; still never once-per-page.
    assert open_calls["n"] < 20
    loader.close()


def test_viewer_lazy_text_dict_until_selection(
    qtbot, tmp_path: Path
) -> None:
    path = tmp_path / "select.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), "Select me", fontsize=14)
        doc.save(str(path))
    finally:
        doc.close()

    loader = PdfLoader(str(path))
    model = PdfEditModel(str(path), loader.page_count)
    viewer = PdfViewerWidget()
    qtbot.addWidget(viewer)
    viewer.resize(700, 500)
    viewer.show()
    viewer.set_model(model, lambda p: loader)
    qtbot.waitUntil(lambda: len(viewer._tiles) >= 1, timeout=5000)
    qtbot.waitUntil(
        lambda: any(t._text_provider is not None for t in viewer._tiles.values()),
        timeout=5000,
    )
    tile = next(iter(viewer._tiles.values()))
    assert tile._text_dict is None
    tile._sel_start = tile.rect().topLeft().toPointF()
    tile._sel_end = tile.rect().bottomRight().toPointF()
    text = tile._text_in_selection()
    assert tile._text_dict is not None
    assert "Select" in text
    loader.close()


def test_grid_windowed_render_and_retain_bound(qtbot, large_pdf: Path) -> None:
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(500, 400)
    grid.show()
    qtbot.waitExposed(grid, timeout=5000)

    loader = PdfLoader(str(large_pdf))
    with qtbot.waitSignal(grid.rendering_finished, timeout=60000):
        grid.load_pdf(loader)

    assert len(grid._cards) == 800
    rendered = sum(1 for w in grid._page_render_width if w > 0)
    # Must not have rendered the entire 800-page document up front.
    assert rendered < 200
    assert rendered > 0

    with_pixmap = sum(
        1 for card in grid._cards if card._source_pixmap is not None
    )
    cols = max(grid._grid_cols, 1)
    retain_cap = cols * (RETAIN_WINDOW_ROWS + 4) + cols
    assert with_pixmap <= retain_cap

    # Scroll toward the end — retain window must stay bounded.
    bar = grid.verticalScrollBar()
    bar.setValue(bar.maximum())
    qtbot.waitUntil(
        lambda: any(
            i > 700 and grid._page_render_width[i] > 0
            for i in range(len(grid._page_render_width))
        ),
        timeout=30000,
    )
    grid._evict_thumbnails_outside_window()
    with_pixmap = sum(
        1 for card in grid._cards if card._source_pixmap is not None
    )
    assert with_pixmap <= cols * (RETAIN_WINDOW_ROWS + 6) + cols

    loader.close()


def test_loader_page_size_pt_uses_open_doc(large_pdf: Path, monkeypatch) -> None:
    open_calls = {"n": 0}
    real_open = fitz.open

    def counting_open(*args, **kwargs):
        open_calls["n"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", counting_open)
    loader = PdfLoader(str(large_pdf))
    opens_after_init = open_calls["n"]
    for i in range(0, 800, 50):
        w, h = loader.page_size_pt(i)
        assert w > 0 and h > 0
    assert open_calls["n"] == opens_after_init
    loader.close()
