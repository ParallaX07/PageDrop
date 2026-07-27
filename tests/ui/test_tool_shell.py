"""Phase 22b — shared modeless tool shell."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QFileDialog

from pagedrop.ui.organize_tools import launch_organize_tool
from pagedrop.ui.tool_shell import (
    SHELL_ORGANIZE_IDS,
    FileDropZone,
    ToolShellWindow,
    open_organize_shell,
)
from pagedrop.ui.tools_window import ToolsWindow


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
