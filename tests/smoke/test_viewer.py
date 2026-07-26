"""Viewer smoke — search, link, and return to grid on a 5-page doc."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtCore import Qt

from pagedrop.core.pdf_service import page_links
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from tests.conftest import RENDER_TIMEOUT_MS, wait_for_pdf_loaded


def _five_page_viewer_pdf(path: Path) -> None:
    """Five pages with searchable text and an internal link on page 1."""
    doc = fitz.open()
    try:
        for i in range(5):
            page = doc.new_page(width=300, height=400)
            page.insert_text((40, 60), f"Smoke page {i} findme", fontsize=14)
        doc[0].insert_link(
            {
                "kind": fitz.LINK_GOTO,
                "from": fitz.Rect(30, 40, 220, 80),
                "page": 3,
                "to": fitz.Point(0, 0),
            }
        )
        doc.save(str(path))
    finally:
        doc.close()


def _active_tab(window: MainWindow) -> PdfTab:
    tab = window._active_tab()
    assert isinstance(tab, PdfTab)
    return tab


def test_smoke_viewer_search_link_return_to_grid(qtbot, tmp_path, isolated_settings):
    path = tmp_path / "viewer_five.pdf"
    _five_page_viewer_pdf(path)

    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()

    window._load_pdf(str(path))
    wait_for_pdf_loaded(qtbot, window)
    tab = _active_tab(window)
    assert tab.edit_model is not None
    assert tab.edit_model.logical_count() == 5
    assert not tab.is_viewer_mode()

    window._open_preview()
    qtbot.waitUntil(
        lambda: tab.is_viewer_mode() and len(tab.viewer_widget._tiles) >= 1,
        timeout=RENDER_TIMEOUT_MS,
    )
    viewer = tab.viewer_widget

    viewer.search("findme")
    qtbot.waitUntil(lambda: viewer.search_hit_count == 5, timeout=RENDER_TIMEOUT_MS)
    viewer.find_next()
    assert viewer._hit_index == 1
    assert viewer.current_page == 1

    links = page_links(tab.edit_model.page_at(0))
    gotos = [link for link in links if link.kind == "goto"]
    assert gotos
    viewer.go_to_page(0)
    viewer._on_link(0, gotos[0])
    assert viewer.current_page == 3

    qtbot.keyClick(viewer, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not tab.is_viewer_mode(), timeout=5000)
    assert tab.content_stack.currentWidget() is tab.thumbnail_grid
    assert window.isVisible()

    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
