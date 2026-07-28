"""Phase 30 — viewer markup toolbar + dirty/undo + Save As persistence."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pagedrop.core.annotations import AnnotationOp, list_annotation_summaries
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.pdf_viewer import AnnotTool
from tests.conftest import RENDER_TIMEOUT_MS, wait_for_pdf_loaded


def _text_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 80), "Markup me", fontsize=14)
        doc.save(str(path))
    finally:
        doc.close()


def _active_tab(window) -> PdfTab:
    tab = window._active_tab()
    assert isinstance(tab, PdfTab)
    return tab


@pytest.fixture
def markup_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "markup.pdf"
    _text_pdf(path)
    return path


def test_annot_tools_and_markup_dirty_undo_save(
    qtbot, main_window, markup_pdf: Path, tmp_path: Path
) -> None:
    window = main_window
    window._load_pdf(str(markup_pdf))
    wait_for_pdf_loaded(qtbot, window)
    tab = _active_tab(window)
    window._open_preview()
    qtbot.waitUntil(lambda: tab.is_viewer_mode(), timeout=RENDER_TIMEOUT_MS)

    viewer = tab.viewer_widget
    assert viewer.annot_tool == AnnotTool.SELECT
    assert hasattr(viewer, "_annot_rail")
    assert not viewer._annot_rail.isHidden()
    assert getattr(viewer, "_annot_bar", None) is None
    viewer._toggle_annot_rail()
    assert viewer._annot_rail_collapsed
    viewer._toggle_annot_rail()
    assert not viewer._annot_rail_collapsed

    for tool in (
        AnnotTool.HIGHLIGHT,
        AnnotTool.UNDERLINE,
        AnnotTool.STRIKEOUT,
        AnnotTool.INK,
        AnnotTool.RECT,
        AnnotTool.CIRCLE,
        AnnotTool.LINE,
        AnnotTool.STAMP,
        AnnotTool.FREETEXT,
        AnnotTool.IMAGE,
        AnnotTool.COMMENT,
        AnnotTool.REDACT,
        AnnotTool.FORM_FILL,
        AnnotTool.FORM_TEXT,
        AnnotTool.FORM_CHECK,
    ):
        viewer.set_annot_tool(tool)
        assert viewer.annot_tool == tool

    assert not tab.is_dirty
    session = tab.markup_session
    session.push_annotation(
        AnnotationOp(kind="highlight", page_index=0, rects=((40, 60, 120, 90),))
    )
    viewer.refresh_markup_overlays()
    viewer.markup_changed.emit()
    qtbot.waitUntil(lambda: tab.is_dirty, timeout=2000)
    assert tab.can_undo_edit()
    assert tab.undo_edit()
    assert not session.is_dirty()

    session.push_annotation(
        AnnotationOp(kind="highlight", page_index=0, rects=((40, 60, 120, 90),))
    )
    viewer.markup_changed.emit()
    qtbot.waitUntil(lambda: tab.is_dirty, timeout=2000)

    out = tmp_path / "marked.pdf"
    from pagedrop.core.pdf_writer import write_pdf

    write_pdf(tab.edit_model, str(out), markup=tab.peek_markup_ops())
    types = [t for _, t, _ in list_annotation_summaries(str(out))]
    assert "Highlight" in types


def test_viewer_markup_undo_redo_via_main_window(
    qtbot, main_window, markup_pdf: Path
) -> None:
    """Enabled Undo/Redo in viewer must undo markup — not no-op on preview guard."""
    window = main_window
    window._load_pdf(str(markup_pdf))
    wait_for_pdf_loaded(qtbot, window)
    tab = _active_tab(window)

    # Grid-edit undo exists, then enter viewer: action must stay disabled (no markup yet).
    tab.thumbnail_grid.selection_manager.set_selection({0})
    assert tab.delete_selected_pages()
    assert tab.edit_model.can_undo()
    window._open_preview()
    qtbot.waitUntil(lambda: tab.is_viewer_mode(), timeout=RENDER_TIMEOUT_MS)
    window._update_undo_redo_actions()
    assert not window._undo_action.isEnabled()
    window._undo()  # must not close viewer / undo grid
    assert tab.is_viewer_mode()
    assert tab.edit_model.can_undo()

    session = tab.markup_session
    session.push_annotation(
        AnnotationOp(kind="highlight", page_index=0, rects=((40, 60, 120, 90),))
    )
    tab.viewer_widget.markup_changed.emit()
    qtbot.waitUntil(lambda: window._undo_action.isEnabled(), timeout=2000)
    assert not window._redo_action.isEnabled()

    window._undo()
    assert not session.can_undo()
    assert session.can_redo()
    assert tab.is_viewer_mode()
    assert window._redo_action.isEnabled()

    window._redo()
    assert session.can_undo()
    assert not session.can_redo()
    assert tab.is_viewer_mode()


def test_text_markup_uses_char_rects_not_drag_box(qtbot) -> None:
    from PyQt6.QtCore import QPointF

    from pagedrop.ui.pdf_viewer import AnnotTool, _PageTile

    tile = _PageTile(0)
    qtbot.addWidget(tile)
    tile.resize(300, 400)
    tile.set_tool(AnnotTool.UNDERLINE)
    tile._page_w = 300.0
    tile._page_h = 400.0
    tile._text_dict = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "spans": [
                            {
                                "text": "Hi",
                                "bbox": (40, 60, 60, 80),
                                "chars": [
                                    {"c": "H", "bbox": (40, 60, 50, 80)},
                                    {"c": "i", "bbox": (50, 60, 60, 80)},
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }
    tile._sel_start = QPointF(42, 70)
    tile._sel_end = QPointF(58, 72)
    rects = tile.text_rects_in_selection()
    assert len(rects) == 1
    assert rects[0][0] <= 40.1
    assert rects[0][2] >= 59.9

    tile._sel_start = QPointF(200, 200)
    tile._sel_end = QPointF(250, 250)
    assert tile._drag_payload() == {"rects": ()}
