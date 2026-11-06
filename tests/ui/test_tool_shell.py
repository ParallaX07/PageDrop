"""Phase 22b — shared modeless tool shell."""

from __future__ import annotations

import contextlib
import sys
import threading
import time
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import QEventLoop, QMimeData, QPoint, QPointF, Qt, QTimer, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QFileDialog, QFormLayout, QLabel, QLineEdit, QWidget

from pagedrop.core import pdf_tools
from pagedrop.core.jobs import CancelToken
from pagedrop.core.thread_policy import FITZ_LOCK
from pagedrop.ui.organize_shell import SHELL_ORGANIZE_IDS, open_organize_shell
from pagedrop.ui.organize_tools import (
    ORGANIZE_DEDICATED_WINDOW_EXCEPTIONS,
    ORGANIZE_TOOL_IDS,
    launch_organize_tool,
)
from pagedrop.ui.tool_shell import (
    FileDropZone,
    ToolShellWindow,
    probe_pdf_input,
    show_field_error,
    run_tool_job,
)
from pagedrop.ui.tools_window import ToolsWindow
from tests.conftest import file_sha256, hold_fitz_lock
from tests.core.test_jobs import _encrypted_pdf


def _write_pdf(path: Path, pages: int = 3) -> None:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), f"P{i}", fontsize=18)
        doc.save(str(path))
    finally:
        doc.close()


def test_tool_forms_wrap_and_keep_validation_local(qtbot):
    shell = ToolShellWindow(title="Test tool", description="Test tool.")
    qtbot.addWidget(shell)
    options = QWidget()
    form = QFormLayout(options)
    field = QLineEdit()
    form.addRow("A deliberately long option label", field)
    shell.set_options_widget(options)

    assert form.rowWrapPolicy() is QFormLayout.RowWrapPolicy.WrapLongRows
    error = show_field_error(field, "Enter a value.")
    assert error.isVisible() is False  # The shell is not shown yet.
    shell.show()
    assert error.isVisible()
    assert error.text() == "Enter a value."


def _prime_shell_for_run(
    shell: ToolShellWindow,
    tool_id: str,
    *,
    src: Path,
    src_b: Path,
    out_dir: Path,
    monkeypatch,
) -> Path:
    """Drop files + stub save pickers so Run exercises the real job path."""
    out_dir.mkdir(parents=True, exist_ok=True)

    if tool_id == "split":
        shell.drop_zone.set_paths([str(src)])
        shell._ranges_edit.setText("1-2")  # type: ignore[attr-defined]
        shell._folder_edit.setText(str(out_dir))  # type: ignore[attr-defined]
        return pdf_tools.predicted_range_output_paths(
            [(0, 1)], out_dir, base_name=src.stem
        )[0]

    if tool_id == "alternate":
        shell.drop_zone.set_paths([str(src), str(src_b)])
        out = out_dir / f"{src.stem}_alternated.pdf"
        monkeypatch.setattr(
            "pagedrop.ui.organize_shell._pick_save_pdf",
            lambda parent, title, suggested: str(out),
        )
        return out

    if tool_id == "zip":
        shell.drop_zone.set_paths([str(src), str(src_b)])
        out = out_dir / "pdfs.zip"
        monkeypatch.setattr(
            "pagedrop.ui.organize_shell._pick_save_zip",
            lambda parent, suggested: str(out),
        )
        return out

    if tool_id == "attachments":
        attach = out_dir / "note.txt"
        attach.write_text("hello", encoding="utf-8")
        shell.drop_zone.set_paths([str(src)])
        edits = [
            e
            for e in shell._options_host.findChildren(QLineEdit)
            if e.isEnabled()
        ]
        assert len(edits) >= 2
        edits[0].setText(attach.name)
        edits[1].setText(str(attach))
        out = out_dir / f"{src.stem}_attachments.pdf"
        monkeypatch.setattr(
            "pagedrop.ui.organize_shell._pick_save_pdf",
            lambda parent, title, suggested: str(out),
        )
        return out

    shell.drop_zone.set_paths([str(src)])
    suffix = {
        "reverse": "reversed",
        "n_up": "nup",
        "booklet": "booklet",
        "posterize": "poster",
        "divide": "divided",
        "combine": "long",
        "normalize": "normalized",
        "metadata": "metadata",
        "page_labels": "labels",
    }.get(tool_id, tool_id)
    out = out_dir / f"{src.stem}_{suffix}.pdf"
    monkeypatch.setattr(
        "pagedrop.ui.organize_shell._pick_save_pdf",
        lambda parent, title, suggested: str(out),
    )
    return out


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
    # QUrl.toLocalFile() uses forward slashes on Windows; pathlib uses backslash.
    expected = str(pdf).replace("\\", "/") if sys.platform == "win32" else str(pdf)
    assert zone.paths() == [expected]


def test_drop_zone_default_prompts(qtbot):
    from pagedrop.ui.tool_shell import EMPTY_PROMPT_PDF, EMPTY_PROMPT_PDFS

    single = FileDropZone()
    qtbot.addWidget(single)
    assert single._prompt.text() == EMPTY_PROMPT_PDF

    multi = FileDropZone(multi=True)
    qtbot.addWidget(multi)
    assert multi._prompt.text() == EMPTY_PROMPT_PDFS


