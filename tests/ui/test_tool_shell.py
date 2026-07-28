"""Phase 22b — shared modeless tool shell."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QFileDialog

from pagedrop.ui.organize_tools import (
    ORGANIZE_DEDICATED_WINDOW_EXCEPTIONS,
    ORGANIZE_MODAL_TOOL_EXCEPTIONS,
    ORGANIZE_TOOL_IDS,
    launch_organize_tool,
)
from pagedrop.ui.tool_shell import (
    SHELL_ORGANIZE_IDS,
    FileDropZone,
    ToolShellWindow,
    open_organize_shell,
    run_tool_job,
)
from pagedrop.ui.tools_window import ToolsWindow
from pagedrop.core.jobs import CancelToken, JobCancelledError


def _write_pdf(path: Path, pages: int = 3) -> None:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), f"P{i}", fontsize=18)
        doc.save(str(path))
    finally:
        doc.close()


def test_drop_zone_click_opens_picker(qtbot, tmp_path, monkeypatch):
    pdf = tmp_path / "picked.pdf"
    _write_pdf(pdf)
    zone = FileDropZone()
    qtbot.addWidget(zone)
    zone.show()

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(pdf), "PDF files (*.pdf)"),
    )
    zone.open_picker()
    assert zone.paths() == [str(pdf)]

    # Click path uses the same picker.
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(pdf), "PDF files (*.pdf)"),
    )
    qtbot.mouseClick(zone, Qt.MouseButton.LeftButton)
    assert zone.paths() == [str(pdf)]


def test_drop_zone_accepts_file_urls(qtbot, tmp_path):
    pdf = tmp_path / "dropped.pdf"
    txt = tmp_path / "notes.txt"
    _write_pdf(pdf)
    txt.write_text("nope", encoding="utf-8")

    zone = FileDropZone()
    qtbot.addWidget(zone)
    zone.show()

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(pdf)), QUrl.fromLocalFile(str(txt))])
    pos = QPoint(20, 20)
    enter = QDragEnterEvent(
        pos,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    zone.dragEnterEvent(enter)
    assert enter.isAccepted()

    drop = QDropEvent(
        QPointF(pos),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    zone.dropEvent(drop)
    assert drop.isAccepted()
    assert zone.paths() == [str(pdf)]


def test_migrated_tool_runs_job_and_shows_result_actions(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    src = tmp_path / "doc.pdf"
    out = tmp_path / "doc_reversed.pdf"
    _write_pdf(src, pages=3)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    shell = open_organize_shell(tools, "reverse")
    assert shell is not None
    qtbot.addWidget(shell)
    assert isinstance(shell, ToolShellWindow)
    shell.drop_zone.set_paths([str(src)])

    monkeypatch.setattr(
        "pagedrop.ui.tool_shell._pick_save_pdf",
        lambda parent, title, suggested: str(out),
    )

    shell._run_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)
    assert out.is_file()
    assert shell._result_bar.isVisible()
    assert shell._result_bar._path == str(out)

    reversed_doc = fitz.open(str(out))
    try:
        assert reversed_doc.page_count == 3
        assert reversed_doc[0].search_for("P2")
        assert reversed_doc[2].search_for("P0")
    finally:
        reversed_doc.close()

    shell.close()
    tools.close()


def test_tools_hub_launches_shell_for_migrated_ids(qtbot, monkeypatch):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    opened: list[str] = []

    def fake_open(t, tool_id):
        opened.append(tool_id)
        assert t is tools
        return None

    monkeypatch.setattr(
        "pagedrop.ui.organize_tools.open_organize_shell", fake_open
    )
    for tool_id in sorted(SHELL_ORGANIZE_IDS):
        launch_organize_tool(tools, tool_id)
    assert opened == sorted(SHELL_ORGANIZE_IDS)
    tools.close()


def test_password_prompt_before_overwrite_confirm(tmp_path: Path, monkeypatch, qtbot):
    """`run_tool_job()` must prompt for password before confirming overwrite."""
    events: list[str] = []

    class FakeRunner:
        def run(self, spec, **_kwargs):
            events.append("runner.run")
            return spec.output

    class FakeHost:
        WINDOW_TITLE = "Tools"

        def __init__(self) -> None:
            self._token: CancelToken | None = None
            self._running = False

        def job_runner(self) -> FakeRunner:
            return FakeRunner()

        def set_job_progress(self, _fraction: float, _message: str) -> None:
            events.append("progress")

        def begin_job(self, _message: str = "Working…") -> CancelToken:
            events.append("begin_job")
            self._running = True
            self._token = CancelToken()
            return self._token

        def is_job_running(self) -> bool:
            return self._running

        def end_job(
            self,
            *,
            status: str | None = None,
            toast: str | None = None,
            toast_kind: str = "info",
            result_path: str | None = None,
            error: str | None = None,
        ) -> None:
            self._running = False
            events.append(f"end_job:{status or error}")

    # Simulate "output already exists" to force overwrite confirmation.
    out = tmp_path / "out.pdf"
    out.write_bytes(b"%PDF-1.4 fake")

    host = FakeHost()

    def fake_prompt_pdf_password(_parent, filename: str, incorrect: bool) -> str:
        assert filename.endswith(".pdf")
        assert incorrect is False
        events.append("password_prompt")
        return "secret"

    def fake_preflight_pdf_inputs(_inputs, prompt, cancel):
        events.append("preflight_pdf_inputs")
        assert cancel is host._token
        # Mimic the preflight triggering an actual password prompt.
        password = prompt("locked.pdf", False)
        assert password == "secret"
        return {}

    def fake_confirm_overwrite(_parent, existing_paths, window_title: str):
        events.append("confirm_overwrite")
        assert window_title == host.WINDOW_TITLE
        assert len(existing_paths) == 1
        assert existing_paths[0].resolve() == out.resolve()
        return True

    monkeypatch.setattr(
        "pagedrop.ui.tool_shell.prompt_pdf_password", fake_prompt_pdf_password
    )
    monkeypatch.setattr(
        "pagedrop.ui.tool_shell.preflight_pdf_inputs", fake_preflight_pdf_inputs
    )
    monkeypatch.setattr(
        "pagedrop.ui.tool_shell.confirm_overwrite", fake_confirm_overwrite
    )

    run_tool_job(
        host,
        job_type="reverse",
        inputs=[str(tmp_path / "input.pdf")],
        output=str(out),
    )

    assert "password_prompt" in events
    assert "confirm_overwrite" in events
    assert events.index("password_prompt") < events.index("confirm_overwrite")
    qtbot.waitUntil(lambda: any(e.startswith("end_job:") for e in events), timeout=5000)
    assert "runner.run" in events
    assert any(e.startswith("end_job:Saved") for e in events)


def test_migrated_organize_tool_uses_modeless_shell(qtbot, monkeypatch):
    """Smoke: migrated tool IDs open ToolShellWindow (never modal _form_dialog)."""
    assert ORGANIZE_TOOL_IDS == set(SHELL_ORGANIZE_IDS) | set(
        ORGANIZE_MODAL_TOOL_EXCEPTIONS.keys()
    ) | set(ORGANIZE_DEDICATED_WINDOW_EXCEPTIONS.keys())

    from PyQt6.QtWidgets import QDialog

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.show()

    def fail_exec(_self):
        raise AssertionError("Modal dialog exec must not be called for migrated tools")

    monkeypatch.setattr(QDialog, "exec", fail_exec)

    opened: dict[str, ToolShellWindow] = {}
    for tool_id in sorted(SHELL_ORGANIZE_IDS):
        launch_organize_tool(tools, tool_id)
        store = getattr(tools, "_tool_shells", {}) or {}
        shell = store.get(tool_id)
        assert isinstance(shell, ToolShellWindow)
        opened[tool_id] = shell
        qtbot.addWidget(shell)

    # Cleanup (top-level widgets) so later tests don't leak windows.
    for shell in opened.values():
        shell.close()
    tools.close()
