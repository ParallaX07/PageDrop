"""Side-by-side Compare window UI tests."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import fitz
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import QToolBar

from pagedrop.core.thread_policy import FITZ_LOCK
from pagedrop.ui.compare_window import CompareWindow
from pagedrop.ui.organize_tools import launch_organize_tool
from pagedrop.ui.tools_window import ToolsWindow
from tests.conftest import file_sha256, hold_fitz_lock, wait_for_compare_render


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
    from PyQt6.QtGui import QImage

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
        "_render_page_image",
        lambda *_args, **_kwargs: (
            QImage(40, 40, QImage.Format.Format_RGB32),
            fitz.Rect(0, 0, 40, 40),
            fitz.Matrix(1, 0, 0, 1, 0, 0),
        ),
    )

    window._render_pages()
    wait_for_compare_render(qtbot, window)

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

    monkeypatch.setattr(compare_module, "_render_page_image", boom)
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window._toast,
        "show_toast",
        lambda msg, kind="info": toasts.append((msg, kind)),
    )

    window._render_pages()
    wait_for_compare_render(qtbot, window)

    status = window.statusBar().currentMessage()
    assert "Could not render page" in status
    assert "Original: render boom" in status
    assert "Revised: render boom" in status
    assert toasts and toasts[-1][1] == "error"
    window.close()


def test_compare_heatmap_uses_async_job_bridge(
    qtbot, tmp_path: Path, monkeypatch
):
    """The secondary heatmap action uses the shared asynchronous bridge."""
    import pagedrop.ui.compare_window as compare_module
    from pagedrop.core.pdf_tools import CompareReport, source_fingerprint

    original = tmp_path / "a.pdf"
    revised = tmp_path / "b.pdf"
    _write_line_pdf(original, "old")
    _write_line_pdf(revised, "new")
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
    window._path_a = str(original)
    window._path_b = str(revised)
    window._report = CompareReport(
        changes=(),
        page_count_a=1,
        page_count_b=1,
        source_fingerprint_a=source_fingerprint(original),
        source_fingerprint_b=source_fingerprint(revised),
    )
    window._export_heatmap()

    assert calls == [
        {
            "job_type": "compare",
            "inputs": [str(original), str(revised)],
            "output": str(out),
            "existing_paths": [],
            "options": {
                "source_fingerprint_a": asdict(window._report.source_fingerprint_a),
                "source_fingerprint_b": asdict(window._report.source_fingerprint_b),
            },
            "progress_message": "Exporting visual heatmap…",
            "success_toast": window._heatmap_success_message,
            "credentials": window._credentials,
        }
    ]

    # An existing ratio note is covered by the overwrite confirmation.
    sidecar = out.with_suffix(".compare_ratio.txt")
    sidecar.write_text("0.1000", encoding="utf-8")
    window._export_heatmap()
    assert calls[-1]["existing_paths"] == [sidecar]
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


def _write_rotated_line_pdf(path: Path, text: str, rotation: int) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 260), text, fontsize=10)
        page.set_rotation(rotation)
        doc.save(str(path))
    finally:
        doc.close()


def test_compare_highlights_follow_rotated_pages(qtbot, tmp_path: Path):
    """Highlights land on the changed word's displayed position on /Rotate pages."""
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _write_rotated_line_pdf(a, "alpha", 90)
    _write_rotated_line_pdf(b, "beta", 270)

    window = CompareWindow()
    qtbot.addWidget(window)
    window.show()
    window._row_a.set_text(str(a))
    window._row_b.set_text(str(b))
    window._run_compare()
    qtbot.waitUntil(lambda: window._report is not None, timeout=5000)
    qtbot.waitUntil(lambda: not window._comparing, timeout=5000)
    window._change_list.setCurrentRow(0)
    wait_for_compare_render(qtbot, window)

    for pane, path, word in ((window._pane_a, a, "alpha"), (window._pane_b, b, "beta")):
        canvas = pane._canvas
        doc = fitz.open(str(path))
        try:
            page = doc[0]
            shown = page.search_for(word)[0] * page.rotation_matrix
            sx = canvas._pixmap.width() / page.rect.width
            sy = canvas._pixmap.height() / page.rect.height
        finally:
            doc.close()
        x = int((shown.x0 + shown.x1) / 2 * sx)
        y = int((shown.y0 + shown.y1) / 2 * sy)
        plain = canvas._pixmap.toImage().pixelColor(x, y)
        painted = canvas.grab().toImage().pixelColor(x, y)
        assert painted != plain, f"no highlight over {word!r} at {(x, y)}"

    window.close()


