"""Phase 28 UI — modify tool shells, blank confirm, raster warning."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from pagedrop.core.modify_ops import RASTER_EFFECT_WARNING
from pagedrop.ui.modify_tools_shell import SHELL_MODIFY_IDS, open_modify_shell
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow


def _write_pdf(path: Path, *, text: str = "hello", pages: int = 1) -> None:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=200, height=200)
            if text:
                page.insert_text((40, 80), text if pages == 1 else f"{text}{i}", fontsize=14)
        doc.save(str(path))
    finally:
        doc.close()


def test_modify_tiles_open_shells(qtbot, isolated_settings):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    by_id = {t.entry.id: t.entry for t in tools._tiles}
    for tool_id in SHELL_MODIFY_IDS:
        assert tool_id in by_id
        assert by_id[tool_id].action == "modify"
        assert not by_id[tool_id].coming_soon
        shell = open_modify_shell(tools, tool_id)
        assert shell is not None
        assert isinstance(shell, ToolShellWindow)
        assert shell.isVisible()
        qtbot.addWidget(shell)
        shell.close()
    tools.close()


def test_watermark_shell_has_diagonal_and_position_controls(qtbot, isolated_settings):
    from PyQt6.QtWidgets import QCheckBox, QDoubleSpinBox, QScrollArea, QToolButton

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "watermark")
    assert shell is not None
    qtbot.addWidget(shell)
    # Options live in a scroll area so dense forms don't crush when window is small.
    assert isinstance(shell._options_scroll, QScrollArea)
    host = shell._options_host

    spins = host.findChildren(QDoubleSpinBox)
    assert any(s.suffix().strip() == "%" for s in spins)
    assert any(s.suffix() == "°" for s in spins)
    pos_buttons = [b for b in host.findChildren(QToolButton) if b.isCheckable()]
    assert len(pos_buttons) == 9
    assert any(b.isChecked() and b.toolTip() == "Center" for b in pos_buttons)
    assert any(
        isinstance(c, QCheckBox) and "Flatten" in c.text()
        for c in host.findChildren(QCheckBox)
    )
    # Unrelated image/font-size rows stay hidden in the default text+diagonal mode.
    shell.resize(560, 480)
    qtbot.wait(20)
    assert shell._options_scroll.viewport().height() > 0
    tools.close()


def test_blank_remove_requires_confirm(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    pdf = tmp_path / "mixed.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), "keep", fontsize=14)
        doc.save(str(pdf))
    finally:
        doc.close()

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "blank_pages")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(pdf)])

    # Force the confirm path (bypass PAGEDROP_TESTING short-circuit).
    confirmed: list[tuple[int, int]] = []

    def fake_confirm(parent, *, blank_count, page_count, heuristic_hint):
        confirmed.append((blank_count, page_count))
        assert "heuristic" in heuristic_hint.casefold() or "coverage" in heuristic_hint.casefold() or "text" in heuristic_hint.casefold()
        return False

    monkeypatch.setattr(
        "pagedrop.ui.modify_tools_shell.confirm_remove_blank_pages",
        fake_confirm,
    )
    save_called = {"n": 0}

    def fake_save(*_a, **_k):
        save_called["n"] += 1
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)

    shell._run_btn.click()
    assert confirmed == [(1, 2)]
    assert save_called["n"] == 0
    tools.close()


def test_raster_effect_warning_copy(qtbot, isolated_settings):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "color_effects")
    assert shell is not None
    qtbot.addWidget(shell)

    effect = shell._color_effect  # type: ignore[attr-defined]
    warning = shell._color_warning  # type: ignore[attr-defined]
    # Select invert (index 1).
    effect.setCurrentIndex(1)
    assert effect.currentData() == "invert"
    assert RASTER_EFFECT_WARNING in warning.text()
    assert "raster" in warning.text().casefold()
    tools.close()


def test_invert_run_shows_raster_warning_dialog(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    pdf = tmp_path / "src.pdf"
    _write_pdf(pdf)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "color_effects")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(pdf)])
    shell._color_effect.setCurrentIndex(1)  # type: ignore[attr-defined]

    warned: list[str] = []

    def fake_warning(parent, title, text, *args, **kwargs):
        warned.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    save_called = {"n": 0}

    def fake_save(*_a, **_k):
        save_called["n"] += 1
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)

    shell._run_btn.click()
    assert any(RASTER_EFFECT_WARNING in t for t in warned)
    assert save_called["n"] == 0
    tools.close()
