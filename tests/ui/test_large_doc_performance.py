"""Large-document performance regressions — count work, not wall clock."""

from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import QObject, QRunnable, QTimer, pyqtSignal

from pagedrop.core import pdf_service
from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.core.pdf_service import doc_cache_size, invalidate_doc_cache
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


def test_viewer_scroll_search_hits_doc_cache(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scroll + search on a multi-page doc must reuse pdf_service's path cache.

    Without the cache, every paint/search would ``fitz.open`` the same path.
    """
    path = tmp_path / "scroll_search.pdf"
    doc = fitz.open()
    try:
        for i in range(40):
            page = doc.new_page(width=300, height=400)
            page.insert_text((40, 60), f"Page {i} findme", fontsize=14)
        doc.save(str(path))
    finally:
        doc.close()

    invalidate_doc_cache()
    open_calls = {"n": 0}
    real_open = pdf_service._open

    def counting_open(path_arg: str, password: str | None = None) -> fitz.Document:
        open_calls["n"] += 1
        return real_open(path_arg, password)

    monkeypatch.setattr(pdf_service, "_open", counting_open)

    loader = PdfLoader(str(path))
    model = PdfEditModel(str(path), loader.page_count)
    cache = {loader.path: loader}

    def get_loader(p: str) -> PdfLoader:
        if p not in cache:
            cache[p] = PdfLoader(p)
        return cache[p]

    viewer = PdfViewerWidget()
    qtbot.addWidget(viewer)
    viewer.resize(700, 500)
    viewer.show()
    viewer.set_layout_mode(ViewerLayout.CONTINUOUS)
    viewer.set_model(model, get_loader)
    qtbot.waitUntil(lambda: len(viewer._tiles) >= 1, timeout=5000)
    qtbot.waitUntil(lambda: not viewer._side_panel_dirty, timeout=5000)
    qtbot.waitUntil(
        lambda: any(
            t._pixmap is not None and not t._pixmap.isNull()
            for t in viewer._tiles.values()
        ),
        timeout=8000,
    )
    assert doc_cache_size() == 1
    opens_warm = open_calls["n"]
    assert opens_warm >= 1

    # Scroll through several viewports — each paint must cache-hit, not reopen.
    bar = viewer._scroll.verticalScrollBar()
    for frac in (0.25, 0.5, 0.75, 1.0):
        bar.setValue(int(bar.maximum() * frac))
        viewer._sync_continuous_tiles()
        viewer._render_visible()
        qtbot.waitUntil(
            lambda: viewer._pool.activeThreadCount() == 0, timeout=10000
        )
    assert open_calls["n"] == opens_warm
    assert doc_cache_size() == 1

    viewer.search("findme")
    qtbot.waitUntil(lambda: viewer.search_hit_count == 40, timeout=10000)
    viewer.find_next()
    assert viewer._hit_index == 1
    # Search walks every page via the shared cache — still one open.
    assert open_calls["n"] == opens_warm
    assert doc_cache_size() == 1

    loader.close()
    invalidate_doc_cache()


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


def test_scroll_skips_eviction_within_row_stride(qtbot, large_pdf: Path) -> None:
    """O17-i: sub-row scroll ticks must not re-walk all cards for eviction.

    Measured 2026-08-01 on a 2k-page blank fixture (offscreen, 500×400):
    steady ``_evict_thumbnails_outside_window`` ~0.5–0.8ms/tick; full
    ``_on_scroll_changed`` ~1.6ms mean across synthetic ticks. Skip when
    |Δy| < row_stride cuts scroll-path mean ~3× while retain still bounds
    pixmap memory after a ≥1-row move.
    """
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(500, 400)
    grid.show()
    qtbot.waitExposed(grid, timeout=5000)

    loader = PdfLoader(str(large_pdf))
    grid.load_pdf(loader)
    qtbot.waitUntil(lambda: len(grid._cards) == 800, timeout=60000)
    qtbot.waitUntil(lambda: not grid._pending_card_indices, timeout=5000)

    calls = {"n": 0}
    real_evict = grid._evict_thumbnails_outside_window

    def counting_evict() -> None:
        calls["n"] += 1
        real_evict()

    grid._evict_thumbnails_outside_window = counting_evict  # type: ignore[method-assign]

    bar = grid.verticalScrollBar()
    assert bar.maximum() > 0
    # Establish baseline eviction at the current scroll position.
    grid._last_evict_scroll_y = None
    grid._on_scroll_changed(bar.value())
    assert calls["n"] == 1
    assert grid._last_evict_scroll_y == bar.value()

    row_stride = grid._row_stride_px()
    start = bar.value()
    # Stay within one row of the last eviction — must not re-evict.
    micro = max(1, row_stride // 4)
    for delta in range(micro, row_stride, micro):
        bar.setValue(start + delta)
    assert calls["n"] == 1

    # Crossing one row from the last eviction must run eviction again.
    bar.setValue(start + row_stride)
    assert calls["n"] == 2

    # Memory still bounded after the stride-triggered eviction.
    cols = max(grid._grid_cols, 1)
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


def test_prepare_yields_event_loop(qtbot, large_pdf: Path, monkeypatch) -> None:
    """Card creation must yield so the event loop can run mid-prepare."""
    import pagedrop.ui.thumbnail_grid as tg

    monkeypatch.setattr(tg, "CARD_CREATE_BATCH", 8)
    monkeypatch.setattr(tg, "CARD_CREATE_BUDGET_MS", 1)

    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(500, 400)
    grid.show()
    qtbot.waitExposed(grid, timeout=5000)

    yielded = {"ok": False}

    def _mark_yielded() -> None:
        # Must fire while cards are still being created.
        if grid._pending_card_indices or len(grid._cards) < 800:
            yielded["ok"] = True

    loader = PdfLoader(str(large_pdf))
    grid.load_pdf(loader)
    QTimer.singleShot(0, _mark_yielded)
    qtbot.waitUntil(lambda: len(grid._cards) == 800, timeout=60000)
    qtbot.waitUntil(lambda: not grid._pending_card_indices, timeout=5000)
    assert yielded["ok"]
    # Incremental layout: every card is in the grid without a final cliff rebuild.
    assert grid._layout.count() == 800
    loader.close()


def test_incremental_layout_appends_without_full_rebuild(
    qtbot, large_pdf: Path, monkeypatch
) -> None:
    """After the first batch, later cards are appended — not a full takeAt rebuild."""
    import pagedrop.ui.thumbnail_grid as tg

    monkeypatch.setattr(tg, "CARD_CREATE_BATCH", 10)
    monkeypatch.setattr(tg, "CARD_CREATE_BUDGET_MS", 50)

    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(500, 400)
    grid.show()
    qtbot.waitExposed(grid, timeout=5000)

    rebuilds = {"n": 0}
    real_reflow = grid._reflow_grid

    def counting_reflow(*, force: bool = False) -> None:
        if force:
            rebuilds["n"] += 1
        real_reflow(force=force)

    monkeypatch.setattr(grid, "_reflow_grid", counting_reflow)

    loader = PdfLoader(str(large_pdf))
    grid.load_pdf(loader)
    qtbot.waitUntil(lambda: len(grid._cards) >= 10, timeout=10000)
    rebuilds_after_first = rebuilds["n"]
    assert rebuilds_after_first >= 1

    qtbot.waitUntil(lambda: len(grid._cards) == 800, timeout=60000)
    qtbot.waitUntil(lambda: not grid._pending_card_indices, timeout=5000)
    # Later batches must append; force-reflow count must not grow per batch.
    assert rebuilds["n"] == rebuilds_after_first
    assert grid._layout.count() == 800
    loader.close()


def test_cancel_rendering_does_not_block(qtbot) -> None:
    """cancel_rendering must return immediately even with a long-running pool job."""

    class _SlowSignals(QObject):
        page_ready = pyqtSignal(int, int, bytes)
        finished = pyqtSignal(int)
        error = pyqtSignal(int, str)

    class _SlowWorker(QRunnable):
        def __init__(self) -> None:
            super().__init__()
            self.signals = _SlowSignals()
            self.setAutoDelete(True)

        def run(self) -> None:
            time.sleep(2.0)
            self.signals.finished.emit(0)

    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    worker = _SlowWorker()
    # Mimic ThumbnailWorker signal ownership so cancel orphans them safely.
    grid._worker_signals.append(worker.signals)  # type: ignore[arg-type]
    grid._render_pool.start(worker)

    t0 = time.monotonic()
    grid.cancel_rendering()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5
    # Pool may still be finishing asynchronously — wait so teardown is clean.
    qtbot.waitUntil(lambda: grid._render_pool.waitForDone(0), timeout=5000)


def test_shift_range_select_diff_chrome_only(qtbot, large_pdf: Path) -> None:
    """Select-all / range must not re-style every card — only flipped indices."""
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(500, 400)
    grid.show()
    qtbot.waitExposed(grid, timeout=5000)

    loader = PdfLoader(str(large_pdf))
    grid.load_pdf(loader)
    qtbot.waitUntil(lambda: len(grid._cards) == 800, timeout=60000)
    qtbot.waitUntil(lambda: not grid._pending_card_indices, timeout=5000)

    calls = {"n": 0}
    for card in grid._cards:
        real = card.set_selected

        def counting_set_selected(selected: bool, *, _real=real) -> None:
            calls["n"] += 1
            _real(selected)

        card.set_selected = counting_set_selected  # type: ignore[method-assign]

    calls["n"] = 0
    grid.selection_manager.select_range(0, 99)
    # Diff chrome: empty → 100 selected → 100 set_selected, not 800.
    assert calls["n"] == 100
    assert {c.page_index for c in grid._cards if c.is_selected} == set(range(100))

    calls["n"] = 0
    grid.selection_manager.select_range(0, 49)
    # 50 deselected only.
    assert calls["n"] == 50
    assert {c.page_index for c in grid._cards if c.is_selected} == set(range(50))
    loader.close()


def test_zoom_defers_offscreen_layout(qtbot, large_pdf: Path, monkeypatch) -> None:
    """Zoom applies full card layout to visible pages only; off-screen stays pending."""
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(500, 400)
    grid.show()
    qtbot.waitExposed(grid, timeout=5000)

    loader = PdfLoader(str(large_pdf))
    grid.load_pdf(loader)
    qtbot.waitUntil(lambda: len(grid._cards) == 800, timeout=60000)
    qtbot.waitUntil(lambda: not grid._pending_card_indices, timeout=5000)
    # Drain any leftover deferred layout from load/autofit.
    grid._deferred_layout_timer.stop()
    grid._pending_layout_indices.clear()

    monkeypatch.setattr(grid, "_get_visible_page_indices", lambda **_: list(range(12)))

    layout_calls: list[int] = []
    for index, card in enumerate(grid._cards):
        real = card.apply_layout_width

        def counting_apply(*, _real=real, _i=index) -> None:
            layout_calls.append(_i)
            _real()

        card.apply_layout_width = counting_apply  # type: ignore[method-assign]

    off = grid._cards[200]
    old_width = off.width()
    target = grid.thumbnail_width_px + 40
    grid.set_thumbnail_zoom(target)
    # Don't let the idle batch run before we inspect pending state.
    grid._deferred_layout_timer.stop()

    # Visible cards get layout during set_card_width; off-screen must not.
    assert all(i < 12 for i in layout_calls)
    assert len(grid._pending_layout_indices) == 800 - 12
    assert 200 in grid._pending_layout_indices
    assert off._card_width == grid._card_width
    assert off.width() == old_width
    loader.close()
