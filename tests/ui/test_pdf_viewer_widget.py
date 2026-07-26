"""Focused checks for the PDF viewer widget + pdf_service."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QMessageBox

from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.core.pdf_service import (
    extract_attachment,
    logical_index_for_source,
    outline_for_paths,
    page_links,
    render_ref_png,
    search_model,
)
from pagedrop.ui.pdf_viewer import PdfViewerWidget, ViewerLayout, ZoomMode


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
        doc.set_toc([[1, "Chapter one", 1], [1, "Chapter two", 2]])
        doc.embfile_add("note.txt", b"hello attachment")
        doc.save(str(path))
    finally:
        doc.close()


@pytest.fixture
def viewer_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "viewer_text.pdf"
    _text_pdf(path, ["Alpha unique", "Bravo unique", "Alpha again"])
    return path


@pytest.fixture
def linked_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "viewer_links.pdf"
    _linked_pdf(path)
    return path


def _bind_viewer(qtbot, path: Path) -> tuple[PdfViewerWidget, PdfEditModel, PdfLoader]:
    loader = PdfLoader(str(path))
    model = PdfEditModel(str(path), loader.page_count)
    cache = {loader.path: loader}

    def get_loader(p: str) -> PdfLoader:
        if p not in cache:
            cache[p] = PdfLoader(p)
        return cache[p]

    viewer = PdfViewerWidget()
    qtbot.addWidget(viewer)
    viewer.resize(900, 700)
    viewer.show()
    viewer.set_model(model, get_loader)
    qtbot.waitUntil(lambda: len(viewer._tiles) >= 1, timeout=5000)
    return viewer, model, loader


def test_pdf_service_search_and_render(viewer_pdf: Path) -> None:
    model = PdfEditModel(str(viewer_pdf), 3)
    hits = search_model(model, "Alpha")
    assert len(hits) == 2
    assert hits[0].logical_page == 0
    png = render_ref_png(model.page_at(0), 400)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_viewer_layouts_and_zoom(qtbot, viewer_pdf: Path) -> None:
    viewer, _model, loader = _bind_viewer(qtbot, viewer_pdf)
    try:
        assert viewer.layout_mode == ViewerLayout.CONTINUOUS
        viewer.set_layout_mode(ViewerLayout.SINGLE)
        assert list(viewer._tiles) == [0]
        viewer.set_layout_mode(ViewerLayout.SPREAD)
        assert sorted(viewer._tiles) == [0, 1]
        viewer.set_zoom_mode(ZoomMode.PERCENT, 150)
        assert viewer.zoom_mode == ZoomMode.PERCENT
        viewer.reset_zoom()
        assert viewer.zoom_mode == ZoomMode.FIT_WIDTH
    finally:
        loader.close()


def test_viewer_search_next_prev(qtbot, viewer_pdf: Path) -> None:
    viewer, _model, loader = _bind_viewer(qtbot, viewer_pdf)
    try:
        viewer.search("Alpha")
        qtbot.waitUntil(lambda: viewer.search_hit_count == 2, timeout=5000)
        assert viewer._hit_index == 0
        viewer.find_next()
        assert viewer._hit_index == 1
        assert viewer.current_page == 2
        viewer.find_prev()
        assert viewer._hit_index == 0
    finally:
        loader.close()


def test_viewer_selection_copy(qtbot, viewer_pdf: Path) -> None:
    viewer, _model, loader = _bind_viewer(qtbot, viewer_pdf)
    try:
        qtbot.waitUntil(
            lambda: any(
                t._pixmap is not None and not t._pixmap.isNull()
                for t in viewer._tiles.values()
            ),
            timeout=8000,
        )
        tile = viewer._tiles[viewer.current_page]
        qtbot.waitUntil(lambda: tile._text_dict is not None, timeout=5000)
        # Force selection geometry covering the text area.
        tile._sel_start = tile.rect().topLeft().toPointF()
        tile._sel_end = tile.rect().bottomRight().toPointF()
        tile._selected_text = tile._text_in_selection()
        assert "Alpha" in tile.selected_text() or "unique" in tile.selected_text()
        assert viewer.copy_selection() is True
    finally:
        loader.close()


def test_internal_link_jumps(qtbot, linked_pdf: Path) -> None:
    viewer, model, loader = _bind_viewer(qtbot, linked_pdf)
    try:
        ref = model.page_at(0)
        links = page_links(ref)
        gotos = [link for link in links if link.kind == "goto"]
        assert gotos
        viewer._on_link(0, gotos[0])
        assert viewer.current_page == 1
    finally:
        loader.close()


def test_external_link_confirms(qtbot, linked_pdf: Path, monkeypatch) -> None:
    viewer, model, loader = _bind_viewer(qtbot, linked_pdf)
    opened: list[str] = []

    def fake_question(*_args, **_kwargs):
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    monkeypatch.setattr(
        "pagedrop.ui.pdf_viewer.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )
    try:
        links = page_links(model.page_at(0))
        uris = [link for link in links if link.kind == "uri"]
        assert uris
        viewer._on_link(0, uris[0])
        assert opened == []
    finally:
        loader.close()


def test_outline_and_attachment_extract(qtbot, linked_pdf: Path, tmp_path: Path) -> None:
    viewer, model, loader = _bind_viewer(qtbot, linked_pdf)
    try:
        items = outline_for_paths([str(linked_pdf)])
        assert len(items) >= 2
        assert viewer._outline.topLevelItemCount() >= 1
        out = extract_attachment(str(linked_pdf), "note.txt", tmp_path)
        assert out.read_bytes() == b"hello attachment"
        logical = logical_index_for_source(model, str(linked_pdf), 1)
        assert logical == 1
        viewer.go_to_page(logical)
        assert viewer.current_page == 1
    finally:
        loader.close()


def test_keyboard_page_and_escape(qtbot, viewer_pdf: Path) -> None:
    viewer, _model, loader = _bind_viewer(qtbot, viewer_pdf)
    closed = {"ok": False}
    viewer.closed.connect(lambda: closed.__setitem__("ok", True))
    try:
        viewer.set_layout_mode(ViewerLayout.SINGLE)
        viewer.go_to_page(0)
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_PageDown,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.keyPressEvent(event)
        assert viewer.current_page == 1
        esc = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.keyPressEvent(esc)
        assert closed["ok"] is True
        assert viewer._tiles[1].accessibleName() == "Page 2"
    finally:
        loader.close()


def test_continuous_virtualizes_tiles(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "many.pdf"
    _text_pdf(path, [f"Page {i}" for i in range(40)])
    viewer, _model, loader = _bind_viewer(qtbot, path)
    try:
        viewer.set_layout_mode(ViewerLayout.CONTINUOUS)
        viewer.resize(700, 500)
        viewer._sync_continuous_tiles()
        # Must not mount all 40 page tiles at once.
        assert 0 < len(viewer._tiles) < 40
        assert viewer._canvas.minimumHeight() > 1000
    finally:
        loader.close()
