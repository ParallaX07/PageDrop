"""Phase 4 smoke tests — thumbnail grid through MainWindow."""

from __future__ import annotations

import os
import re
import pytest

from pagedrop.ui.main_window import MainWindow
from tests.fixtures.generate_fixtures import generate_n_page


def _page_numbers(cards) -> list[int]:
    numbers = []
    for card in cards:
        match = re.search(r"(\d+)\s*$", card._page_label.text())
        assert match is not None, card._page_label.text()
        numbers.append(int(match.group(1)))
    return numbers


def test_smoke_thumbnail_grid_five_pages(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()

    window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(window._thumbnail_grid.rendering_finished, timeout=30000)

    cards = window._thumbnail_grid._cards
    assert len(cards) == 5
    assert _page_numbers(cards) == [1, 2, 3, 4, 5]

    window.close()


@pytest.mark.skipif(
    not os.environ.get("PAGEDROP_STRESS_PAGES"),
    reason="Set PAGEDROP_STRESS_PAGES=50 to run stress smoke test",
)
def test_smoke_stress_pages(qtbot, pdf_fixtures_dir):
    page_count = int(os.environ["PAGEDROP_STRESS_PAGES"])
    stress_pdf = pdf_fixtures_dir / f"stress_{page_count}.pdf"
    if not stress_pdf.exists():
        generate_n_page(stress_pdf, page_count)

    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()

    window._load_pdf(str(stress_pdf))
    qtbot.waitSignal(window._thumbnail_grid.rendering_finished, timeout=120000)

    assert len(window._thumbnail_grid._cards) == page_count
    assert window.isEnabled()

    window.close()