def test_drop_zone_prompt_uses_full_width(qtbot):
    """Layout AlignCenter used to shrink the prompt and wrap/clip it."""
    zone = FileDropZone(multi=True)
    qtbot.addWidget(zone)
    zone.resize(800, 120)
    zone.show()
    qtbot.waitExposed(zone)
    zone._fit_wrapped_labels()
    zone.resize(800, zone.minimumHeight())

    prompt = zone._prompt
    margins = zone.layout().contentsMargins()
    assert prompt.width() >= zone.width() - margins.left() - margins.right() - 2
    assert prompt.height() >= prompt.heightForWidth(prompt.width())


def test_drop_zone_narrow_wrap_not_clipped(qtbot):
    """When width forces a wrap, zone minimum height must cover the lines."""
    zone = FileDropZone(multi=True)
    qtbot.addWidget(zone)
    zone.resize(160, 96)
    zone.show()
    qtbot.waitExposed(zone)
    zone._fit_wrapped_labels()
    zone.resize(160, zone.minimumHeight())

    prompt = zone._prompt
    needed = prompt.heightForWidth(prompt.width())
    assert needed > prompt.fontMetrics().lineSpacing()  # wrapped
    assert prompt.height() >= needed
    assert zone.minimumHeight() >= zone.layout().sizeHint().height()


def test_run_button_tooltip_matches_description(qtbot):
    """O12: Run tip is sentence-case like Merge/Create primary actions."""
    tip = "Split by ranges into new files"
    shell = ToolShellWindow(title="Split / extract", description=tip)
    qtbot.addWidget(shell)
    assert shell._run_btn.toolTip() == tip
    assert shell._run_btn.statusTip() == tip


def test_shell_sequence_collapses_selected_input_and_demotes_rerun(qtbot, tmp_path):
    source = tmp_path / "report.pdf"
    _write_pdf(source)
    shell = ToolShellWindow(title="Reverse", description="Reverse every page")
    qtbot.addWidget(shell)

    layout = shell.layout()
    assert layout.indexOf(shell._workflow_header) < layout.indexOf(shell.drop_zone)
    assert shell._workflow_header.findChild(QLabel, "ToolWorkflowTitle").text() == "Reverse"

    shell.drop_zone.set_paths([str(source)])
    assert shell.drop_zone._prompt.text() == "Input file"
    assert shell.drop_zone._files_label.text() == "report.pdf"
    assert not shell.drop_zone._change_btn.isHidden()
    assert shell.drop_zone._privacy.isHidden()

    shell._set_result_precedence(True)
    assert shell._run_btn.property("resultAvailable") is True


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
        "pagedrop.ui.organize_shell._pick_save_pdf",
        lambda parent, title, suggested: str(out),
    )

    shell._run_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)
    assert out.is_file()
    assert shell._result_bar.isVisible()
    assert shell._result_bar._path == str(out)
    assert str(out) in shell._result_bar._label.text()
    assert shell._run_btn.text() == "Run"
    assert shell._busy_overlay._cancel_btn.text() == "Cancel"
    assert shell._result_bar._preview_btn.text() == "Preview"
    assert shell._result_bar._open_btn.text() == "Open in editor"
    assert shell._result_bar._folder_btn.text() == "Show in folder"

    reversed_doc = fitz.open(str(out))
    try:
        assert reversed_doc.page_count == 3
        assert reversed_doc[0].search_for("P2")
        assert reversed_doc[2].search_for("P0")
    finally:
        reversed_doc.close()

    shell.close()
    tools.close()


def test_split_multi_file_success_copy_mentions_showing_first(
    qtbot, tmp_path, isolated_settings
):
    """O12: Split N>1 names file count and that result actions bind to the first."""
    src = tmp_path / "doc.pdf"
    out_dir = tmp_path / "parts"
    _write_pdf(src, pages=3)
    out_dir.mkdir()

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    shell = open_organize_shell(tools, "split")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(src)])
    shell._ranges_edit.setText("1,2,3")  # type: ignore[attr-defined]
    shell._folder_edit.setText(str(out_dir))  # type: ignore[attr-defined]

    shell._run_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)

    written = sorted(out_dir.glob("*.pdf"))
    assert len(written) == 3
    first = pdf_tools.predicted_range_output_paths(
        [(0, 0), (1, 1), (2, 2)], out_dir, base_name=src.stem
    )[0]
    status = shell.statusBar().currentMessage()
    toast = shell._toast._message.text()
    bar = shell._result_bar._label.text()
    assert status == "Saved 3 files. Showing first"
    assert toast == "Completed"
    assert status in bar
    assert str(first) in bar
    assert shell._result_bar._path == str(first)
    assert shell.editor is None

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
        "pagedrop.ui.organize_shell.open_organize_shell", fake_open
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

    def fake_preflight_pdf_inputs(_inputs, prompt, cancel, credentials):
        events.append("preflight_pdf_inputs")
        assert cancel is host._token
        assert credentials is None
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
    """Smoke: organize tools open ToolShellWindow (never modal catalogue jobs)."""
    assert ORGANIZE_TOOL_IDS == set(SHELL_ORGANIZE_IDS) | set(
        ORGANIZE_DEDICATED_WINDOW_EXCEPTIONS.keys()
    )

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
        assert shell._run_btn.isDefault()
        opened[tool_id] = shell
        qtbot.addWidget(shell)

    # Cleanup (top-level widgets) so later tests don't leak windows.
    for shell in opened.values():
        shell.close()
    tools.close()