def test_compare_waits_for_fitz_lock_then_proceeds(qtbot, tmp_path: Path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _write_line_pdf(a, "alpha")
    _write_line_pdf(b, "beta")
    hashes = (file_sha256(a), file_sha256(b))
    window = CompareWindow()
    qtbot.addWidget(window)
    window._row_a.set_text(str(a))
    window._row_b.set_text(str(b))

    with hold_fitz_lock():
        window._run_compare()
        assert window._comparing
        assert window.statusBar().currentMessage() == "Waiting for running job…"
        qtbot.wait(200)
        assert window._report is None
        assert window._comparing

    qtbot.waitUntil(lambda: window._report is not None, timeout=5000)
    qtbot.waitUntil(lambda: not window._comparing, timeout=5000)
    assert (file_sha256(a), file_sha256(b)) == hashes
    assert not FITZ_LOCK._is_owned()
    window.close()


def test_compare_cancel_during_fitz_lock_wait(qtbot, tmp_path: Path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _write_line_pdf(a, "alpha")
    _write_line_pdf(b, "beta")
    window = CompareWindow()
    qtbot.addWidget(window)
    window._row_a.set_text(str(a))
    window._row_b.set_text(str(b))

    with hold_fitz_lock():
        window._run_compare()
        assert window.statusBar().currentMessage() == "Waiting for running job…"
        window.cancel_active_job()
        qtbot.waitUntil(lambda: not window._comparing, timeout=3000)
        assert not window.is_job_running()
        assert window.statusBar().currentMessage() == "Cancelled"

    assert window._report is None
    assert not FITZ_LOCK._is_owned()
    window.close()


# --- debounced, off-thread pane renders ------------------------------------


def _write_pages_pdf(path: Path, pages: int, *, y: float = 260) -> None:
    doc = fitz.open()
    try:
        for n in range(pages):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, y), f"page {n + 1} text", fontsize=10)
        doc.save(str(path))
    finally:
        doc.close()


def _report_window(qtbot, tmp_path: Path, pages: int = 3, *, show: bool = True):
    from pagedrop.core.pdf_tools import CompareReport

    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _write_pages_pdf(a, pages)
    _write_pages_pdf(b, pages)
    window = CompareWindow()
    qtbot.addWidget(window)
    # Large enough for the panes to fit a full page without side scrolling.
    window.resize(960, 640)
    if show:
        window.show()
    window._path_a = str(a)
    window._path_b = str(b)
    window._report = CompareReport(changes=(), page_count_a=pages, page_count_b=pages)
    return window


def _record_renders(monkeypatch):
    """Wrap the pane render; returns the list of (path, page, width, thread id)."""
    import threading

    import pagedrop.ui.compare_window as compare_module

    calls: list[tuple[str, int, int, int]] = []
    real = compare_module._render_page_image

    def recording(path, page_index, width_px, **kwargs):
        calls.append((path, page_index, width_px, threading.get_ident()))
        return real(path, page_index, width_px, **kwargs)

    monkeypatch.setattr(compare_module, "_render_page_image", recording)
    return calls


def test_compare_render_burst_coalesces_to_one_render(qtbot, tmp_path: Path, monkeypatch):
    window = _report_window(qtbot, tmp_path)
    window._render_pages()
    wait_for_compare_render(qtbot, window)
    calls = _record_renders(monkeypatch)

    for _ in range(10):
        window._nudge_zoom(1.05)
    for _ in range(10):
        window.resize(window.width() + 6, window.height())
    window._nudge_page(1)
    for _ in range(3):
        window._nudge_zoom(1.02)
    assert not calls
    wait_for_compare_render(qtbot, window)

    final_width = window._target_width()
    assert [(page, width) for _p, page, width, _t in calls] == [(1, final_width)] * 2
    assert window._page_label.text() == "Page 2 / 3"


