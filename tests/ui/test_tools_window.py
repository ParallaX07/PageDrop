"""UI shell — Tools hub window."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pagedrop.core.capabilities import (
    AbsenceReason,
    CapabilityStatus,
    PILLOW,
)
from pagedrop.core.jobs import JobCancelledError, preflight_pdf_inputs
from pagedrop.ui.busy_overlay import ToastOverlay
from pagedrop.ui.command_palette import collect_actions
from pagedrop.ui.dialogs import (
    prompt_cancel_running_job,
    prompt_missing_capability,
    prompt_pdf_password,
)
from pagedrop.ui.job_chrome import JobChromeMixin
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.result_actions import ResultActionsBar, show_in_folder
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow
from pagedrop.ui.window_manager import WindowManager
from tests.core.test_jobs import _encrypted_pdf
from tests.conftest import RENDER_TIMEOUT_MS


def test_shell_owns_job_chrome_not_catalogue():
    """O15: JobChromeMixin lives on shells; catalogue keeps toast only."""
    assert not issubclass(ToolsWindow, JobChromeMixin)
    assert issubclass(ToolShellWindow, JobChromeMixin)
    assert ToolShellWindow.begin_job is JobChromeMixin.begin_job
    assert ToolShellWindow.end_job is JobChromeMixin.end_job
    assert ToolShellWindow._on_preview_result is JobChromeMixin._on_preview_result
    assert ToolShellWindow._on_open_result is JobChromeMixin._on_open_result
    assert hasattr(ToolsWindow, "show_toast")
    assert not hasattr(ToolsWindow, "begin_job")


def test_merge_create_compare_share_result_action_handlers():
    """O16: Merge/Create/Compare Preview/Open/Show reuse JobChromeMixin."""
    from pagedrop.ui.compare_window import CompareWindow
    from pagedrop.ui.convert_window import ConvertWindow
    from pagedrop.ui.merge_window import MergeWindow

    for cls in (MergeWindow, ConvertWindow, CompareWindow):
        assert issubclass(cls, JobChromeMixin)
        assert cls._on_preview_result is JobChromeMixin._on_preview_result
        assert cls._on_open_result is JobChromeMixin._on_open_result
        assert cls._on_show_folder is JobChromeMixin._on_show_folder


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
    main_window.show()
    main_window._actions["tools"].trigger()
    qtbot.waitUntil(
        lambda: main_window._tools_window is not None
        and main_window._tab_manager.indexOf(main_window._tools_window) >= 0,
        timeout=5000,
    )
    tools = main_window._tools_window
    assert isinstance(tools, ToolsWindow)
    assert main_window._tab_manager.currentWidget() is tools
    assert tools._search.isVisible()
    assert tools.visible_tiles()
    assert any(t.entry.id == "merge" for t in tools.visible_tiles())
    index = main_window._tab_manager.indexOf(tools)
    assert main_window._try_close_tab(index)
    qtbot.waitUntil(lambda: main_window._tools_window is None, timeout=5000)


def test_tools_hub_tiles_use_sentence_case_titles(qtbot):
    """Spot-check catalogue titles stay sentence-case (not Title Case)."""
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    samples = {e.id: e.title for e in TOOL_CATALOGUE}
    assert samples["merge"] == "Merge PDFs"
    assert samples["split"] == "Split / extract"
    assert samples["create_pdf"] == "Create PDF"
    assert samples["compress"] == "Compress PDF"
    # No mid-title Capital Words on multi-word non-acronym titles.
    assert samples["alternate"] == "Alternate pages"
    assert samples["normalize"] == "Normalize page size"


def test_tools_reopen_focuses_same_tab(main_window, qtbot):
    main_window._open_tools_window()
    tools = main_window._tools_window
    assert tools is not None
    main_window._tab_manager.add_blank_tab()
    main_window._open_tools_window()
    assert main_window._tab_manager.currentWidget() is tools
    assert main_window._tool_pages.get("tools") is tools


def test_tools_tab_has_no_detach_menu(main_window, qtbot):
    main_window._open_tools_window()
    tools = main_window._tools_window
    assert tools is not None
    index = main_window._tab_manager.indexOf(tools)
    bar = main_window._tab_manager.detachable_tab_bar
    assert not bar._page_is_pdf(index)


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


def test_density_toggle_sets_compact_property(qtbot):
    """R6: Compact density toggle still flips tile compact state/property."""
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    merge = next(t for t in window._tiles if t.entry.id == "merge")
    assert merge.property("compact") is False
    window._compact_btn.setChecked(True)
    assert merge.property("compact") is True
    assert all(t.property("compact") is True for t in window._tiles)
    window._compact_btn.setChecked(False)
    assert merge.property("compact") is False
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


def _job_chrome_host(qtbot) -> ToolShellWindow:
    shell = ToolShellWindow(title="Test tool", description="Job chrome host")
    qtbot.addWidget(shell)
    shell.show()
    return shell


def test_failed_job_shows_dialog_not_status_only(qtbot, monkeypatch):
    window = _job_chrome_host(qtbot)

    shown: list[str] = []

    def fake_critical(parent, title, text):
        shown.append(text)
        return 0

    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.QMessageBox.critical",
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
    window = _job_chrome_host(qtbot)

    out = tmp_path / "prev.pdf"
    out.write_bytes(b"%PDF-1.4")
    window._result_bar.show_for(out)
    assert window._result_bar.isVisible()

    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.QMessageBox.critical",
        lambda *args, **kwargs: 0,
    )
    window.begin_job("Running…")
    window.end_job(error="Failed after a prior success")
    assert not window._result_bar.isVisible()
    window.close()


def test_busy_overlay_cancel_aborts_job(qtbot):
    window = _job_chrome_host(qtbot)

    token = window.begin_job("Working…")
    assert window._busy_overlay._cancel_btn.isVisible()
    assert not token.is_cancelled()

    window._busy_overlay._cancel_btn.click()
    assert token.is_cancelled()
    assert window.is_job_running()  # overlay cancel does not end_job by itself
    window.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
    assert not window.is_job_running()
    window.close()


def test_busy_overlay_escape_cancels_when_cancellable(qtbot):
    from PyQt6.QtCore import Qt

    window = _job_chrome_host(qtbot)
    qtbot.waitExposed(window, timeout=5000)

    token = window.begin_job("Working…")
    overlay = window._busy_overlay
    assert overlay.isVisible()
    assert overlay._cancel_btn.isVisible()
    qtbot.waitUntil(lambda: overlay._cancel_btn.hasFocus(), timeout=2000)

    qtbot.keyClick(overlay._cancel_btn, Qt.Key.Key_Escape)
    assert token.is_cancelled()
    window.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
    window.close()


def test_busy_overlay_escape_blocked_without_cancel(qtbot):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QWidget

    from pagedrop.ui.busy_overlay import BusyOverlay

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(320, 240)
    host.show()
    overlay = BusyOverlay(host)
    overlay.set_cancellable(False)
    cancelled = []
    blocked = []
    overlay.cancelled.connect(lambda: cancelled.append(True))
    overlay.escape_blocked.connect(lambda: blocked.append(True))
    overlay.show_message("Loading…")
    qtbot.waitUntil(lambda: overlay.isVisible(), timeout=2000)
    overlay.setFocus()
    qtbot.waitUntil(lambda: overlay.hasFocus(), timeout=2000)

    qtbot.keyClick(overlay, Qt.Key.Key_Escape)
    assert cancelled == []
    assert blocked == [True]
    overlay.hide_overlay()


def test_protected_pdf_wrong_password_retries_and_cancel_aborts_job(
    qtbot, tmp_path, monkeypatch
):
    """Tools jobs reuse prompt_pdf_password: wrong → retry, cancel aborts job."""
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_bytes = enc.read_bytes()

    window = _job_chrome_host(qtbot)
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
    window = _job_chrome_host(qtbot)
    window.begin_job("Working…")

    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.prompt_cancel_running_job",
        lambda *args, **kwargs: False,
    )
    window.close()
    assert window.isVisible()
    assert window.is_job_running()

    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.prompt_cancel_running_job",
        lambda *args, **kwargs: True,
    )
    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
    assert not window.is_job_running()


def test_closing_editor_with_tools_tab_quits(
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
    assert editor._tab_manager.indexOf(tools) >= 0

    quit_called: list[bool] = []

    def spy_quit() -> None:
        quit_called.append(True)

    monkeypatch.setattr(qapp, "quit", spy_quit)
    editor.close()
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
    assert bar.accessibleName() == f"Saved {path.name}"
    bar.show_for(path, message="Merged 3 files")
    assert bar.accessibleName() == "Merged 3 files"
    bar.clear()
    assert bar.accessibleName() == ""
    bar.show_for(path)
    bar._preview_btn.click()
    bar._open_btn.click()
    bar._folder_btn.click()
    assert [kind for kind, _ in received] == ["preview", "open", "folder"]


def test_tool_tile_accessible_name_and_blocked_description(monkeypatch, qtbot):
    """O14: ToolTile announces title; blocked tiles include absence text."""
    from pagedrop.core.capabilities import TESSDATA, clear_cache
    from pagedrop.ui.tools_window import ToolTile

    clear_cache()

    def _fake_probe(capability_id: str, refresh: bool = False) -> CapabilityStatus:
        del refresh
        if capability_id == TESSDATA:
            return CapabilityStatus(
                id=TESSDATA,
                available=False,
                reason=AbsenceReason.DATA_MISSING,
                detail="missing in test",
            )
        return CapabilityStatus(id=capability_id, available=True)

    monkeypatch.setattr("pagedrop.ui.tools_window.probe", _fake_probe)
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    by_id = {t.entry.id: t for t in window._tiles}

    merge = by_id["merge"]
    assert isinstance(merge, ToolTile)
    assert merge.accessibleName() == merge.entry.title
    assert merge.accessibleDescription() == merge.entry.description

    ocr = by_id["ocr_pdf"]
    assert ocr.is_blocked()
    assert ocr.accessibleName() == ocr.entry.title
    assert "Data missing" in ocr.accessibleDescription()
    assert ocr.entry.description in ocr.accessibleDescription()
    window.close()


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
    assert prompt_missing_capability(host, status, tool_title="Export XLSX") == "cancel"

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
    # Monkeypatching result_actions.sys.platform mutates the shared sys module.
    host_is_windows = sys.platform == "win32"

    monkeypatch.setattr(
        "pagedrop.ui.result_actions.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    # Force folder-open path (non-win/mac select).
    monkeypatch.setattr("pagedrop.ui.result_actions.sys.platform", "linux")
    assert show_in_folder(target) is True
    # QUrl.toLocalFile() uses forward slashes on Windows; pathlib uses backslash.
    folder = str(tmp_path.resolve())
    expected = folder.replace("\\", "/") if host_is_windows else folder
    assert opened == [expected]


def test_search_enter_focuses_first_tile(qtbot):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    window._search.setText("merge")
    window._search.setFocus()
    window._search.returnPressed.emit()
    focused = window.focusWidget()
    assert isinstance(focused, type(window.visible_tiles()[0]))
    assert focused.entry.id == "merge"
    window.close()


def test_coming_soon_toggle_hidden_when_none(qtbot):
    """No coming-soon tiles remain — upcoming toggle stays hidden."""
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    assert not any(e.coming_soon for e in TOOL_CATALOGUE)

    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    visible_ids = {t.entry.id for t in window.visible_tiles()}
    assert "viewer" not in visible_ids
    # Phase 27 Optimize & Secure tiles are live (not coming-soon).
    assert "compress" in visible_ids
    assert "encrypt" in visible_ids
    # Phase 29 OCR / tables are live.
    assert "ocr_pdf" in visible_ids
    assert "extract_tables" in visible_ids
    # Phase 32 Word / spreadsheet conversions.
    assert "pdf_to_word" in visible_ids
    assert "pdf_to_csv" in visible_ids
    assert "pdf_to_excel" in visible_ids

    assert not window._upcoming_btn.isVisible()
    window.close()


def test_category_heading_counts_update_on_filter(qtbot):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    organize = window._category_headings["Organize"]
    assert organize.text() == "Organize (15)"

    window._search.setText("interleave")
    assert organize.text() == "Organize (1 of 15)"
    assert window._match_label.isVisible()
    assert "1 tool match" in window._match_label.text()

    window._search.clear()
    assert organize.text() == "Organize (15)"
    assert not window._match_label.isVisible()
    window.close()


def test_no_viewer_tile_in_tools_catalogue(qtbot):
    """Preview/viewer lives on the editor tab — not duplicated in Tools."""
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    assert "View" not in window._category_sections
    assert all(t.entry.id != "viewer" for t in window._tiles)
    window.close()


def test_tools_shortcut_is_ctrl_shift_o_not_ctrl_t(main_window):
    from PyQt6.QtGui import QKeySequence

    action = main_window._actions["tools"]
    assert action.shortcut() == QKeySequence("Ctrl+Shift+O")
    assert main_window._actions["new_tab"].shortcut() == QKeySequence("Ctrl+T")


def test_tile_tooltip_uses_description(qtbot):
    window = ToolsWindow()
    qtbot.addWidget(window)
    tile = next(t for t in window._tiles if t.entry.id == "merge")
    assert tile.toolTip() == tile.entry.description
    window.close()


def test_error_toast_uses_longer_timeout(qtbot):
    assert ToastOverlay.ERROR_TIMEOUT_MS > ToastOverlay.DEFAULT_TIMEOUT_MS

    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    window.show_toast("fail", kind="error")
    assert window._toast.isVisible()
    assert window._toast._timer.interval() == ToastOverlay.ERROR_TIMEOUT_MS
    window.close()