@pytest.mark.parametrize("tool_id", sorted(SHELL_ORGANIZE_IDS))
def test_each_migrated_organize_tool_runs_job_and_shows_result_actions(
    qtbot, tmp_path, monkeypatch, isolated_settings, tool_id
):
    """O7: every shell organize tool opens, runs, and shows result actions."""
    src = tmp_path / "doc.pdf"
    src_b = tmp_path / "doc_b.pdf"
    _write_pdf(src, pages=4)
    _write_pdf(src_b, pages=2)
    source_hash = file_sha256(src)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    shell = open_organize_shell(tools, tool_id)
    assert shell is not None
    qtbot.addWidget(shell)
    assert isinstance(shell, ToolShellWindow)

    out = _prime_shell_for_run(
        shell,
        tool_id,
        src=src,
        src_b=src_b,
        out_dir=tmp_path / f"out_{tool_id}",
        monkeypatch=monkeypatch,
    )

    shell._run_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=15000)
    assert Path(out).is_file(), f"{tool_id} did not write {out}"
    assert shell._result_bar.isVisible()
    assert shell._result_bar._path == str(out)
    assert shell._result_bar._folder_btn.text() == "Show in folder"
    assert not hasattr(tools, "is_job_running")
    assert file_sha256(src) == source_hash
    assert Path(out).resolve() != src.resolve()

    shell.close()
    tools.close()


def test_n_up_shell_cancel_mid_run_via_busy_overlay(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    """Heavy organize cancel: BusyOverlay Cancel mid N-up → idle, no promote."""
    src = tmp_path / "doc.pdf"
    out = tmp_path / "doc_nup.pdf"
    _write_pdf(src, pages=12)
    source_hash = file_sha256(src)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    shell = open_organize_shell(tools, "n_up")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(src)])
    monkeypatch.setattr(
        "pagedrop.ui.organize_shell._pick_save_pdf",
        lambda parent, title, suggested: str(out),
    )

    real_check = pdf_tools._check_cancel
    checks = {"n": 0}

    def wait_for_ui_cancel(cancel):
        checks["n"] += 1
        if checks["n"] == 1:
            # Block mid-loop until BusyOverlay Cancel flips the token.
            deadline = time.time() + 5.0
            while not cancel.is_cancelled() and time.time() < deadline:
                time.sleep(0.01)
        real_check(cancel)

    monkeypatch.setattr(pdf_tools, "_check_cancel", wait_for_ui_cancel)

    shell._run_btn.click()
    qtbot.waitUntil(
        lambda: (
            shell.is_job_running()
            and checks["n"] >= 1
            and shell._busy_overlay._cancel_btn.isVisible()
        ),
        timeout=5000,
    )
    assert shell._busy_overlay.isVisible()
    shell._busy_overlay._cancel_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=15000)

    assert not out.exists()
    qtbot.waitUntil(lambda: not shell._busy_overlay.isVisible(), timeout=1000)
    assert not shell._result_bar.isVisible()
    assert shell.statusBar().currentMessage() == "Cancelled"
    assert file_sha256(src) == source_hash
    assert checks["n"] >= 1

    shell.close()
    tools.close()


# --- R11: Run host + vertical rhythm -----------------------------------------


def test_r11_drop_zone_and_options_margins(qtbot):
    """R11: drop-zone (16,12,16,12); options layout symmetric (no P9 8px right)."""
    zone = FileDropZone()
    qtbot.addWidget(zone)
    m = zone.layout().contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (16, 12, 16, 12)

    shell = ToolShellWindow(title="Demo", description="Margins")
    qtbot.addWidget(shell)
    om = shell._options_layout.contentsMargins()
    assert (om.left(), om.top(), om.right(), om.bottom()) == (0, 0, 0, 0)


def test_r11_standard_shell_run_enabled_after_file_pick(qtbot, tmp_path):
    """R11: standard shell keeps one Run in #ToolShellActions; enables after pick."""
    from PyQt6.QtWidgets import QPushButton, QToolBar

    src = tmp_path / "doc.pdf"
    _write_pdf(src, pages=1)

    shell = ToolShellWindow(title="Reverse", description="Reverse pages")
    qtbot.addWidget(shell)
    shell.show()
    qtbot.waitExposed(shell, timeout=5000)

    assert shell._actions_host.isVisible()
    assert shell._run_btn.parentWidget() is shell._actions_host
    assert not shell._run_btn.isEnabled()
    assert shell.findChild(QToolBar, "ToolShellToolbar") is None

    shell.drop_zone.set_paths([str(src)])
    assert shell._run_btn.isEnabled()
    runs = [
        w
        for w in shell.findChildren(QPushButton)
        if w.objectName() == "ToolbarPrimary" and w.text() == "Run"
    ]
    assert runs == [shell._run_btn]


