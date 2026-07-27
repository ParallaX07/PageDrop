"""Smoke — Phase 22b modeless tool shell: open, cancel, success + cleanup."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core.jobs import JobCancelledError, JobContext, JobSpec
from pagedrop.ui.tool_shell import open_organize_shell
from pagedrop.ui.tools_window import ToolsWindow


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_pdf(path: Path, pages: int = 2) -> None:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), f"P{i}", fontsize=18)
        doc.save(str(path))
    finally:
        doc.close()


def test_smoke_shell_open_cancel_success_cleanup(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    src = tmp_path / "in.pdf"
    out_ok = tmp_path / "out_ok.pdf"
    out_cancel = tmp_path / "out_cancel.pdf"
    _write_pdf(src)
    source_hash = _file_hash(src)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    shell = open_organize_shell(tools, "reverse")
    assert shell is not None
    qtbot.addWidget(shell)
    qtbot.waitUntil(lambda: shell.isVisible(), timeout=5000)
    shell.drop_zone.set_paths([str(src)])
    assert shell._run_btn.isEnabled()

    def cancelling_handler(ctx: JobContext) -> Path:
        ctx.staged_output.write_bytes(b"%PDF-partial")
        ctx.cancel.cancel()
        ctx.cancel.check()
        return ctx.staged_output

    runner = shell.job_runner()
    runner.register("shell_cancel", cancelling_handler)

    token = shell.begin_job("Cancelling…")
    with pytest.raises(JobCancelledError):
        runner.run(
            JobSpec.create(
                "shell_cancel", inputs=[str(src)], output=str(out_cancel)
            ),
            cancel=token,
        )
    shell.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
    assert not out_cancel.exists()
    assert _file_hash(src) == source_hash
    assert not shell.is_job_running()
    assert not shell._result_bar.isVisible()

    monkeypatch.setattr(
        "pagedrop.ui.tool_shell._pick_save_pdf",
        lambda parent, title, suggested: str(out_ok),
    )
    shell._run_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)
    assert out_ok.is_file()
    assert _file_hash(src) == source_hash
    assert shell._result_bar.isVisible()
    assert shell.statusBar().currentMessage().startswith("Saved")

    shell.close()
    tools.close()
    qtbot.waitUntil(lambda: not shell.isVisible(), timeout=5000)
