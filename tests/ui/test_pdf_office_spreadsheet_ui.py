"""Phase 32 UI — PDF to Word / CSV / Excel catalogue + shells."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PyQt6.QtWidgets import QComboBox

from pagedrop.core.capabilities import (
    LIBREOFFICE,
    AbsenceReason,
    CapabilityStatus,
    clear_cache,
)
from pagedrop.ui.ocr_shell import open_ocr_shell
from pagedrop.ui.pdf_to_word_shell import SHELL_PDF_TO_WORD_ID, open_pdf_to_word_shell
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow


@pytest.fixture(autouse=True)
def _reset_caps() -> None:
    clear_cache()
    yield
    clear_cache()


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_phase32_tiles_present(qtbot, isolated_settings):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    by_id = {t.entry.id: t.entry for t in window._tiles}
    assert by_id["pdf_to_word"].action == "pdf_to_word"
    assert by_id["pdf_to_word"].capability_id == LIBREOFFICE
    assert not by_id["pdf_to_word"].coming_soon
    assert by_id["pdf_to_csv"].action == "pdf_to_csv"
    assert by_id["pdf_to_excel"].action == "pdf_to_excel"
    assert "csv" in by_id["convert_to_pdf"].keywords
    assert "csv" in by_id["office_to_pdf"].keywords
    window.close()


def test_pdf_to_word_shell_opens(qtbot, monkeypatch, isolated_settings):
    monkeypatch.setattr(
        "pagedrop.ui.pdf_to_word_shell.probe",
        lambda _cid, refresh=False: CapabilityStatus(
            id=LIBREOFFICE,
            available=True,
            detail="ok",
            extras={"path": "/usr/bin/soffice"},
        ),
    )
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_pdf_to_word_shell(tools)
    assert shell is not None
    assert isinstance(shell, ToolShellWindow)
    assert shell.isVisible()
    assert SHELL_PDF_TO_WORD_ID in str(shell.windowTitle()) or "Word" in shell.windowTitle()
    qtbot.addWidget(shell)
    shell.close()


def test_pdf_to_word_missing_lo_blocks_run(qtbot, monkeypatch, isolated_settings, tmp_path):
    monkeypatch.setattr(
        "pagedrop.ui.pdf_to_word_shell.probe",
        lambda _cid, refresh=False: CapabilityStatus(
            id=LIBREOFFICE,
            available=False,
            reason=AbsenceReason.ENGINE_MISSING,
            detail="no soffice",
        ),
    )
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_pdf_to_word_shell(tools)
    assert shell is not None
    qtbot.addWidget(shell)
    pdf = _make_pdf(tmp_path / "in.pdf")
    shell.drop_zone.set_paths([str(pdf)])
    assert shell._run_btn.isEnabled() is False
    shell.close()


def test_pdf_to_csv_prefills_format(qtbot, isolated_settings, tmp_path):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_ocr_shell(tools, "pdf_to_csv")
    assert shell is not None
    qtbot.addWidget(shell)
    combo = getattr(shell, "_table_format_combo", None)
    assert isinstance(combo, QComboBox)
    assert combo.currentData() == "csv"
    shell.close()


def test_pdf_to_excel_prefills_format(qtbot, isolated_settings):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_ocr_shell(tools, "pdf_to_excel")
    assert shell is not None
    qtbot.addWidget(shell)
    combo = getattr(shell, "_table_format_combo", None)
    assert isinstance(combo, QComboBox)
    assert combo.currentData() == "xlsx"
    shell.close()


def test_convert_to_pdf_accepts_csv(qtbot, isolated_settings, tmp_path):
    from pagedrop.ui.native_convert_shell import open_conversion_shell

    csv_path = tmp_path / "sheet.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_conversion_shell(tools, "convert_to_pdf")
    assert shell is not None
    qtbot.addWidget(shell)
    assert shell.drop_zone._accept(str(csv_path))
    shell.close()
