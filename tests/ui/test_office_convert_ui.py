"""Phase 26 UI — Office to PDF modeless shell."""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel, QPushButton

from pagedrop.core.backends.office import OfficeCapabilityReport
from pagedrop.core.capabilities import (
    LIBREOFFICE,
    OFFICE_COM,
    AbsenceReason,
    CapabilityStatus,
    clear_cache,
)
from pagedrop.ui.dialogs import build_missing_libreoffice_dialog
from pagedrop.ui.office_convert_window import (
    SHELL_OFFICE_ID,
    open_office_convert_shell,
)
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow


def _report(*, com: bool = False, lo: bool = False) -> OfficeCapabilityReport:
    return OfficeCapabilityReport(
        com=(
            CapabilityStatus(
                id=OFFICE_COM,
                available=True,
                detail="ok",
                extras={"apps": ["word"]},
            )
            if com
            else CapabilityStatus(
                id=OFFICE_COM,
                available=False,
                reason=AbsenceReason.ENGINE_MISSING,
                detail="no",
            )
        ),
        libreoffice=(
            CapabilityStatus(
                id=LIBREOFFICE,
                available=True,
                detail="ok",
                extras={"path": "/usr/bin/soffice"},
            )
            if lo
            else CapabilityStatus(
                id=LIBREOFFICE,
                available=False,
                reason=AbsenceReason.ENGINE_MISSING,
                detail="no",
            )
        ),
        preferred="auto",
        soffice_path=None,
    )


def test_office_tile_opens_modeless_shell(qtbot, isolated_settings):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_office_convert_shell(tools)
    assert shell is not None
    assert isinstance(shell, ToolShellWindow)
    assert shell.isVisible()
    qtbot.addWidget(shell)
    shell.close()


def test_office_tile_not_coming_soon(qtbot, isolated_settings):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    by_id = {t.entry.id: t.entry for t in window._tiles}
    assert SHELL_OFFICE_ID in by_id
    assert by_id[SHELL_OFFICE_ID].action == "office_to_pdf"
    assert not by_id[SHELL_OFFICE_ID].coming_soon
    window.close()


def test_preflight_shows_backend_status(qtbot, monkeypatch, isolated_settings):
    monkeypatch.setattr(
        "pagedrop.ui.office_convert_window.capability_report",
        lambda **_k: _report(com=True, lo=True),
    )
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_office_convert_shell(tools)
    assert shell is not None
    qtbot.addWidget(shell)
    label = getattr(shell, "_backend_status_label", None)
    assert isinstance(label, QLabel)
    text = label.text()
    assert "Microsoft Office" in text
    assert "LibreOffice" in text


def test_run_disabled_without_backend(qtbot, tmp_path, monkeypatch, isolated_settings):
    monkeypatch.setattr(
        "pagedrop.ui.office_convert_window.capability_report",
        lambda **_k: _report(com=False, lo=False),
    )
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_office_convert_shell(tools)
    assert shell is not None
    qtbot.addWidget(shell)

    doc = tmp_path / "note.docx"
    doc.write_bytes(b"docx")
    shell.drop_zone.set_paths([str(doc)])
    assert not shell._run_btn.isEnabled()

    # Configure CTA present
    configure = shell.findChildren(QPushButton)
    assert any(b.text() == "Configure…" for b in configure)


def test_missing_lo_dialog_has_download_and_recheck(qtbot):
    host = ToolsWindow()
    qtbot.addWidget(host)
    dialog = build_missing_libreoffice_dialog(host, subject="Office to PDF")
    names = {b.objectName() for b in dialog.buttons() if b.objectName()}
    assert "lo_recheck" in names
    assert "lo_download" in names
    dialog.close()


def test_status_names_backend_used(qtbot, monkeypatch, isolated_settings):
    monkeypatch.setattr(
        "pagedrop.ui.office_convert_window.capability_report",
        lambda **_k: _report(lo=True),
    )
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_office_convert_shell(tools)
    assert shell is not None
    qtbot.addWidget(shell)
    # Idle status mentions preferred / ready once backends exist
    msg = shell.statusBar().currentMessage()
    assert "LibreOffice" in msg or "Ready" in msg or "preferred" in msg.lower()
    clear_cache()
