"""Page operations — duplicate, rotate, extract to tab/window."""

from __future__ import annotations

import fitz

from pagedrop.core.drag_mime import decode_page_refs, encode_page_refs
from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_loader import render_page_png
from pagedrop.ui.window_manager import WindowManager


def test_page_ref_rotation_mime_roundtrip():
    refs = [
        PageRef("/tmp/a.pdf", 0, 90),
        PageRef("/tmp/b.pdf", 2, 270),
    ]
    assert decode_page_refs(encode_page_refs(refs)) == refs


def test_legacy_mime_defaults_rotation_to_zero():
    payload = b'[{"source_path":"/tmp/a.pdf","source_index":1}]'
    assert decode_page_refs(payload) == [PageRef("/tmp/a.pdf", 1, 0)]


def test_render_page_png_accepts_rotation(tmp_path):
    path = tmp_path / "landscape.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=100)
        doc.save(str(path))
    finally:
        doc.close()

    doc = fitz.open(str(path))
    try:
        base = render_page_png(doc, 0, width_px=80, rotation=0)
        rotated = render_page_png(doc, 0, width_px=80, rotation=90)
        base_w = int.from_bytes(base[16:20], "big")
        base_h = int.from_bytes(base[20:24], "big")
        rot_w = int.from_bytes(rotated[16:20], "big")
        rot_h = int.from_bytes(rotated[20:24], "big")
        assert base_w > base_h
        assert rot_h > rot_w
    finally:
        doc.close()


def test_duplicate_selected_pages(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    tab = main_window._active_tab()
    grid = tab.thumbnail_grid
    grid.selection_manager.set_selection({1, 3})

    main_window._duplicate_selected_pages()

    model = tab.edit_model
    assert model is not None
    assert model.logical_count() == 7
    # Insert after last selected (index 3) → duplicates land before original page 5.
    assert [model.page_at(i).source_index for i in range(7)] == [0, 1, 2, 3, 1, 3, 4]
    assert grid.selection_manager.selection == {4, 5}
    assert model.is_dirty()


def test_rotate_selected_pages_updates_ref_and_indicator(
    main_window, five_page_pdf, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    tab = main_window._active_tab()
    grid = tab.thumbnail_grid
    grid.selection_manager.select_single(2)

    main_window._rotate_selected_pages(90)

    assert tab.edit_model.page_at(2).rotation == 90
    overlay = grid._cards[2]._rotation_overlay
    assert not overlay.isHidden()
    assert overlay.text() == "90°"
    assert tab.edit_model.is_dirty()
    # Stale width cache must be cleared so the thumbnail pixels re-render.
    assert grid._page_render_width[2] == 0


def test_extract_selected_to_new_tab(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    source = main_window._active_tab()
    source.thumbnail_grid.selection_manager.set_selection({0, 2})
    assert main_window._tab_manager.count() == 1

    main_window._extract_selected_to_new_tab()

    assert main_window._tab_manager.count() == 2
    new_tab = main_window._active_tab()
    assert new_tab is not source
    assert new_tab.edit_model is not None
    assert new_tab.edit_model.logical_count() == 2
    assert [
        (r.source_index, r.rotation) for r in (
            new_tab.edit_model.page_at(0),
            new_tab.edit_model.page_at(1),
        )
    ] == [(0, 0), (2, 0)]
    # Source document unchanged (copy, not move).
    assert source.edit_model.logical_count() == 5


def test_extract_selected_to_new_window(qapp, five_page_pdf, qtbot):
    manager = WindowManager(qapp)
    main_window = manager.open_new_window()
    qtbot.addWidget(main_window)

    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitSignal(main_window._thumbnail_grid.rendering_finished, timeout=15000)

    main_window._active_tab().thumbnail_grid.selection_manager.set_selection({1, 4})
    main_window._rotate_selected_pages(90)

    before = len(manager.windows)
    main_window._extract_selected_to_new_window()
    assert len(manager.windows) == before + 1

    other = next(w for w in manager.windows if w is not main_window)
    qtbot.addWidget(other)
    tab = other._active_tab()
    assert tab is not None and tab.edit_model is not None
    assert tab.edit_model.logical_count() == 2
    assert tab.edit_model.page_at(0).source_index == 1
    assert tab.edit_model.page_at(0).rotation == 90
    assert tab.edit_model.page_at(1).source_index == 4
