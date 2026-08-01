"""Phase 14 smoke tests — inbound PDF drop inserts pages at the drop index."""

from __future__ import annotations

from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import RENDER_TIMEOUT_MS, wait_for_grid_loaded
from tests.fixtures.generate_fixtures import generate_n_page


def test_smoke_inbound_drop_between_pages(qtbot, five_page_pdf, tmp_path):
    """Drag B.pdf (3 pages) between pages 2 and 3; verify order and thumbnails."""
    b_pdf = tmp_path / "B.pdf"
    generate_n_page(b_pdf, 3)

    tab = PdfTab(TempManager())
    qtbot.addWidget(tab)
    tab.resize(900, 650)
    tab.show()
    tab.load_pdf(str(five_page_pdf))

    grid = tab.thumbnail_grid
    wait_for_grid_loaded(qtbot, grid)
    grid._reflow_grid(force=True)

    assert grid.insert_pdf_pages([str(b_pdf)], drop_index=2)
    assert tab.is_dirty

    model = tab.edit_model
    assert model is not None
    assert model.logical_count() == 8

    primary = str(five_page_pdf)
    expected = [
        (primary, 0),
        (primary, 1),
        (str(b_pdf), 0),
        (str(b_pdf), 1),
        (str(b_pdf), 2),
        (primary, 2),
        (primary, 3),
        (primary, 4),
    ]
    actual = [
        (model.page_at(i).source_path, model.page_at(i).source_index)
        for i in range(model.logical_count())
    ]
    assert actual == expected

    wait_for_grid_loaded(qtbot, grid)
    assert len(grid._cards) == 8
    # 8 pages fit the retain window on this fixture — wait for pixmaps, not
    # only pool-idle (MetaCall can lag the worker return under xdist load).
    qtbot.waitUntil(
        lambda: all(
            card._source_pixmap is not None and not card._source_pixmap.isNull()
            for card in grid._cards
        ),
        timeout=RENDER_TIMEOUT_MS,
    )
