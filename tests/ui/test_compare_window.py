"""Side-by-side Compare window UI tests."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtWidgets import QToolBar

from pagedrop.ui.compare_window import CompareWindow
from pagedrop.ui.organize_tools import launch_organize_tool
from pagedrop.ui.tools_window import ToolsWindow


def _write_line_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 260), text, fontsize=10)
        doc.save(str(path))
    finally:
        doc.close()


def test_tools_tile_opens_compare_window(qtbot):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.show()

    launch_organize_tool(tools, "compare")
    window = getattr(tools, "_compare_window", None)
    assert isinstance(window, CompareWindow)
    qtbot.waitUntil(lambda: window.isVisible(), timeout=3000)
    # R13: empty state is path rows + primary only; mode toolbar stays hidden.
    assert not window._toolbar.isVisible()
    assert window._compare_btn.objectName() == "ToolbarPrimary"
    assert window._row_b.isAncestorOf(window._compare_btn)
    # O14: arrow-key nav is wired even while the toolbar is hidden.
    toolbars = window.findChildren(QToolBar)
    assert toolbars
    assert hasattr(toolbars[0], "_pagedrop_arrow_nav")
    window.close()
    tools.close()


def test_compare_toolbar_visible_after_report(qtbot, tmp_path: Path):
    """R13: mode/nav/zoom toolbar appears only after a successful compare."""
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _write_line_pdf(a, "alpha")
    _write_line_pdf(b, "beta")

    window = CompareWindow()
    qtbot.addWidget(window)
    window.show()
    assert not window._toolbar.isVisible()

    window._row_a.set_text(str(a))
    window._row_b.set_text(str(b))
    window._run_compare()
    qtbot.waitUntil(lambda: window._report is not None, timeout=5000)
    qtbot.waitUntil(lambda: not window._comparing, timeout=5000)

    assert window._toolbar.isVisible()
    assert window._export_act.isEnabled()
    # Path rows stay usable for another compare; keyboard nav remains installed.
    assert window._row_a.isEnabled()
    assert window._row_b.isEnabled()
    assert hasattr(window._toolbar, "_pagedrop_arrow_nav")
    window.close()


def test_compare_window_lists_deleted_text(qtbot, tmp_path: Path):
    a = tmp_path / "full.pdf"
    b = tmp_path / "short.pdf"
    long_line = (
        "Tech Stack: Electron 30, React 18, Express 5, SQLite, Drizzle ORM, "
        "Zustand, TanStack Query, Tailwind CSS v4, shadcn/ui"
    )
    short_line = "Tech Stack: Electron 30, React 18, Express 5, SQLite, Drizzle ORM,"
    _write_line_pdf(a, long_line)
    _write_line_pdf(b, short_line)

    window = CompareWindow()
    qtbot.addWidget(window)
    window.show()
    window._row_a.set_text(str(a))
    window._row_b.set_text(str(b))
    window._run_compare()
    qtbot.waitUntil(lambda: window._report is not None, timeout=5000)
    qtbot.waitUntil(lambda: not window._comparing, timeout=5000)

    assert window._report is not None
    assert window._report.deleted_count == 1
    assert window._change_list.count() == 1
    item = window._change_list.item(0)
    assert "Removed" in item.text()
    assert "Zustand" in item.text()

    # Selecting the change jumps to page 1 and paints a highlight on A.
    window._change_list.setCurrentRow(0)
    assert window._page_index == 0
    highlights = window._highlights_for_page("a", 0)
    assert highlights
    assert any(r[1] <= 260 <= r[3] for r, _color in highlights)

    window.close()


def test_compare_viewer_uses_replacement_before_after_and_red_green(qtbot):
    from pagedrop.core.pdf_tools import CompareChange, CompareReport

    window = CompareWindow()
    qtbot.addWidget(window)
    change = CompareChange(
        kind="modified",
        page_a=0,
        page_b=0,
        text="old → new",
        before_text="old complete value",
        after_text="new complete value",
        rects_a=((10.0, 20.0, 30.0, 40.0),),
        rects_b=((12.0, 22.0, 32.0, 42.0),),
    )
    window._report = CompareReport(changes=(change,), page_count_a=1, page_count_b=1)
    window._populate_changes()

    label = window._change_list.item(0).text()
    assert "1. Replaced" in label
    assert "Original p.1 / Revised p.1" in label
    assert "Before: old complete value" in label
    assert "After: new complete value" in label
    assert (
        "Text comparison, matched by page number. Image, formatting, and moved-content differences are not classified."
        == window._limitation.text()
    )
    original_color = window._highlights_for_page("a", 0)[0][1]
    revised_color = window._highlights_for_page("b", 0)[0][1]
    assert original_color.red() > original_color.green()
    assert revised_color.green() > revised_color.red()
    window.close()


def test_compare_input_edit_clears_report_and_result_actions(qtbot):
    from pagedrop.core.pdf_tools import CompareReport

    window = CompareWindow()
    qtbot.addWidget(window)
    window._path_a = "original.pdf"
    window._path_b = "revised.pdf"
    window._report = CompareReport(changes=(), page_count_a=1, page_count_b=1)
    window._toolbar.setVisible(True)
    window._result_bar.show_for("result.pdf")

    window._row_a.set_text("edited.pdf")

    assert window._report is None
    assert not window._toolbar.isVisible()
    assert not window._result_bar.isVisible()
    assert window._summary.text() == "Removed 0 · Added 0 · Replaced 0"
    window.close()


def test_compare_viewer_shows_textless_page_notices(qtbot, monkeypatch):
    import pagedrop.ui.compare_window as compare_module
    from pagedrop.core.pdf_tools import CompareReport
    from PyQt6.QtGui import QPixmap

    window = CompareWindow()
    qtbot.addWidget(window)
    window._path_a = "original.pdf"
    window._path_b = "revised.pdf"
    window._report = CompareReport(
        changes=(),
        page_count_a=1,
        page_count_b=1,
        textless_pages_a=(0,),
        textless_pages_b=(0,),
    )
    monkeypatch.setattr(
        compare_module,
        "_render_page_pixmap",
        lambda *_args, **_kwargs: (QPixmap(40, 40), fitz.Rect(0, 0, 40, 40)),
    )

    window._render_pages()

    assert window._pane_a._notice.text() == "No extractable text on this page"
    assert window._pane_b._notice.text() == "No extractable text on this page"
    window.close()


def test_compare_render_failure_shows_status_and_toast(
    qtbot, tmp_path: Path, monkeypatch
):
    """Pane render errors must surface status/toast — not silent blank panes."""
    import pagedrop.ui.compare_window as compare_module
    from pagedrop.core.pdf_tools import CompareReport

    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _write_line_pdf(a, "alpha")
    _write_line_pdf(b, "beta")

    window = CompareWindow()
    qtbot.addWidget(window)
    window._path_a = str(a)
    window._path_b = str(b)
    window._report = CompareReport(changes=(), page_count_a=1, page_count_b=1)

    def boom(*_args, **_kwargs):
        raise RuntimeError("render boom")

    monkeypatch.setattr(compare_module, "_render_page_pixmap", boom)
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window._toast,
        "show_toast",
        lambda msg, kind="info": toasts.append((msg, kind)),
    )

    window._render_pages()

    status = window.statusBar().currentMessage()
    assert "Could not render page" in status
    assert "render boom" in status
    assert toasts and toasts[-1][1] == "error"
    window.close()


def test_compare_heatmap_uses_async_job_bridge(
    qtbot, tmp_path: Path, monkeypatch
):
    """The secondary heatmap action uses the shared asynchronous bridge."""
    import pagedrop.ui.compare_window as compare_module

    out = tmp_path / "heat_compare.pdf"
    calls: list[dict] = []
    monkeypatch.setattr(
        compare_module,
        "run_tool_job",
        lambda _host, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        compare_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(out), "PDF files (*.pdf)"),
    )

    window = CompareWindow()
    qtbot.addWidget(window)
    window.show()
    window._path_a = str(tmp_path / "a.pdf")
    window._path_b = str(tmp_path / "b.pdf")
    window._export_heatmap()

    assert calls == [
        {
            "job_type": "compare",
            "inputs": [str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")],
            "output": str(out),
            "progress_message": "Exporting visual heatmap…",
            "success_toast": window._heatmap_success_message,
            "credentials": window._credentials,
        }
    ]
    window.close()


def test_compare_export_defaults_and_job_spec(
    qtbot, tmp_path: Path, monkeypatch
):
    import pagedrop.ui.compare_window as compare_module
    from pagedrop.core.pdf_tools import CompareReport, source_fingerprint

    original = tmp_path / "original.pdf"
    revised = tmp_path / "revised.pdf"
    _write_line_pdf(original, "old")
    _write_line_pdf(revised, "new")
    out = tmp_path / "original_compare_split.pdf"
    calls: list[dict] = []

    window = CompareWindow()
    qtbot.addWidget(window)
    window._path_a = str(original)
    window._path_b = str(revised)
    window._report = CompareReport(
        changes=(),
        page_count_a=1,
        page_count_b=1,
        source_fingerprint_a=source_fingerprint(original),
        source_fingerprint_b=source_fingerprint(revised),
    )
    monkeypatch.setattr(
        compare_module,
        "prompt_compare_export_options",
        lambda _parent: ("split", True, True),
    )
    monkeypatch.setattr(
        compare_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(out), "PDF files (*.pdf)"),
    )
    monkeypatch.setattr(
        compare_module,
        "run_tool_job",
        lambda _host, **kwargs: calls.append(kwargs),
    )

    window._export_comparison()

    assert calls[0]["job_type"] == "compare_report"
    assert calls[0]["output"] == str(out)
    assert calls[0]["options"]["layout"] == "split"
    assert calls[0]["options"]["include_summary"] is True
    assert calls[0]["options"]["include_revisions"] is True
    assert set(calls[0]["options"]) == {
        "layout",
        "include_summary",
        "include_revisions",
        "source_fingerprint_a",
        "source_fingerprint_b",
    }
    assert window._export_act.text() == "Export comparison…"
    assert window._heatmap_act.text() == "Export visual heatmap…"
    window.close()


def test_compare_open_in_editor_opens_exported_pdf(qtbot, tmp_path: Path, monkeypatch):
    """Open in editor must load the exported heatmap via the wired editor."""
    out = tmp_path / "heat_compare.pdf"
    out.write_bytes(b"%PDF-1.4 fake")
    opened: list[str] = []

    class FakeEditor:
        def _open_single_pdf(self, path: str) -> None:
            opened.append(path)

    window = CompareWindow(editor=FakeEditor())
    qtbot.addWidget(window)
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window._toast,
        "show_toast",
        lambda msg, kind="info": toasts.append((msg, kind)),
    )
    window._result_bar.show_for(out, message=f"Saved {out.name}")
    window._result_bar._open_btn.click()

    assert opened == [str(out)]
    assert toasts and toasts[-1] == (f"Opened {out.name}", "success")
    window.close()


def test_launch_compare_passes_editor(qtbot):
    """Tools launch must hand the editor through to CompareWindow."""

    class FakeEditor:
        def _open_single_pdf(self, path: str) -> None:
            pass

    editor = FakeEditor()
    tools = ToolsWindow(editor=editor)
    qtbot.addWidget(tools)
    tools.show()

    launch_organize_tool(tools, "compare")
    window = getattr(tools, "_compare_window", None)
    assert isinstance(window, CompareWindow)
    assert window._editor is editor
    window.close()
    tools.close()


def test_request_close_while_comparing_explains_busy(qtbot, monkeypatch):
    window = CompareWindow()
    qtbot.addWidget(window)
    window._comparing = True
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window._toast,
        "show_toast",
        lambda msg, kind="info": toasts.append((msg, kind)),
    )

    assert window.request_close() is False
    assert "still running" in window.statusBar().currentMessage()
    assert toasts and toasts[-1] == ("Compare still running…", "info")


def test_compare_export_cancellation_waits_for_worker_cleanup(qtbot):
    window = CompareWindow()
    qtbot.addWidget(window)
    token = window.begin_job("Exporting comparison…")

    assert window.request_close() is False
    window._busy_overlay._cancel_btn.click()
    assert token.is_cancelled()
    assert window.is_job_running()

    window.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
    assert not window.is_job_running()
    assert window.request_close() is True
    window.close()
