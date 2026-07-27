"""UI shell — Tools hub window."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pagedrop.core.capabilities import (
    AbsenceReason,
    CapabilityStatus,
    PILLOW,
)
from pagedrop.core.jobs import JobCancelledError, preflight_pdf_inputs
from pagedrop.ui.command_palette import collect_actions
from pagedrop.ui.dialogs import (
    prompt_cancel_running_job,
    prompt_missing_capability,
    prompt_pdf_password,
)
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.result_actions import ResultActionsBar, show_in_folder
from pagedrop.ui.tools_window import ToolsWindow
from pagedrop.ui.window_manager import WindowManager
from tests.conftest import RENDER_TIMEOUT_MS


def _wait_for_tab_loaded(qtbot, tab: PdfTab, *, timeout: int = RENDER_TIMEOUT_MS) -> None:
    qtbot.waitUntil(
        lambda: (
            tab.loader is not None
            and tab.thumbnail_grid._last_rendered_width_px
            == tab.thumbnail_grid._thumbnail_width_px
            and tab.thumbnail_grid._render_pool.activeThreadCount() == 0
            and len(tab.thumbnail_grid._cards) == tab.loader.page_count
        ),
        timeout=timeout,
    )


def test_tools_opens_from_menubar(main_window, qtbot):
    assert "tools" in main_window._actions
    main_window._actions["tools"].trigger()
    qtbot.waitUntil(
        lambda: main_window._tools_window is not None
        and main_window._tools_window.isVisible(),
        timeout=5000,
    )
    tools = main_window._tools_window
    assert isinstance(tools, ToolsWindow)
    assert tools._search.isVisible()
    assert tools.visible_tiles()
    assert any(t.entry.id == "merge" for t in tools.visible_tiles())
    tools.close()
    qtbot.waitUntil(lambda: not tools.isVisible(), timeout=5000)


def test_command_palette_finds_tools(main_window):
    labels = {a.text().replace("&", "") for a in collect_actions(main_window)}
    assert "Tools" in labels
    assert main_window._actions["tools"] in collect_actions(main_window)


def test_search_filters_category_grid(qtbot):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    window._search.setText("merge")
    visible = window.visible_tiles()
    assert len(visible) == 1
    assert visible[0].entry.id == "merge"

    window._search.setText("zzz-no-match")
    assert not window.visible_tiles()
    assert window._empty_label.isVisible()
    window.close()


def test_search_matches_multiple_words(qtbot):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    window._search.setText("split extract")
    visible = window.visible_tiles()
    assert any(t.entry.id == "split" for t in visible)
    # Full query as one substring would miss; both tokens must match.
    window._search.setText("split zzz-no-match")
    assert not window.visible_tiles()
    window.close()


def test_failed_job_shows_dialog_not_status_only(qtbot, monkeypatch):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    shown: list[str] = []

    def fake_critical(parent, title, text):
        shown.append(text)
        return 0

    monkeypatch.setattr(
        "pagedrop.ui.tools_window.QMessageBox.critical",
        fake_critical,
    )

    window.begin_job("Running test…")
    assert window._busy_overlay.isVisible()
    status = window.statusBar()
    assert status is not None
    assert status.currentMessage().endswith("…")

    window.end_job(error="Something went wrong with the job.")
    assert shown == ["Something went wrong with the job."]
    assert not window._busy_overlay.isVisible()
    assert status.currentMessage() == "Job failed"
    assert window._toast.isVisible()
    window.close()


def test_end_job_error_clears_result_bar(qtbot, tmp_path, monkeypatch):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    out = tmp_path / "prev.pdf"
    out.write_bytes(b"%PDF-1.4")
    window.show_result(out)
    assert window._result_bar.isVisible()

    monkeypatch.setattr(
        "pagedrop.ui.tools_window.QMessageBox.critical",
        lambda *args, **kwargs: 0,
    )
    window.begin_job("Running…")
    window.end_job(error="Failed after a prior success")
    assert not window._result_bar.isVisible()
    window.close()


def test_busy_overlay_cancel_aborts_job(qtbot):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    token = window.begin_job("Working…")
    assert window._busy_overlay._cancel_btn.isVisible()
    assert not token.is_cancelled()

    window._busy_overlay._cancel_btn.click()
    assert token.is_cancelled()
    assert window.is_job_running()  # overlay cancel does not end_job by itself
    window.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
    assert not window.is_job_running()
    window.close()


def test_protected_pdf_wrong_password_retries_and_cancel_aborts_job(
    qtbot, tmp_path, monkeypatch
):
    """Tools jobs reuse prompt_pdf_password: wrong → retry, cancel aborts job."""
    enc = tmp_path / "locked.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(
            str(enc),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="secret",
            owner_pw="owner",
        )
    finally:
        doc.close()
    source_bytes = enc.read_bytes()

    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    cancel = window.begin_job("Unlocking…")

    prompts: list[bool] = []
    # First attempt: wrong password. Retry: cancel (None).
    replies = iter([("wrong", True), ("", False)])

    def fake_get_text(*args, **kwargs):
        label = args[2] if len(args) > 2 else kwargs.get("label", "")
        incorrect = "Incorrect password" in label
        prompts.append(incorrect)
        return next(replies)

    monkeypatch.setattr(
        "pagedrop.ui.dialogs.QInputDialog.getText",
        fake_get_text,
    )

    def prompt(filename: str, incorrect: bool) -> str | None:
        return prompt_pdf_password(window, filename, incorrect=incorrect)

    with pytest.raises(JobCancelledError):
        preflight_pdf_inputs([enc], prompt=prompt, cancel=cancel)

    assert prompts == [False, True]
    window.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
    assert not window.is_job_running()
    assert not window._busy_overlay.isVisible()
    assert window.statusBar().currentMessage() == "Cancelled"
    assert enc.read_bytes() == source_bytes
    window.close()


def test_close_while_running_confirms_cancel(qtbot, monkeypatch):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    window.begin_job("Working…")

    monkeypatch.setattr(
        "pagedrop.ui.tools_window.prompt_cancel_running_job",
        lambda *args, **kwargs: False,
    )
    window.close()
    assert window.isVisible()
    assert window.is_job_running()

    monkeypatch.setattr(
        "pagedrop.ui.tools_window.prompt_cancel_running_job",
        lambda *args, **kwargs: True,
    )
    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
    assert not window.is_job_running()


def test_window_manager_keeps_app_alive_with_tools_open(
    qtbot, five_page_pdf, qapp, monkeypatch
):
    manager = WindowManager(qapp)
    editor = manager.open_new_window()
    qtbot.addWidget(editor)
    tab = editor._tab_manager.widget(0)
    assert isinstance(tab, PdfTab)
    tab.load_pdf(str(five_page_pdf))
    _wait_for_tab_loaded(qtbot, tab)

    editor._open_tools_window()
    tools = editor._tools_window
    assert tools is not None
    qtbot.addWidget(tools)
    qtbot.waitUntil(lambda: tools.isVisible(), timeout=5000)

    quit_called: list[bool] = []

    def spy_quit() -> None:
        quit_called.append(True)

    monkeypatch.setattr(qapp, "quit", spy_quit)
    editor.close()
    qapp.processEvents()

    assert not quit_called
    assert tools.isVisible()
    tools.close()
    qapp.processEvents()
    assert quit_called


def test_result_actions_bar_emits_explicit_only(qtbot, tmp_path):
    bar = ResultActionsBar()
    qtbot.addWidget(bar)
    path = tmp_path / "out.pdf"
    path.write_bytes(b"%PDF-1.4")

    received: list[tuple[str, str]] = []
    bar.preview_requested.connect(lambda p: received.append(("preview", p)))
    bar.open_in_editor_requested.connect(lambda p: received.append(("open", p)))
    bar.show_in_folder_requested.connect(lambda p: received.append(("folder", p)))

    assert not bar.isVisible()
    bar.show_for(path)
    assert bar.isVisible()
    bar._preview_btn.click()
    bar._open_btn.click()
    bar._folder_btn.click()
    assert [kind for kind, _ in received] == ["preview", "open", "folder"]


def test_missing_capability_dialog_reason_copy(monkeypatch, qtbot):
    from PyQt6.QtWidgets import QWidget

    from pagedrop.ui import dialogs as dialogs_mod

    host = QWidget()
    qtbot.addWidget(host)

    status = CapabilityStatus(
        id=PILLOW,
        available=False,
        reason=AbsenceReason.CODEC_MISSING,
        detail="Pillow not installed",
    )
    monkeypatch.setenv("PAGEDROP_TESTING", "1")
    assert prompt_missing_capability(host, status, tool_title="Export TIFF") == "cancel"

    assert AbsenceReason.ENGINE_MISSING in dialogs_mod._REASON_COPY
    assert AbsenceReason.DATA_MISSING in dialogs_mod._REASON_COPY
    assert AbsenceReason.CODEC_MISSING in dialogs_mod._REASON_COPY
    assert AbsenceReason.LICENCE_BLOCKED in dialogs_mod._REASON_COPY


def test_prompt_cancel_running_job_testing_default(monkeypatch, qtbot):
    from PyQt6.QtWidgets import QWidget

    host = QWidget()
    qtbot.addWidget(host)
    monkeypatch.setenv("PAGEDROP_TESTING", "1")
    assert prompt_cancel_running_job(host) is True


def test_show_in_folder_opens_parent(tmp_path, monkeypatch):
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"%PDF")
    opened: list[str] = []

    monkeypatch.setattr(
        "pagedrop.ui.result_actions.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    # Force folder-open path (non-win/mac select).
    monkeypatch.setattr("pagedrop.ui.result_actions.sys.platform", "linux")
    assert show_in_folder(target) is True
    assert opened == [str(tmp_path.resolve())]