def test_r11_empty_options_shell_collapses_options_scroll(qtbot):
    """R11: empty options must not expand a blank form band.

    R19: compact title+? header stays visible (help reachable); stretch stays 0.
    """
    from PyQt6.QtWidgets import QFormLayout, QLabel, QWidget

    shell = ToolShellWindow(title="Booklet", description="No options")
    qtbot.addWidget(shell)
    shell.set_options_widget(QWidget())
    shell.show()
    qtbot.waitExposed(shell, timeout=5000)

    assert shell._options_scroll.isVisible()
    assert shell._header_host.isVisible()
    assert shell._help_btn.isVisible()
    root = shell.layout()
    assert root.stretch(root.indexOf(shell._options_scroll)) == 0

    # Real controls restore the scroll stretch.
    opts = QWidget()
    form = QFormLayout(opts)
    form.addRow("Hint", QLabel("x"))
    shell.set_options_widget(opts)
    assert shell._options_scroll.isVisible()
    assert shell._header_host.isVisible()
    assert shell._options_host.isAncestorOf(shell._header_host)
    assert root.stretch(root.indexOf(shell._options_scroll)) == 1


def test_r18_header_lives_in_options_not_root(qtbot):
    """R18/R19: title + ? are under options, not above the drop zone."""
    from PyQt6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget

    shell = ToolShellWindow(title="Demo", description="In options")
    qtbot.addWidget(shell)
    opts = QWidget()
    form = QFormLayout(opts)
    form.addRow("Hint", QLabel("x"))
    shell.set_options_widget(opts)

    root = shell.layout()
    assert root.indexOf(shell._header_host) < 0
    assert root.indexOf(shell._title_label) < 0
    assert shell._options_host.isAncestorOf(shell._title_label)
    assert shell._title_label.text() == "Demo"
    assert shell.findChild(QLabel, "ToolShellDescription") is None
    assert shell._help_btn.text() == "?"

    # adopt_header docks into an external column (Watermark pattern).
    col = QWidget()
    col_lay = QVBoxLayout(col)
    shell.adopt_header(col_lay)
    assert col.isAncestorOf(shell._header_host)
    assert not shell._options_host.isAncestorOf(shell._header_host)


def test_r19_help_popup_shows_help_text(qtbot):
    """R19: ? opens a popup with help_text (falls back to description)."""
    from PyQt6.QtWidgets import QFormLayout, QLabel, QWidget

    from pagedrop.ui.tool_shell import _ToolHelpPopup

    shell = ToolShellWindow(
        title="Demo",
        description="Short line",
        help_text="Detailed help about this tool for the popup.",
    )
    qtbot.addWidget(shell)
    opts = QWidget()
    form = QFormLayout(opts)
    form.addRow("Hint", QLabel("x"))
    shell.set_options_widget(opts)
    shell.show()
    qtbot.waitExposed(shell, timeout=5000)

    assert shell.findChild(QLabel, "ToolShellDescription") is None
    shell._help_btn.click()
    qtbot.waitUntil(
        lambda: shell._help_popup is not None and shell._help_popup.isVisible(),
        timeout=2000,
    )
    assert isinstance(shell._help_popup, _ToolHelpPopup)
    body = shell._help_popup.findChild(QLabel, "ToolShellHelpBody")
    assert body is not None
    assert "Detailed help" in body.text()
    shell._help_btn.click()
    qtbot.waitUntil(
        lambda: shell._help_popup is None or not shell._help_popup.isVisible(),
        timeout=2000,
    )


def test_r11_booklet_shell_hides_empty_options(qtbot, isolated_settings):
    """R11/R19: booklet empty form — no expand; title+? header still visible."""
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_organize_shell(tools, "booklet")
    assert shell is not None
    qtbot.addWidget(shell)
    assert shell._options_scroll.isVisible()
    assert shell._header_host.isVisible()
    assert shell._help_btn.isVisible()
    root = shell.layout()
    assert root.stretch(root.indexOf(shell._options_scroll)) == 0
    assert shell._actions_host.isVisible()
    assert shell._run_btn.parentWidget() is shell._actions_host
    shell.close()
    tools.close()


def test_r11_metadata_load_from_file_left_aligned(qtbot, isolated_settings):
    """R11: Load from file is compact/left — not a full-width form-spanning primary."""
    from PyQt6.QtWidgets import QPushButton

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_organize_shell(tools, "metadata")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.resize(640, 520)
    shell.show()
    qtbot.waitExposed(shell, timeout=5000)

    load_btn = next(
        b
        for b in shell._options_host.findChildren(QPushButton)
        if b.text() == "Load from file"
    )
    assert load_btn.objectName() == "ToolbarSecondary"
    # Must not stretch across the options host (old form.addRow("", btn) look).
    assert load_btn.width() < shell._options_host.width() * 0.6
    shell.close()
    tools.close()