def test_compare_render_runs_off_gui_thread_and_gui_stays_responsive(
    qtbot, tmp_path: Path, monkeypatch
):
    import threading

    import pagedrop.ui.compare_window as compare_module
    from PyQt6.QtCore import QTimer

    window = _report_window(qtbot, tmp_path)
    started = threading.Event()
    release = threading.Event()
    threads: list[int] = []
    real = compare_module._render_page_image

    def blocking(path, page_index, width_px, **kwargs):
        threads.append(threading.get_ident())
        started.set()
        assert release.wait(10)
        return real(path, page_index, width_px, **kwargs)

    monkeypatch.setattr(compare_module, "_render_page_image", blocking)
    ticks: list[int] = []
    ticker = QTimer(window)
    ticker.timeout.connect(lambda: ticks.append(1))
    ticker.start(10)
    try:
        window._render_pages()
        qtbot.waitUntil(started.is_set, timeout=5000)
        qtbot.waitUntil(lambda: len(ticks) >= 3, timeout=2000)
        assert not window._render_landed
        release.set()
        wait_for_compare_render(qtbot, window)
    finally:
        release.set()
        ticker.stop()

    assert threads and set(threads) != {threading.get_ident()}


def test_compare_stale_render_result_is_dropped(qtbot, tmp_path: Path, monkeypatch):
    import threading

    import pagedrop.ui.compare_window as compare_module
    from PyQt6.QtGui import QImage

    window = _report_window(qtbot, tmp_path)
    started = threading.Event()
    release = threading.Event()

    def fake(path, page_index, width_px, **kwargs):
        if page_index == 0:
            started.set()
            assert release.wait(10)
        # Image width encodes which page was rendered.
        return (
            QImage(100 + page_index, 40, QImage.Format.Format_RGB32),
            fitz.Rect(0, 0, 100, 40),
            fitz.Matrix(1, 0, 0, 1, 0, 0),
        )

    monkeypatch.setattr(compare_module, "_render_page_image", fake)
    shown: list[int] = []
    real_set = window._pane_a.set_content
    window._pane_a.set_content = lambda pix, *a, **k: (
        shown.append(pix.width()),
        real_set(pix, *a, **k),
    )

    try:
        window._render_pages()
        qtbot.waitUntil(started.is_set, timeout=5000)
        window._nudge_page(1)
        qtbot.waitUntil(lambda: not window._render_timer.isActive(), timeout=2000)
        release.set()
        wait_for_compare_render(qtbot, window)
    finally:
        release.set()

    assert shown == [101]
    assert window._page_label.text() == "Page 2 / 3"


def test_compare_nudge_does_not_block_on_fitz_lock(qtbot, tmp_path: Path):
    import time

    window = _report_window(qtbot, tmp_path)
    window._render_pages()
    wait_for_compare_render(qtbot, window)

    with hold_fitz_lock():
        started = time.monotonic()
        window._nudge_page(1)
        assert time.monotonic() - started < 1.0
        assert window._page_label.text() == "Page 2 / 3"
        assert window._prev_act.isEnabled()
        qtbot.waitUntil(lambda: not window._render_timer.isActive(), timeout=2000)
        assert not window._render_landed

    wait_for_compare_render(qtbot, window)
    assert not FITZ_LOCK._is_owned()


def test_compare_render_failure_names_the_failing_pane(qtbot, tmp_path: Path, monkeypatch):
    import pagedrop.ui.compare_window as compare_module

    window = _report_window(qtbot, tmp_path, show=False)
    real = compare_module._render_page_image

    def fail_revised(path, page_index, width_px, **kwargs):
        if path == window._path_b:
            raise RuntimeError("revised boom")
        return real(path, page_index, width_px, **kwargs)

    monkeypatch.setattr(compare_module, "_render_page_image", fail_revised)
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window._toast, "show_toast", lambda msg, kind="info": toasts.append((msg, kind))
    )

    window._render_pages()
    wait_for_compare_render(qtbot, window)

    status = window.statusBar().currentMessage()
    assert status == "Could not render page: Revised: revised boom"
    assert toasts == [("Could not render compare page", "error")]
    assert not window._pane_a._canvas._pixmap.isNull()
    assert window._pane_b._canvas._pixmap.isNull()


