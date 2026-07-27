"""Phase 29 UI — OCR tile capability gate + configure dialog."""

from __future__ import annotations

from pagedrop.core.capabilities import (
    TESSDATA,
    AbsenceReason,
    CapabilityStatus,
    clear_cache,
)
from pagedrop.ui.dialogs import build_missing_tessdata_dialog
from pagedrop.ui.ocr_shell import SHELL_OCR_IDS, open_ocr_shell
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow


def test_ocr_tile_blocked_when_tessdata_absent(monkeypatch, qtbot, isolated_settings):
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
    tile = by_id["ocr_pdf"]
    assert tile.is_blocked()
    assert "Data missing" in tile._subtitle.text()
    assert by_id["extract_tables"].entry.action == "extract_tables"
    assert not by_id["extract_tables"].is_blocked()
    window.close()


def test_missing_tessdata_dialog_has_download_configure_recheck():
    dialog = build_missing_tessdata_dialog(None, subject="OCR", detail="none found")
    names = {b.objectName() for b in dialog.buttons() if b.objectName()}
    assert "tess_recheck" in names
    assert "tess_download" in names
    assert "tess_configure" in names
    assert "Language data missing" in dialog.text()


def test_ocr_and_tables_shells_open(qtbot, isolated_settings):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    for tool_id in sorted(SHELL_OCR_IDS):
        shell = open_ocr_shell(tools, tool_id)
        assert shell is not None
        assert isinstance(shell, ToolShellWindow)
        assert shell.isVisible()
        qtbot.addWidget(shell)
        shell.close()
    tools.close()