def test_tool_shell_hides_idle_status_footer(qtbot):
    """Placeholder idle status must not reserve a full-width strip."""
    shell = ToolShellWindow(title="Demo", description="Demo tool")
    qtbot.addWidget(shell)
    shell.show()
    status = shell.statusBar()
    assert status.currentMessage() == ""
    assert status.isHidden()
    status.showMessage("Working…")
    assert not status.isHidden()
    assert status.isVisible()
    assert status.currentMessage() == "Working…"
    status.showMessage("")
    assert status.isHidden()


class _RecordingHost:
    WINDOW_TITLE = "Tools"

    def __init__(self) -> None:
        self.specs: list = []
        self.ended: list[dict] = []
        self._running = False
        host = self

        class _Runner:
            def run(self, spec, **_kwargs):
                host.specs.append(spec)
                return spec.output

        self._runner = _Runner()

    def job_runner(self):
        return self._runner

    def set_job_progress(self, _fraction: float, _message: str) -> None:
        pass

    def begin_job(self, _message: str = "Working…") -> CancelToken:
        self._running = True
        return CancelToken()

    def is_job_running(self) -> bool:
        return self._running

    def end_job(self, **kwargs) -> None:
        self._running = False
        self.ended.append(kwargs)


def test_run_tool_job_rejects_source_output_before_asking_to_overwrite(
    tmp_path: Path, overwrite_answer
):
    src = tmp_path / "in.pdf"
    _write_pdf(src)
    source_hash = file_sha256(src)
    host = _RecordingHost()

    run_tool_job(host, job_type="reverse", inputs=[str(src)], output=str(src))

    assert overwrite_answer.calls == []
    assert host.specs == []
    assert host.ended[-1]["toast"] == "Cannot overwrite source"
    assert file_sha256(src) == source_hash


def test_run_tool_job_declined_overwrite_leaves_existing_file(
    tmp_path: Path, overwrite_answer
):
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _write_pdf(src)
    out.write_bytes(b"existing")
    source_hash = file_sha256(src)
    overwrite_answer.answer = False
    host = _RecordingHost()

    run_tool_job(host, job_type="reverse", inputs=[str(src)], output=str(out))

    assert overwrite_answer.calls == [[out]]
    assert host.specs == []
    assert host.ended[-1]["status"] == "Cancelled"
    assert out.read_bytes() == b"existing"
    assert file_sha256(src) == source_hash


def test_run_tool_job_only_allows_overwrite_when_user_confirmed(
    tmp_path: Path, qtbot, overwrite_answer
):
    src = tmp_path / "in.pdf"
    _write_pdf(src)
    fresh = tmp_path / "fresh.pdf"
    taken = tmp_path / "taken.pdf"
    taken.write_bytes(b"existing")
    host = _RecordingHost()

    run_tool_job(host, job_type="reverse", inputs=[str(src)], output=str(fresh))
    qtbot.waitUntil(lambda: len(host.specs) == 1, timeout=5000)
    run_tool_job(host, job_type="reverse", inputs=[str(src)], output=str(taken))
    qtbot.waitUntil(lambda: len(host.specs) == 2, timeout=5000)

    assert host.specs[0].overwrite is False
    assert host.specs[1].overwrite is True
    assert overwrite_answer.calls == [[taken]]


# --- Preflight waits for a running job without freezing the window -----------

WAITING = "Waiting for running job…"


def _write_encrypted_pdf(path: Path, password: str = "pw") -> None:
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200).insert_text((40, 80), "secret", fontsize=18)
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw=password,
        )
    finally:
        doc.close()


def _new_shell(qtbot) -> ToolShellWindow:
    shell = ToolShellWindow(title="Test tool", description="Test tool.")
    qtbot.addWidget(shell)
    return shell


def _reverse(shell, src: Path, out: Path) -> None:
    run_tool_job(
        shell,
        job_type="reverse",
        inputs=[str(src)],
        output=str(out),
        options={"add_blank_page": False},
        progress_message="Reversing pages…",
    )


def test_run_waits_for_fitz_lock_without_blocking_event_loop(qtbot, tmp_path):
    src = tmp_path / "doc.pdf"
    out = tmp_path / "doc_reversed.pdf"
    _write_pdf(src, pages=3)
    source_hash = file_sha256(src)
    shell = _new_shell(qtbot)
    messages: list[str] = []
    real_progress = shell.set_job_progress

    def spy_progress(fraction, message, **kwargs):
        messages.append(message)
        real_progress(fraction, message, **kwargs)

    shell.set_job_progress = spy_progress
    ticks: list[int] = []
    probe = QTimer()
    probe.timeout.connect(lambda: ticks.append(1))
    probe.start(10)

    with hold_fitz_lock():
        started = time.monotonic()
        _reverse(shell, src, out)
        assert time.monotonic() - started < 1.0
        assert shell.is_job_running()
        assert shell.statusBar().currentMessage() == WAITING
        assert messages == [WAITING]
        qtbot.waitUntil(lambda: len(ticks) >= 5, timeout=3000)
        assert shell.is_job_running()
        assert not shell.worker_pending()
        assert not out.exists()

    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)
    probe.stop()
    assert messages[:2] == [WAITING, "Reversing pages…"]
    assert out.is_file()
    assert file_sha256(src) == source_hash
    assert out.resolve() != src.resolve()
    assert not FITZ_LOCK._is_owned()


