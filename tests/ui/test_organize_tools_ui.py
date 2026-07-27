"""Phase 24 organize Tools hub UI — tiles, prefill, overwrite guards."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core.jobs import JobSpec, SourceOverwriteError
from pagedrop.ui.organize_tools import (
    ORGANIZE_TOOL_IDS,
    editor_pdf_context,
    ensure_organize_runner,
)
from pagedrop.ui.tools_window import TOOL_CATALOGUE, ToolsWindow
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import RENDER_TIMEOUT_MS


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_organize_tiles_present_and_wired():
    organize = [e for e in TOOL_CATALOGUE if e.category == "Organize"]
    ids = {e.id for e in organize}
    assert "merge" in ids
    assert ORGANIZE_TOOL_IDS <= ids
    for entry in organize:
        if entry.id == "merge":
            assert entry.action == "merge"
            continue
        assert entry.action == "organize"
        assert not entry.coming_soon


def test_split_prefills_from_tab_selection(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    tab = main_window._active_tab()
    assert tab is not None
    qtbot.waitUntil(
        lambda: tab.edit_model is not None and tab.edit_model.logical_count() == 5,
        timeout=RENDER_TIMEOUT_MS,
    )

    tab.thumbnail_grid.selection_manager.set_selection({1, 2, 4})
    ctx = editor_pdf_context(main_window)
    assert ctx is not None
    assert Path(ctx.path).resolve() == five_page_pdf.resolve()
    assert ctx.range_prefill == "2-3,5"


def test_reverse_job_via_tools_runner_never_overwrites_source(tmp_path: Path):
    src = tmp_path / "doc.pdf"
    out = tmp_path / "doc_reversed.pdf"
    doc = fitz.open()
    try:
        for text in ("A", "B", "C"):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), text, fontsize=18)
        doc.save(str(src))
    finally:
        doc.close()
    source_hash = _file_hash(src)

    temp = TempManager()
    try:
        runner = ensure_organize_runner(temp)
        with pytest.raises(SourceOverwriteError):
            runner.run(JobSpec.create("reverse", inputs=[src], output=src))

        result = runner.run(JobSpec.create("reverse", inputs=[src], output=out))
        assert result == out
        assert _file_hash(src) == source_hash
        reversed_doc = fitz.open(str(out))
        try:
            assert reversed_doc.page_count == 3
            assert reversed_doc[0].search_for("C")
            assert reversed_doc[2].search_for("A")
        finally:
            reversed_doc.close()
    finally:
        temp.cleanup()


def test_tools_window_launches_organize_split(qtbot, monkeypatch):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    launched: list[str] = []

    def fake_launch(tools, tool_id):
        launched.append(tool_id)
        assert tools is window

    monkeypatch.setattr(
        "pagedrop.ui.tools_window.launch_organize_tool",
        fake_launch,
    )

    tile = next(t for t in window._tiles if t.entry.id == "split")
    assert not tile.entry.coming_soon
    tile.activated.emit("split")
    assert launched == ["split"]
    window.close()


def test_form_dialog_keeps_widgets_alive_after_accept(qtbot, monkeypatch):
    """Regression: reading fields after exec must not hit deleted Qt objects."""
    from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit

    from pagedrop.ui.organize_tools import _PathRow, _form_dialog

    monkeypatch.setattr(
        QDialog,
        "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )

    parent = ToolsWindow()
    qtbot.addWidget(parent)

    def build(form: QFormLayout, w: dict) -> None:
        w["source"] = _PathRow(parent, browse_title="Choose PDF", initial="/tmp/doc.pdf")
        form.addRow("Source PDF", w["source"])
        w["ranges"] = QLineEdit("2-3,5")
        form.addRow("Page ranges", w["ranges"])

    widgets = _form_dialog(parent, title="Split / extract", build=build)
    assert widgets is not None
    assert widgets["source"].text() == "/tmp/doc.pdf"
    assert widgets["ranges"].text() == "2-3,5"
