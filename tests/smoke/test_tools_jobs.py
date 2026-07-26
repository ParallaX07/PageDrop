"""Smoke tests — Tools hub + shared job runner."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import fitz
import pytest

from pagedrop.core.jobs import (
    JobCancelledError,
    JobContext,
    JobSpec,
    SerializedJobRunner,
)
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.tools_window import ToolsWindow
from pagedrop.utils.temp_manager import TempManager


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_pdf(path: Path, pages: int = 1) -> None:
    doc = fitz.open()
    try:
        for _ in range(pages):
            doc.new_page(width=200, height=200)
        doc.save(str(path))
    finally:
        doc.close()


def _copy_handler(ctx: JobContext) -> Path:
    src = Path(ctx.spec.inputs[0])
    ctx.cancel.check()
    ctx.progress(0.4, "Copying…")
    shutil.copy2(src, ctx.staged_output)
    ctx.cancel.check()
    ctx.progress(0.8, "Finishing…")
    return ctx.staged_output


def _cancelling_handler(ctx: JobContext) -> Path:
    ctx.staged_output.write_bytes(b"%PDF-partial")
    ctx.cancel.cancel()
    ctx.cancel.check()
    return ctx.staged_output


def test_smoke_tools_opens_and_editor_stays_usable(qtbot, isolated_settings):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._open_tools_window()
    tools = window._tools_window
    assert isinstance(tools, ToolsWindow)
    qtbot.waitUntil(lambda: tools.isVisible(), timeout=5000)
    assert window.isVisible()
    tools.close()
    window.close()


def test_smoke_dummy_job_success_and_cancel_cleanup(qtbot, tmp_path, isolated_settings):
    """Enqueue a dummy job: success promotes; cancel leaves no orphans."""
    src = tmp_path / "in.pdf"
    out_ok = tmp_path / "out-ok.pdf"
    out_cancel = tmp_path / "out-cancel.pdf"
    _write_pdf(src)
    source_hash = _file_hash(src)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        runner.register("dummy_copy", _copy_handler)
        runner.register("dummy_cancel", _cancelling_handler)

        # Success — Tools progress UI + promote + no leftover job_* temps.
        token = tools.begin_job("Running dummy job…")
        assert tools.is_job_running()
        assert tools.statusBar().currentMessage().endswith("…")

        result = runner.run(
            JobSpec.create("dummy_copy", inputs=[src], output=out_ok),
            progress=tools.set_job_progress,
            cancel=token,
        )
        tools.end_job(
            status=f"Saved {result.name}",
            toast=f"Saved {result.name}",
            toast_kind="success",
            result_path=str(result),
        )
        assert result == out_ok
        assert out_ok.is_file()
        assert _file_hash(src) == source_hash
        assert not tools.is_job_running()
        assert tools._result_bar.isVisible()
        assert not any(temp.get_dir().glob("job_*"))

        # Cancel — partial staged output removed; destination never written.
        token = tools.begin_job("Cancelling dummy job…")
        with pytest.raises(JobCancelledError):
            runner.run(
                JobSpec.create("dummy_cancel", inputs=[src], output=out_cancel),
                cancel=token,
            )
        tools.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
        assert not out_cancel.exists()
        assert _file_hash(src) == source_hash
        leftovers = [p for p in temp.get_dir().rglob("*") if p.is_file()]
        assert leftovers == []
        assert not tools.is_job_running()
        assert tools.statusBar().currentMessage() == "Cancelled"
    finally:
        temp.cleanup()
        tools.close()
        qtbot.waitUntil(lambda: not tools.isVisible(), timeout=5000)