def test_cancel_during_fitz_lock_wait_ends_cancelled(qtbot, tmp_path, monkeypatch):
    src = tmp_path / "doc.pdf"
    out = tmp_path / "doc_reversed.pdf"
    _write_pdf(src)
    source_hash = file_sha256(src)
    shell = _new_shell(qtbot)
    prompts: list[str] = []
    monkeypatch.setattr(
        "pagedrop.ui.tool_shell.prompt_pdf_password",
        lambda *_a, **_k: prompts.append("prompt"),
    )
    baseline = len(shell.findChildren(QTimer))

    with hold_fitz_lock():
        _reverse(shell, src, out)
        assert shell.statusBar().currentMessage() == WAITING
        assert len(shell.findChildren(QTimer)) == baseline + 1
        shell.cancel_active_job()
        # Ends while the other thread still holds the lock.
        qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=3000)
        assert shell.statusBar().currentMessage() == "Cancelled"
        assert not shell.worker_pending()

    qtbot.waitUntil(lambda: len(shell.findChildren(QTimer)) == baseline, timeout=3000)
    assert not out.exists()
    assert prompts == []
    assert file_sha256(src) == source_hash
    assert not FITZ_LOCK._is_owned()


def test_closing_host_during_fitz_lock_wait_ends_once(qtbot, tmp_path):
    src = tmp_path / "doc.pdf"
    out = tmp_path / "doc_reversed.pdf"
    _write_pdf(src)
    shell = _new_shell(qtbot)
    ends: list[dict] = []
    real_end = shell.end_job

    def spy_end(**kwargs):
        ends.append(kwargs)
        real_end(**kwargs)

    shell.end_job = spy_end
    baseline = len(shell.findChildren(QTimer))

    with hold_fitz_lock():
        _reverse(shell, src, out)
        assert shell.statusBar().currentMessage() == WAITING
        shell.close()
        assert not shell.is_job_running()
        assert len(ends) == 1

    qtbot.waitUntil(lambda: len(shell.findChildren(QTimer)) == baseline, timeout=3000)
    qtbot.wait(150)
    assert len(ends) == 1
    assert not shell.worker_pending()
    assert not out.exists()
    assert not FITZ_LOCK._is_owned()


def test_fitz_lock_caught_in_narrow_free_window(qtbot, tmp_path, monkeypatch):
    """A job that frees the lock for ~1 ms must still be caught by a waiting tick."""
    from pagedrop.ui import job_chrome

    src = tmp_path / "doc.pdf"
    out = tmp_path / "doc_reversed.pdf"
    _write_pdf(src)
    main_thread = threading.current_thread()
    waiting = threading.Event()
    calls: list[tuple] = []

    class SpyLock:
        def acquire(self, blocking=True, timeout=-1):
            if threading.current_thread() is main_thread and not FITZ_LOCK._is_owned():
                calls.append((blocking, timeout))
                waiting.set()
            return FITZ_LOCK.acquire(blocking, timeout)

        def release(self):
            FITZ_LOCK.release()

    monkeypatch.setattr(job_chrome, "FITZ_LOCK", SpyLock())
    # Skip the synchronous first try so the timer path is what gets exercised.
    monkeypatch.setattr(job_chrome, "_LOCK_FIRST_TRY_S", 0)

    stop = threading.Event()
    held = threading.Event()

    def churn() -> None:
        # Free the lock for 2 ms, but only once the GUI side has started an
        # acquire and had time to sleep in it.
        while not stop.is_set():
            waiting.clear()
            with FITZ_LOCK:
                held.set()
                if waiting.wait(0.2):
                    time.sleep(0.005)
            time.sleep(0.002)

    thread = threading.Thread(target=churn, daemon=True)
    thread.start()
    try:
        assert held.wait(5)
        shell = _new_shell(qtbot)
        _reverse(shell, src, out)
        qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=5000)
    finally:
        stop.set()
        thread.join(5)

    assert out.is_file()
    assert len(calls) <= 4
    assert not FITZ_LOCK._is_owned()


@pytest.mark.parametrize("contended", [False, True])
def test_fitz_lock_free_during_dialogs_and_prompt_precedes_confirm(
    qtbot, tmp_path, monkeypatch, contended
):
    src = tmp_path / "locked.pdf"
    out = tmp_path / "locked_reversed.pdf"
    _write_encrypted_pdf(src)
    out.write_bytes(b"%PDF-1.4 old")
    source_hash = file_sha256(src)
    shell = _new_shell(qtbot)
    events: list[str] = []
    answers = iter(["wrong", "pw"])

    def prompt(_parent, _name, incorrect=False):
        events.append(f"prompt:{incorrect}:owned={FITZ_LOCK._is_owned()}")
        return next(answers)

    def confirm(_parent, _paths, window_title):
        events.append(f"confirm:owned={FITZ_LOCK._is_owned()}")
        return True

    monkeypatch.setattr("pagedrop.ui.tool_shell.prompt_pdf_password", prompt)
    monkeypatch.setattr("pagedrop.ui.tool_shell.confirm_overwrite", confirm)

    if contended:
        with hold_fitz_lock():
            _reverse(shell, src, out)
            assert shell.statusBar().currentMessage() == WAITING
            assert events == []
    else:
        _reverse(shell, src, out)
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)

    assert events == [
        "prompt:False:owned=False",
        "prompt:True:owned=False",
        "confirm:owned=False",
    ]
    result = fitz.open(str(out))
    try:
        assert result.page_count == 1
    finally:
        result.close()
    assert file_sha256(src) == source_hash
    assert not FITZ_LOCK._is_owned()


