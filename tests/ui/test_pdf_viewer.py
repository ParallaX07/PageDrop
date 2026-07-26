"""PDF viewer — MainWindow / PdfTab integration."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QGuiApplication, QKeyEvent, QKeySequence
from PyQt6.QtWidgets import QMessageBox

from pagedrop.core.pdf_service import page_links
from pagedrop.ui.pdf_tab import PdfTab
from tests.conftest import RENDER_TIMEOUT_MS, wait_for_pdf_loaded


def _text_pdf(path: Path, pages: list[str]) -> None:
    doc = fitz.open()
    try:
        for text in pages:
            page = doc.new_page(width=300, height=400)
            page.insert_text((40, 60), text, fontsize=14)
        doc.save(str(path))
    finally:
        doc.close()


def _linked_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        doc.new_page(width=300, height=400)
        doc.new_page(width=300, height=400)
        p0 = doc[0]
        p1 = doc[1]
        p0.insert_text((40, 60), "Go to page two", fontsize=14)
        p1.insert_text((40, 60), "Destination", fontsize=14)
        p0.insert_link(
            {
                "kind": fitz.LINK_GOTO,
                "from": fitz.Rect(30, 40, 200, 80),
                "page": 1,
                "to": fitz.Point(0, 0),
            }
        )
        p0.insert_link(
            {
                "kind": fitz.LINK_URI,
                "from": fitz.Rect(30, 100, 200, 140),
                "uri": "https://example.com/pagedrop-test",
            }
        )
        doc.save(str(path))
    finally:
        doc.close()


def _active_tab(window) -> PdfTab:
    tab = window._active_tab()
    assert isinstance(tab, PdfTab)
    return tab


def _wait_viewer_tiles(qtbot, tab: PdfTab) -> None:
    qtbot.waitUntil(
        lambda: tab.is_viewer_mode() and len(tab.viewer_widget._tiles) >= 1,
        timeout=RENDER_TIMEOUT_MS,
    )


@pytest.fixture
def viewer_text_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "viewer_text.pdf"
    _text_pdf(path, ["Alpha unique", "Bravo unique", "Alpha again"])
    return path


@pytest.fixture
def linked_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "viewer_links.pdf"
    _linked_pdf(path)
    return path


@pytest.fixture
def reorder_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "viewer_reorder.pdf"
    _text_pdf(path, [f"Marker{i}" for i in range(5)])
    return path


def test_toggle_grid_viewer_preserves_tab(main_window, five_page_pdf, qtbot):
    """Grid ↔ viewer toggle keeps the same tab; Esc returns to grid."""
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)

    tab = _active_tab(main_window)
    assert not tab.is_viewer_mode()

    tab.thumbnail_grid.selection_manager.select_single(2)
    main_window._open_preview()
    _wait_viewer_tiles(qtbot, tab)
    assert tab.is_preview_visible()
    assert tab.viewer_widget.current_page == 2
    assert tab.content_stack.currentWidget() is tab.viewer_widget
    main_window._update_preview_status()
    assert main_window.statusBar().currentMessage() == "Page 3 of 5"

    qtbot.keyClick(tab.viewer_widget, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not tab.is_viewer_mode(), timeout=5000)
    assert tab.content_stack.currentWidget() is tab.thumbnail_grid
    assert tab is main_window._active_tab()


def test_search_finds_text_and_navigates_hits(main_window, viewer_text_pdf, qtbot):
    main_window._load_pdf(str(viewer_text_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = _active_tab(main_window)

    main_window._open_preview()
    _wait_viewer_tiles(qtbot, tab)
    viewer = tab.viewer_widget

    viewer.search("Alpha")
    qtbot.waitUntil(lambda: viewer.search_hit_count == 2, timeout=RENDER_TIMEOUT_MS)
    assert viewer._hit_index == 0
    viewer.find_next()
    assert viewer._hit_index == 1
    assert viewer.current_page == 2
    viewer.find_prev()
    assert viewer._hit_index == 0


def test_selection_copy_clipboard(main_window, viewer_text_pdf, qtbot):
    main_window._load_pdf(str(viewer_text_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = _active_tab(main_window)

    main_window._open_preview()
    _wait_viewer_tiles(qtbot, tab)
    viewer = tab.viewer_widget

    qtbot.waitUntil(
        lambda: any(
            t._pixmap is not None and not t._pixmap.isNull()
            for t in viewer._tiles.values()
        ),
        timeout=RENDER_TIMEOUT_MS,
    )
    tile = viewer._tiles[viewer.current_page]
    qtbot.waitUntil(lambda: tile._text_dict is not None, timeout=5000)
    tile._sel_start = tile.rect().topLeft().toPointF()
    tile._sel_end = tile.rect().bottomRight().toPointF()
    tile._selected_text = tile._text_in_selection()
    assert "Alpha" in tile.selected_text() or "unique" in tile.selected_text()

    clipboard = QGuiApplication.clipboard()
    clipboard.clear()
    assert viewer.copy_selection() is True
    assert "Alpha" in clipboard.text() or "unique" in clipboard.text()


def test_internal_link_jumps(main_window, linked_pdf, qtbot):
    main_window._load_pdf(str(linked_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = _active_tab(main_window)
    model = tab.edit_model
    assert model is not None

    main_window._open_preview()
    _wait_viewer_tiles(qtbot, tab)
    viewer = tab.viewer_widget

    links = page_links(model.page_at(0))
    gotos = [link for link in links if link.kind == "goto"]
    assert gotos
    viewer._on_link(0, gotos[0])
    assert viewer.current_page == 1


def test_external_link_confirms(main_window, linked_pdf, qtbot, monkeypatch):
    main_window._load_pdf(str(linked_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = _active_tab(main_window)
    model = tab.edit_model
    assert model is not None

    main_window._open_preview()
    _wait_viewer_tiles(qtbot, tab)
    viewer = tab.viewer_widget

    opened: list[str] = []

    def fake_question(*_args, **_kwargs):
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    monkeypatch.setattr(
        "pagedrop.ui.pdf_viewer.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )

    uris = [link for link in page_links(model.page_at(0)) if link.kind == "uri"]
    assert uris
    viewer._on_link(0, uris[0])
    assert opened == []


def test_shortcuts_guarded_in_viewer_mode(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)

    tab = _active_tab(main_window)
    grid = tab.thumbnail_grid
    grid.selection_manager.select_single(1)
    main_window._open_preview()
    qtbot.waitUntil(lambda: tab.is_viewer_mode(), timeout=5000)

    before_count = tab.edit_model.logical_count()
    before_zoom = grid.thumbnail_width_px
    before_selection = set(grid.selection_manager.selection)

    main_window._select_all_pages()
    assert grid.selection_manager.selection == before_selection

    main_window._delete_selected_pages()
    assert tab.edit_model.logical_count() == before_count

    main_window._move_selected_pages_up()
    assert list(grid.selection_manager.selection) == list(before_selection)

    plus = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Plus,
        Qt.KeyboardModifier.NoModifier,
        "+",
    )
    assert not main_window.eventFilter(main_window, plus)
    assert grid.thumbnail_width_px == before_zoom

    select_all = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_A,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert select_all.matches(QKeySequence.StandardKey.SelectAll)
    assert not main_window.eventFilter(main_window, select_all)
    assert grid.selection_manager.selection == before_selection


def test_reordered_model_viewer_order_matches_grid(main_window, reorder_pdf, qtbot):
    """After reorder, grid labels and viewer logical order follow the model."""
    main_window._load_pdf(str(reorder_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = _active_tab(main_window)
    model = tab.edit_model
    assert model is not None
    grid = tab.thumbnail_grid

    # Move last page to front: source 4 becomes logical 0.
    assert grid.reorder_pages_by_drop([4], 0)
    assert [model.page_at(i).source_index for i in range(5)] == [4, 0, 1, 2, 3]
    for index, card in enumerate(grid._cards):
        assert card.page_index == index
        assert card._page_label.text() == f"Page {index + 1}"

    tab.show_preview_at(0)
    _wait_viewer_tiles(qtbot, tab)
    viewer = tab.viewer_widget
    assert viewer.current_page == 0
    assert model.page_at(viewer.current_page).source_index == 4
    assert viewer._page_label.text() == "Page 1 of 5"

    # Search finds the moved page's text at logical index 0.
    viewer.search("Marker4")
    qtbot.waitUntil(lambda: viewer.search_hit_count == 1, timeout=RENDER_TIMEOUT_MS)
    assert viewer.current_page == 0

    viewer.go_to_page(1)
    assert model.page_at(viewer.current_page).source_index == 0
    assert viewer._page_label.text() == "Page 2 of 5"
