"""Side-by-side Compare window UI tests."""

from __future__ import annotations

from pathlib import Path

import fitz

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
    window.close()
    tools.close()


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


def test_compare_success_shows_diff_ratio(
    qtbot, tmp_path: Path, monkeypatch
):
    """UI should read overall diff ratio sidecar and include it in status/toast."""
    import pagedrop.ui.compare_window as compare_module
    from pagedrop.core.jobs import JobSpec

    out = tmp_path / "heat_compare.pdf"
    ratio_text = "0.1234"
    opened: list[str] = []

    class FakeRunner:
        def run(self, spec: JobSpec, **_kwargs):
            out_path = Path(spec.output)
            out_path.write_bytes(b"%PDF-1.4 fake")
            out_path.with_suffix(".compare_ratio.txt").write_text(
                ratio_text, encoding="utf-8"
            )
            return out_path

    class FakeEditor:
        def _open_single_pdf(self, path: str) -> None:
            opened.append(path)

    monkeypatch.setattr(compare_module, "ensure_organize_runner", lambda: FakeRunner())
    monkeypatch.setattr(
        compare_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(out), "PDF files (*.pdf)"),
    )

    window = CompareWindow(editor=FakeEditor())
    qtbot.addWidget(window)
    window.show()
    window._path_a = str(tmp_path / "a.pdf")
    window._path_b = str(tmp_path / "b.pdf")
    window._export_heatmap()

    status = window.statusBar().currentMessage()
    assert "Overall diff" in status
    assert f"{float(ratio_text):.4f}" in status
    assert window._result_bar.isVisible()
    assert window._result_bar._path == str(out)
    assert opened == []  # success must not auto-open
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