@pytest.mark.parametrize("contended", [False, True])
def test_fitz_lock_released_after_prompt_cancel_and_load_error(
    qtbot, tmp_path, monkeypatch, contended
):
    shell = _new_shell(qtbot)
    errors: list[bool] = []
    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.QMessageBox.critical",
        staticmethod(lambda *_a, **_k: errors.append(FITZ_LOCK._is_owned())),
    )
    locked = tmp_path / "locked.pdf"
    _write_encrypted_pdf(locked)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    monkeypatch.setattr(
        "pagedrop.ui.tool_shell.prompt_pdf_password", lambda *_a, **_k: None
    )

    def run(src: Path) -> None:
        out = tmp_path / f"{src.stem}_out.pdf"
        if contended:
            with hold_fitz_lock():
                _reverse(shell, src, out)
                assert shell.statusBar().currentMessage() == WAITING
        else:
            _reverse(shell, src, out)
        qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)
        assert not out.exists()
        assert not FITZ_LOCK._is_owned()

    run(locked)
    assert shell.statusBar().currentMessage() == "Cancelled"
    assert errors == []
    run(broken)
    assert errors == [False]


class _TickThenRelease:
    """Hold ``FITZ_LOCK`` on a helper thread; free it after *after* event-loop ticks."""

    def __init__(self, after: int = 5) -> None:
        self.after = after
        self.ticks = 0
        self._stack = contextlib.ExitStack()
        self._held = False
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)

    def hold(self) -> None:
        self._stack.enter_context(hold_fitz_lock())
        self._held = True
        self.ticks = 0
        self._timer.start(10)

    def _tick(self) -> None:
        if self._held:
            self.ticks += 1
            if self.ticks >= self.after:
                self.release()

    def release(self) -> None:
        self._held = False
        self._stack.close()

    @property
    def held(self) -> bool:
        return self._held

    def stop(self) -> None:
        self._timer.stop()
        self.release()


def test_gui_fitz_call_pumps_events_without_user_input_and_passes_results(
    qtbot, monkeypatch
):
    from pagedrop.ui import job_chrome

    flags: list[object] = []
    real_process = job_chrome.QApplication.processEvents

    class SpyApp:
        @staticmethod
        def processEvents(flag=QEventLoop.ProcessEventsFlag.AllEvents):  # noqa: N802
            flags.append(flag)
            real_process(flag)

    monkeypatch.setattr(job_chrome, "QApplication", SpyApp)
    seen_owned: list[bool] = []

    def probe(a, *, b):
        seen_owned.append(FITZ_LOCK._is_owned())
        return a + b

    assert job_chrome.gui_fitz_call(probe, 1, b=2) == 3
    assert flags == [], "the uncontended path must not pump events"

    def boom():
        raise ValueError("probe failed")

    with pytest.raises(ValueError, match="probe failed"):
        job_chrome.gui_fitz_call(boom)
    assert flags == []
    assert not FITZ_LOCK._is_owned()

    holder = _TickThenRelease()
    try:
        holder.hold()
        assert job_chrome.gui_fitz_call(probe, 5, b=6) == 11
        assert holder.ticks >= 5, "timers kept running during the wait"
        assert flags
        assert set(flags) == {QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents}
        assert seen_owned == [True, True]
        assert not FITZ_LOCK._is_owned()

        holder.hold()
        with pytest.raises(ValueError, match="probe failed"):
            job_chrome.gui_fitz_call(boom)
    finally:
        holder.stop()
    assert not FITZ_LOCK._is_owned()
    assert FITZ_LOCK.acquire(timeout=1.0)
    FITZ_LOCK.release()


def test_split_run_stays_live_while_another_thread_holds_the_lock(
    qtbot, tmp_path, isolated_settings
):
    src = tmp_path / "doc.pdf"
    out_dir = tmp_path / "parts"
    _write_pdf(src, pages=3)
    out_dir.mkdir()
    source_hash = file_sha256(src)
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_organize_shell(tools, "split")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(src)])
    shell._ranges_edit.setText("1-2")  # type: ignore[attr-defined]
    shell._folder_edit.setText(str(out_dir))  # type: ignore[attr-defined]

    holder = _TickThenRelease()
    try:
        holder.hold()
        shell._run_btn.click()  # returns only after the pumped wait ended
        assert holder.ticks >= 5, "the window kept running while the page count waited"
    finally:
        holder.stop()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)

    assert len(list(out_dir.glob("*.pdf"))) == 1
    assert file_sha256(src) == source_hash
    assert not FITZ_LOCK._is_owned()
    shell.close()
    tools.close()


