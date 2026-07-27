"""Phase 25 UI — Convert to PDF / Export from PDF modeless shells."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PyQt6.QtWidgets import QMessageBox

from pagedrop.core.capabilities import OPENPYXL, PI_HEIF, PILLOW, clear_cache
from pagedrop.ui.native_convert_shell import (
    SHELL_CONVERT_IDS,
    _page_indices_from_text,
    open_conversion_shell,
)
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow


def _write_pdf(path: Path, pages: int = 3, text: str = "hello") -> None:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), f"{text}-{i}", fontsize=16)
        doc.save(str(path))
    finally:
        doc.close()


def test_page_indices_reuse_page_jump_patterns():
    assert _page_indices_from_text("", 10) is None
    assert _page_indices_from_text("1-3,5", 10) == [0, 1, 2, 4]
    assert _page_indices_from_text("bogus", 10) == []


def test_convert_and_export_tiles_open_modeless_shell(qtbot):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    for tool_id in sorted(SHELL_CONVERT_IDS):
        shell = open_conversion_shell(tools, tool_id)
        assert shell is not None
        assert isinstance(shell, ToolShellWindow)
        assert shell.isVisible()
        qtbot.addWidget(shell)
        shell.close()


def test_convert_to_pdf_tile_not_coming_soon(qtbot):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    visible = {t.entry.id for t in window.visible_tiles()}
    assert "convert_to_pdf" in visible
    assert "export_from_pdf" in visible
    by_id = {t.entry.id: t.entry for t in window._tiles}
    assert by_id["convert_to_pdf"].action == "convert_to_pdf"
    assert by_id["export_from_pdf"].action == "export_from_pdf"
    window.close()


def test_unsupported_format_message(qtbot, tmp_path, monkeypatch, isolated_settings):
    bad = tmp_path / "notes.docx"
    bad.write_bytes(b"not-a-supported-native-import")

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    shell = open_conversion_shell(tools, "convert_to_pdf")
    assert shell is not None
    qtbot.addWidget(shell)
    # Drop zone accept-filter normally rejects this; inject past it to hit on_run.
    shell.drop_zone._accept = lambda _p: True
    shell.drop_zone.set_paths([str(bad)])
    assert shell._run_btn.isEnabled()

    captured: list[tuple[str, str]] = []

    def fake_warning(parent, title, text, *args, **kwargs):
        captured.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    shell._run_btn.click()
    assert len(captured) == 1
    assert "Unsupported format" in captured[0][1]
    assert "notes.docx" in captured[0][1]
    assert not shell.is_job_running()


def test_export_dialog_omits_gated_formats_when_absent(
    qtbot, monkeypatch, isolated_settings
):
    clear_cache()

    class _Absent:
        available = False
        detail = "not installed"

        def __init__(self) -> None:
            from pagedrop.core.capabilities import AbsenceReason

            self.reason = AbsenceReason.CODEC_MISSING

    def fake_probe(capability_id, refresh=False):
        if capability_id in {PILLOW, OPENPYXL, PI_HEIF}:
            return _Absent()
        return type("S", (), {"available": True, "reason": None, "detail": ""})()

    monkeypatch.setattr("pagedrop.core.supported_formats.probe", fake_probe)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    shell = open_conversion_shell(tools, "export_from_pdf")
    assert shell is not None
    qtbot.addWidget(shell)

    ids = {shell._format_combo.itemData(i) for i in range(shell._format_combo.count())}
    assert "png" in ids
    assert "text" in ids
    assert "tiff" not in ids
    assert "xlsx" not in ids
    assert shell._ranges_edit.placeholderText()
    assert shell._dpi_spin.value() > 0


def test_export_shell_runs_job_via_runner(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    src = tmp_path / "doc.pdf"
    out = tmp_path / "doc.txt"
    _write_pdf(src, pages=2, text="born-digital")

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    shell = open_conversion_shell(tools, "export_from_pdf")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(src)])

    # Prefer text format (single-file, no folder picker).
    combo = shell._format_combo
    for i in range(combo.count()):
        if combo.itemData(i) == "text":
            combo.setCurrentIndex(i)
            break
    else:
        pytest.fail("text export format missing")

    monkeypatch.setattr(
        "pagedrop.ui.native_convert_shell._pick_save_path",
        lambda parent, title, suggested, file_filter: str(out),
    )

    shell._run_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)
    assert out.is_file()
    assert "born-digital" in out.read_text(encoding="utf-8")
    assert shell._result_bar.isVisible()


def test_convert_shell_batch_via_job_runner(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.md"
    a.write_text("Alpha page", encoding="utf-8")
    b.write_text("# Beta\n\nBody", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()

    shell = open_conversion_shell(tools, "convert_to_pdf")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(a), str(b)])

    monkeypatch.setattr(
        "pagedrop.ui.native_convert_shell._pick_folder",
        lambda parent, title: str(out_dir),
    )

    shell._run_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=15000)
    assert (out_dir / "a.pdf").is_file()
    assert (out_dir / "b.pdf").is_file()
    assert shell._result_bar.isVisible()
