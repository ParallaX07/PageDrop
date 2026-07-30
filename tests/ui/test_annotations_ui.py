"""Phase 30 — viewer markup toolbar + dirty/undo + Save As persistence."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog, QToolButton

from pagedrop.core.annotations import AnnotationOp, list_annotation_summaries
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.pdf_viewer import ANNOT_TOOL_ITEMS, AnnotTool
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


def _rail_tool_labels(viewer) -> list[str]:
    host = viewer._annot_tools_host
    return [
        btn.text()
        for btn in host.findChildren(QToolButton)
        if viewer._annot_group.id(btn) >= 0
    ]


@pytest.fixture
def markup_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "markup.pdf"
    _text_pdf(path)
    return path


@pytest.fixture
def accept_markup_color(monkeypatch: pytest.MonkeyPatch):
    """Accept color dialog with a distinct magenta so storage is observable."""

    def _fake_get_color(*_args, **_kwargs) -> QColor:
        return QColor(200, 40, 180)

    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(_fake_get_color))
    return (200 / 255, 40 / 255, 180 / 255)


def test_annot_tools_and_markup_dirty_undo_save(
    qtbot, main_window, markup_pdf: Path, tmp_path: Path, accept_markup_color
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

    for _label, tool in ANNOT_TOOL_ITEMS:
        if tool == AnnotTool.SELECT:
            continue
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


def test_markup_rail_hygiene_no_stamp_field_check_or_color(
    qtbot, main_window, markup_pdf: Path
) -> None:
    window = main_window
    window._load_pdf(str(markup_pdf))
    wait_for_pdf_loaded(qtbot, window)
    tab = _active_tab(window)
    window._open_preview()
    qtbot.waitUntil(lambda: tab.is_viewer_mode(), timeout=RENDER_TIMEOUT_MS)

    viewer = tab.viewer_widget
    labels = _rail_tool_labels(viewer)
    assert "Stamp" not in labels
    assert "Field" not in labels
    assert "Check" not in labels
    assert "Color" not in labels
    assert viewer.findChild(QToolButton, "PdfViewerMarkupColor") is None
    rail_texts = [b.text() for b in viewer._annot_tools_host.findChildren(QToolButton)]
    assert "Apply redaction" not in rail_texts
    # Kept discoverable tools still on the rail.
    for kept in ("Highlight", "Fill", "Redact", "Text", "Ink", "Rect"):
        assert kept in labels
    rail_tools = {tool for _label, tool in ANNOT_TOOL_ITEMS}
    assert AnnotTool.STAMP not in rail_tools
    assert AnnotTool.FORM_TEXT not in rail_tools
    assert AnnotTool.FORM_CHECK not in rail_tools


def test_redact_confirm_cancel_chrome(
    qtbot, main_window, markup_pdf: Path
) -> None:
    """R16: redact gesture is pending until Confirm; Cancel drops the mark."""
    window = main_window
    window._load_pdf(str(markup_pdf))
    wait_for_pdf_loaded(qtbot, window)
    tab = _active_tab(window)
    window._open_preview()
    qtbot.waitUntil(lambda: tab.is_viewer_mode(), timeout=RENDER_TIMEOUT_MS)

    viewer = tab.viewer_widget
    session = tab.markup_session
    assert not session.is_dirty()

    viewer._on_markup_gesture(0, "redact", {"rect": (40.0, 60.0, 120.0, 90.0)})
    assert viewer._pending_redact is not None
    assert viewer._pending_redact.rect == (40.0, 60.0, 120.0, 90.0)
    assert session.redaction_regions() == []
    assert not session.is_dirty()
    assert not viewer._redact_confirm.isHidden()
    assert viewer.findChild(QToolButton, "PdfViewerRedactConfirmBtn") is not None
    assert viewer.findChild(QToolButton, "PdfViewerRedactCancelBtn") is not None

    viewer._cancel_pending_redact(status=True)
    assert viewer._pending_redact is None
    assert session.redaction_regions() == []
    assert viewer._redact_confirm.isHidden()

    viewer._on_markup_gesture(0, "redact", {"rect": (50.0, 70.0, 130.0, 100.0)})
    viewer._confirm_pending_redact()
    assert viewer._pending_redact is None
    regions = session.redaction_regions()
    assert len(regions) == 1
    assert regions[0].rect == (50.0, 70.0, 130.0, 100.0)
    assert session.is_dirty()
    assert viewer._redact_confirm.isHidden()
    qtbot.waitUntil(lambda: tab.is_dirty, timeout=2000)


def test_save_as_with_redaction_uses_verify_path(
    qtbot, main_window, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R16: pending redaction regions go through redact_edit_model(verify=True)."""
    import hashlib

    from PyQt6.QtWidgets import QFileDialog

    from pagedrop.core.annotations import AnnotationOp
    from pagedrop.core.redact import (
        RedactionRegion,
        inspect_redaction_result,
        redact_edit_model,
    )

    secret = "SAVEAS_REDACT_SECRET"
    src = tmp_path / "secret.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        page.insert_text((40, 80), f"Hello {secret} world", fontsize=14)
        doc.save(str(src))
    finally:
        doc.close()
    hits = fitz.open(str(src))
    try:
        r = hits[0].search_for(secret)[0]
        rect = (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
    finally:
        hits.close()
    before = hashlib.sha256(src.read_bytes()).hexdigest()

    window = main_window
    window._load_pdf(str(src))
    wait_for_pdf_loaded(qtbot, window)
    tab = _active_tab(window)
    session = tab.markup_session
    session.push_annotation(
        AnnotationOp(kind="highlight", page_index=0, rects=((40, 100, 120, 130),))
    )
    session.push_redaction(RedactionRegion(0, rect))
    tab._sync_dirty_from_model()
    assert tab.is_dirty

    out = tmp_path / "verified.pdf"
    calls: list[dict] = []
    real_redact = redact_edit_model

    def _spy(*args, **kwargs):
        calls.append(dict(kwargs))
        assert kwargs.get("verify", True) is True
        assert kwargs.get("scope") is not None
        return real_redact(*args, **kwargs)

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(out), "PDF Files (*.pdf)"),
    )
    monkeypatch.setattr("pagedrop.ui.main_window.redact_edit_model", _spy)

    assert window._save_as(tab) is True
    assert len(calls) == 1
    assert out.is_file()
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
    assert inspect_redaction_result(out, absent_text=[secret]).ok
    assert session.redaction_regions() == []
    assert not session.is_dirty()
    assert not tab.is_dirty
    assert tab.edit_model is not None
    assert tab.edit_model.save_path == str(out)


