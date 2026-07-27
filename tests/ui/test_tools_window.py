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


def test_coming_soon_hidden_by_default_and_toggle_shows(qtbot):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()

    visible_ids = {t.entry.id for t in window.visible_tiles()}
    assert "compress" not in visible_ids
    assert "encrypt" not in visible_ids
    assert "export_tiff" not in visible_ids
    assert "viewer" not in visible_ids

    assert window._upcoming_btn.isVisible()
    assert "Show upcoming tools" in window._upcoming_btn.text()
    window._upcoming_btn.setChecked(True)
    visible_ids = {t.entry.id for t in window.visible_tiles()}
    assert "compress" in visible_ids
    assert "encrypt" in visible_ids
    assert "export_tiff" in visible_ids
    assert "Hide upcoming tools" in window._upcoming_btn.text()
    window.close()


def test_codec_capability_gates_convert_tiles(monkeypatch, qtbot):
    """TIFF / XLSX / HEIC tiles stay blocked when their codec pack is absent."""
    from pagedrop.core.capabilities import OPENPYXL, PI_HEIF, CapabilityStatus

    def _fake_probe(capability_id: str, refresh: bool = False) -> CapabilityStatus:
        del refresh
        if capability_id in {PILLOW, OPENPYXL, PI_HEIF}:
            return CapabilityStatus(
                id=capability_id,
                available=False,
                reason=AbsenceReason.CODEC_MISSING,
                detail="missing in test",
            )
        return CapabilityStatus(id=capability_id, available=True)

    monkeypatch.setattr("pagedrop.ui.tools_window.probe", _fake_probe)
    window = ToolsWindow()
    qtbot.addWidget(window)
    window._upcoming_btn.setChecked(True)
    window.show()

    by_id = {t.entry.id: t for t in window._tiles}
    for tool_id in ("export_tiff", "export_xlsx", "import_heic"):
        tile = by_id[tool_id]
        assert tile.is_blocked()
        assert "Codec missing" in tile._subtitle.text()
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
    from pagedrop.ui.busy_overlay import ToastOverlay

    assert ToastOverlay.ERROR_TIMEOUT_MS > ToastOverlay.DEFAULT_TIMEOUT_MS

    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    window.show_toast("fail", kind="error")
    assert window._toast.isVisible()
    assert window._toast._timer.interval() == ToastOverlay.ERROR_TIMEOUT_MS
    window.close()