def test_prompt_reacquire_waits_for_a_job_without_freezing_the_event_loop(
    qtbot, tmp_path, monkeypatch
):
    src = tmp_path / "locked.pdf"
    out = tmp_path / "locked_reversed.pdf"
    _write_encrypted_pdf(src)
    source_hash = file_sha256(src)
    shell = _new_shell(qtbot)
    holder = _TickThenRelease()
    prompts: list[bool] = []

    def prompt(_parent, _name, incorrect=False):
        prompts.append(FITZ_LOCK._is_owned())
        holder.hold()  # a job takes the lock while the prompt is open
        return "pw"

    monkeypatch.setattr("pagedrop.ui.tool_shell.prompt_pdf_password", prompt)
    try:
        _reverse(shell, src, out)
        assert holder.ticks >= 5, "the event loop kept running during the re-acquire"
        assert not holder.held
    finally:
        holder.stop()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)

    assert prompts == [False]
    assert out.is_file()
    assert out.resolve() != src.resolve()
    assert file_sha256(src) == source_hash
    assert not FITZ_LOCK._is_owned()


def test_cancel_during_prompt_reacquire_ends_cancelled_without_the_lock(
    qtbot, tmp_path, monkeypatch
):
    src = tmp_path / "locked.pdf"
    out = tmp_path / "locked_reversed.pdf"
    _write_encrypted_pdf(src)
    source_hash = file_sha256(src)
    shell = _new_shell(qtbot)
    holder = _TickThenRelease(after=10_000)  # only released explicitly

    def prompt(_parent, _name, incorrect=False):
        holder.hold()
        QTimer.singleShot(30, shell.cancel_active_job)
        return "pw"

    monkeypatch.setattr("pagedrop.ui.tool_shell.prompt_pdf_password", prompt)
    try:
        _reverse(shell, src, out)
        # Ended while the other thread still holds the lock.
        assert holder.held
        assert not shell.is_job_running()
        assert shell.statusBar().currentMessage() == "Cancelled"
        assert not FITZ_LOCK._is_owned()
    finally:
        holder.stop()

    assert FITZ_LOCK.acquire(timeout=1.0), "the GUI left the lock balanced"
    FITZ_LOCK.release()
    assert not out.exists()
    assert file_sha256(src) == source_hash


def _count_password_prompts(monkeypatch, replies: list[tuple[str, bool]]) -> list[bool]:
    """Patch the password dialog; returns the incorrect-flag seen on each prompt."""
    seen: list[bool] = []
    queue = iter(replies)

    def fake_get_text(*args, **kwargs):
        label = args[2] if len(args) > 2 else kwargs.get("label", "")
        seen.append("Incorrect password" in label)
        return next(queue)

    monkeypatch.setattr("pagedrop.ui.dialogs.QInputDialog.getText", fake_get_text)
    return seen


def test_probe_pdf_input_returns_count_and_credentials(qtbot, tmp_path, monkeypatch):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    shell = ToolShellWindow(title="Probe tool", description="Probe.")
    qtbot.addWidget(shell)
    prompts = _count_password_prompts(monkeypatch, [("wrong", True), ("secret", True)])

    probed = probe_pdf_input(shell, str(enc))

    assert probed is not None
    count, creds = probed
    assert count == 1
    assert creds is shell.tool_credentials
    assert creds.get(str(enc)) == "secret"
    assert prompts == [False, True]

    # The unlocked password is remembered: no further prompt.
    assert probe_pdf_input(shell, str(enc)) is not None
    assert prompts == [False, True]


def test_probe_pdf_input_returns_none_when_prompt_cancelled(
    qtbot, tmp_path, monkeypatch
):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    shell = ToolShellWindow(title="Probe tool", description="Probe.")
    qtbot.addWidget(shell)
    prompts = _count_password_prompts(monkeypatch, [("", False)])

    assert probe_pdf_input(shell, str(enc)) is None
    assert prompts == [False]
    assert shell.tool_credentials.get(str(enc)) is None
    assert shell.statusBar().currentMessage() == "Cancelled"


def test_run_tool_job_defaults_to_shell_credentials(qtbot, tmp_path, monkeypatch):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = file_sha256(enc)
    shell = ToolShellWindow(title="Reverse tool", description="Reverse.")
    qtbot.addWidget(shell)
    prompts = _count_password_prompts(monkeypatch, [("secret", True)])

    for name in ("first.pdf", "second.pdf"):
        out = tmp_path / name
        run_tool_job(shell, job_type="reverse", inputs=[str(enc)], output=str(out))
        qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10_000)
        assert out.is_file()
        assert out != enc

    assert prompts == [False]
    assert shell.tool_credentials.get(str(enc)) == "secret"
    assert file_sha256(enc) == source_hash


def test_zip_of_encrypted_pdf_does_not_prompt(qtbot, tmp_path, monkeypatch):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = file_sha256(enc)
    out = tmp_path / "locked.zip"
    shell = ToolShellWindow(title="Zip tool", description="Zip.")
    qtbot.addWidget(shell)
    prompts = _count_password_prompts(monkeypatch, [])

    run_tool_job(
        shell,
        job_type="zip",
        inputs=[str(enc)],
        output=str(out),
        check_passwords=False,
    )
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10_000)

    assert prompts == []
    assert out.is_file()
    assert file_sha256(enc) == source_hash