def test_save_as_redaction_verify_fail_keeps_marks(
    qtbot, main_window, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed verify discards output and leaves redaction marks on the tab."""
    from PyQt6.QtWidgets import QFileDialog

    from pagedrop.core.redact import RedactionRegion, RedactionVerifyError

    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        doc.new_page().insert_text((40, 80), "keep me", fontsize=14)
        doc.save(str(src))
    finally:
        doc.close()
    before = src.read_bytes()

    window = main_window
    window._load_pdf(str(src))
    wait_for_pdf_loaded(qtbot, window)
    tab = _active_tab(window)
    session = tab.markup_session
    session.push_redaction(RedactionRegion(0, (40.0, 60.0, 120.0, 90.0)))
    tab._sync_dirty_from_model()
    assert tab.is_dirty

    out = tmp_path / "should_not_remain.pdf"

    def _fail(*_a, **_k):
        raise RedactionVerifyError("simulated verify failure")

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(out), "PDF Files (*.pdf)"),
    )
    monkeypatch.setattr("pagedrop.ui.main_window.redact_edit_model", _fail)

    assert window._save_as(tab) is False
    assert not out.exists()
    assert len(session.redaction_regions()) == 1
    assert tab.is_dirty
    assert src.read_bytes() == before
    assert tab.edit_model is not None
    assert tab.edit_model.save_path is None


def test_save_as_redaction_scope_cancel_aborts(
    qtbot, main_window, markup_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PyQt6.QtWidgets import QFileDialog

    from pagedrop.core.redact import RedactionRegion

    window = main_window
    window._load_pdf(str(markup_pdf))
    wait_for_pdf_loaded(qtbot, window)
    tab = _active_tab(window)
    session = tab.markup_session
    session.push_redaction(RedactionRegion(0, (40.0, 60.0, 120.0, 90.0)))
    tab._sync_dirty_from_model()
    assert tab.is_dirty

    out = tmp_path / "cancelled.pdf"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(out), "PDF Files (*.pdf)"),
    )
    monkeypatch.setattr(
        "pagedrop.ui.main_window.prompt_redaction_scope",
        lambda *_a, **_k: None,
    )

    def _must_not_run(*_a, **_k):
        raise AssertionError("redact_edit_model must not run when scope is cancelled")

    monkeypatch.setattr("pagedrop.ui.main_window.redact_edit_model", _must_not_run)

    assert window._save_as(tab) is False
    assert not out.exists()
    assert len(session.redaction_regions()) == 1
    assert tab.is_dirty


def test_color_on_select_stores_color_cancel_keeps_tool(
    qtbot, main_window, markup_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = main_window
    window._load_pdf(str(markup_pdf))
    wait_for_pdf_loaded(qtbot, window)
    tab = _active_tab(window)
    window._open_preview()
    qtbot.waitUntil(lambda: tab.is_viewer_mode(), timeout=RENDER_TIMEOUT_MS)
    viewer = tab.viewer_widget

    calls: list[str] = []

    def accept(*_a, **_k) -> QColor:
        calls.append("accept")
        return QColor(10, 20, 30)

    def cancel(*_a, **_k) -> QColor:
        calls.append("cancel")
        return QColor()  # invalid → cancelled

    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(accept))
    viewer.set_annot_tool(AnnotTool.HIGHLIGHT)
    assert viewer.annot_tool == AnnotTool.HIGHLIGHT
    assert viewer._markup_color == pytest.approx((10 / 255, 20 / 255, 30 / 255))
    assert calls == ["accept"]

    # Same-tool re-click must not re-prompt.
    viewer.set_annot_tool(AnnotTool.HIGHLIGHT)
    assert calls == ["accept"]

    # Enter a different color-capable tool → re-prompt.
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(accept))
    viewer.set_annot_tool(AnnotTool.INK)
    assert viewer.annot_tool == AnnotTool.INK
    assert calls == ["accept", "accept"]

    # Cancel → stay on Ink; rail check state restored.
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(cancel))
    viewer.set_annot_tool(AnnotTool.RECT)
    assert viewer.annot_tool == AnnotTool.INK
    assert calls == ["accept", "accept", "cancel"]
    viewer._sync_annot_tool_ui()
    for i, (_label, tool) in enumerate(ANNOT_TOOL_ITEMS):
        btn = viewer._annot_group.button(i)
        assert btn is not None
        assert btn.isChecked() == (tool == AnnotTool.INK)


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
