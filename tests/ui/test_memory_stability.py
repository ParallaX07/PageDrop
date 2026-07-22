"""Phase G — loader cache eviction + optional quality guidance at scale."""

from __future__ import annotations

from pagedrop.ui.pdf_tab import (
    QUALITY_GUIDANCE_MIN_PAGES,
    QUALITY_GUIDANCE_MIN_ZOOM_PX,
    PdfTab,
)
from pagedrop.ui.settings import set_thumbnail_quality
from pagedrop.ui.theme import DEFAULT_THUMBNAIL_WIDTH
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import wait_for_grid_loaded
from tests.fixtures.generate_fixtures import generate_n_page


def _load_tab(qtbot, pdf_path) -> PdfTab:
    tab = PdfTab(TempManager())
    qtbot.addWidget(tab)
    tab.load_pdf(str(pdf_path))
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)
    return tab


def test_loader_cache_evicts_unused_dropped_sources(qtbot, five_page_pdf, tmp_path):
    other = tmp_path / "other.pdf"
    generate_n_page(other, 2)
    other_path = str(other)
    primary = str(five_page_pdf)

    tab = _load_tab(qtbot, five_page_pdf)
    assert primary in tab._loader_cache

    assert tab.thumbnail_grid.insert_pdf_pages([other_path], drop_index=0)
    tab._sync_dirty_from_model()
    assert other_path in tab._loader_cache
    assert primary in tab._loader_cache

    model = tab.edit_model
    assert model is not None
    drop_indices = [
        i
        for i in range(model.logical_count())
        if model.page_at(i).source_path == other_path
    ]
    assert tab.thumbnail_grid.remove_pages_by_indices(drop_indices)
    tab._sync_dirty_from_model()

    assert other_path not in tab._loader_cache
    assert primary in tab._loader_cache


def test_loader_cache_keep_protects_path_before_insert(qtbot, five_page_pdf, tmp_path):
    other = tmp_path / "pending.pdf"
    generate_n_page(other, 1)
    other_path = str(other)

    tab = _load_tab(qtbot, five_page_pdf)
    # Mimic insert_pdf_pages: open loader before model references the path.
    loader = tab.get_loader(other_path)
    assert other_path in tab._loader_cache
    assert loader.path == other_path


def test_quality_scale_guidance_when_large_and_zoomed(
    qtbot, tmp_path, isolated_settings
):
    big = tmp_path / "big.pdf"
    generate_n_page(big, QUALITY_GUIDANCE_MIN_PAGES)
    tab = _load_tab(qtbot, big)
    tab.set_zoom_level(DEFAULT_THUMBNAIL_WIDTH)

    assert tab.quality_scale_guidance() is None

    tab.set_zoom_level(QUALITY_GUIDANCE_MIN_ZOOM_PX, manual=True)
    tip = tab.quality_scale_guidance()
    assert tip is not None
    assert "Large document at high zoom" in tip
    assert "Thumbnail quality" in tip
    # Once per tab session.
    assert tab.quality_scale_guidance() is None


def test_quality_scale_guidance_low_quality_omits_menu_hint(
    qtbot, tmp_path, isolated_settings
):
    set_thumbnail_quality("low")
    big = tmp_path / "big.pdf"
    generate_n_page(big, QUALITY_GUIDANCE_MIN_PAGES)
    tab = _load_tab(qtbot, big)
    tab.set_zoom_level(QUALITY_GUIDANCE_MIN_ZOOM_PX, manual=True)

    tip = tab.quality_scale_guidance()
    assert tip is not None
    assert "smaller thumbnail size" in tip
    assert "Thumbnail quality" not in tip


def test_quality_guidance_status_on_zoom(main_window, tmp_path, qtbot, isolated_settings):
    big = tmp_path / "big.pdf"
    generate_n_page(big, QUALITY_GUIDANCE_MIN_PAGES)
    with qtbot.waitSignal(
        main_window._thumbnail_grid.rendering_finished, timeout=30000
    ):
        main_window._load_pdf(str(big))

    tab = main_window._active_tab()
    assert tab is not None
    # Autofit / load may already have spent the one-shot tip.
    main_window._on_zoom_requested(DEFAULT_THUMBNAIL_WIDTH)
    tab._quality_guidance_shown = False
    main_window._on_zoom_requested(QUALITY_GUIDANCE_MIN_ZOOM_PX)
    assert "Large document at high zoom" in main_window.statusBar().currentMessage()