def test_compare_change_selection_scrolls_after_render_lands(qtbot, tmp_path: Path):
    from pagedrop.core.pdf_tools import compare_pdf_text_diff

    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _write_pages_pdf(a, 1, y=740)
    _write_pages_pdf(b, 1, y=740)
    doc = fitz.open(str(b))
    try:
        doc[0].insert_text((72, 700), "extra words", fontsize=10)
        doc.saveIncr()
    finally:
        doc.close()
    report = compare_pdf_text_diff(str(a), str(b))
    assert report.changes

    window = CompareWindow()
    qtbot.addWidget(window)
    window.resize(960, 640)
    window.show()
    window._apply_compare_report(str(a), str(b), report)
    window._nudge_zoom(2.0)
    window._change_list.setCurrentRow(0)
    pane = window._pane_a if report.changes[0].rects_a else window._pane_b
    bar = pane.scroll.verticalScrollBar()
    assert bar.value() == 0
    assert not window._render_landed

    wait_for_compare_render(qtbot, window)
    qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
    assert bar.value() > 0


def test_compare_close_during_render_drops_late_result(qtbot, tmp_path: Path, monkeypatch):
    import threading

    import pagedrop.ui.compare_window as compare_module
    from PyQt6.QtWidgets import QApplication

    window = _report_window(qtbot, tmp_path, show=False)
    started = threading.Event()
    release = threading.Event()
    real = compare_module._render_page_image

    def blocking(path, page_index, width_px, **kwargs):
        started.set()
        assert release.wait(10)
        return real(path, page_index, width_px, **kwargs)

    monkeypatch.setattr(compare_module, "_render_page_image", blocking)
    updates: list[int] = []
    window._pane_a.set_content = lambda *a, **k: updates.append(1)

    try:
        window._render_pages()
        qtbot.waitUntil(started.is_set, timeout=5000)
        window.close()
        release.set()
        assert compare_module._compare_render_pool().waitForDone(5000)
        QApplication.processEvents()
    finally:
        release.set()

    assert not updates
    assert not window._render_timer.isActive()


def test_compare_late_render_signal_after_widget_deleted_is_harmless(
    qtbot, tmp_path: Path, monkeypatch
):
    import threading

    import pagedrop.ui.compare_window as compare_module
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication

    window = _report_window(qtbot, tmp_path, show=False)
    started = threading.Event()
    release = threading.Event()
    real = compare_module._render_page_image

    def blocking(path, page_index, width_px, **kwargs):
        started.set()
        assert release.wait(10)
        return real(path, page_index, width_px, **kwargs)

    monkeypatch.setattr(compare_module, "_render_page_image", blocking)
    try:
        window._render_pages()
        qtbot.waitUntil(started.is_set, timeout=5000)
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        release.set()
        assert compare_module._compare_render_pool().waitForDone(5000)
        QApplication.processEvents()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not compare_module._COMPARE_RENDER_SIGNAL_REFS, timeout=2000)


def test_compare_render_settles_without_resize_feedback(qtbot, tmp_path: Path, monkeypatch):
    window = _report_window(qtbot, tmp_path)
    # Zoomed in, the page outgrows the pane so its vertical scrollbar appears.
    window._nudge_zoom(2.0)
    wait_for_compare_render(qtbot, window)
    calls = _record_renders(monkeypatch)

    bar = window._pane_a.scroll.verticalScrollBar()
    qtbot.waitUntil(bar.isVisible, timeout=2000)
    assert window._render_key_now() == window._render_key

    window._render_pages()
    window.resizeEvent(QResizeEvent(window.size(), window.size()))
    window._nudge_zoom(1.0)
    assert not window._render_timer.isActive()
    assert not calls


def test_compare_target_width_ignores_scrollbar_state(qtbot, tmp_path: Path):
    from PyQt6.QtCore import Qt

    window = _report_window(qtbot, tmp_path)
    scroll = window._pane_a.scroll
    widths = {}
    for policy in (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
    ):
        scroll.setVerticalScrollBarPolicy(policy)
        want = policy == Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        qtbot.waitUntil(lambda want=want: scroll.verticalScrollBar().isVisible() == want, timeout=2000)
        widths[want] = window._target_width()
    assert widths[True] == widths[False]
    # The reserved bar width keeps the fitted page clear of a horizontal bar.
    assert widths[True] <= scroll.viewport().width()
    assert not scroll.horizontalScrollBar().isVisible()
