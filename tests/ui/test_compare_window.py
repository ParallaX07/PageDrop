"""Side-by-side Compare window UI tests."""

from __future__ import annotations

from pathlib import Path

import fitz

from pagedrop.ui.compare_window import CompareWindow
from pagedrop.ui.organize_tools import launch_organize_tool
from pagedrop.ui.tools_window import ToolsWindow


def _write_line_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 260), text, fontsize=10)
        doc.save(str(path))
    finally:
        doc.close()


def test_tools_tile_opens_compare_window(qtbot):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.show()

    launch_organize_tool(tools, "compare")
    window = getattr(tools, "_compare_window", None)
    assert isinstance(window, CompareWindow)
    qtbot.waitUntil(lambda: window.isVisible(), timeout=3000)
    window.close()
    tools.close()


def test_compare_window_lists_deleted_text(qtbot, tmp_path: Path):
    a = tmp_path / "full.pdf"
    b = tmp_path / "short.pdf"
    long_line = (
        "Tech Stack: Electron 30, React 18, Express 5, SQLite, Drizzle ORM, "
        "Zustand, TanStack Query, Tailwind CSS v4, shadcn/ui"
    )
    short_line = "Tech Stack: Electron 30, React 18, Express 5, SQLite, Drizzle ORM,"
    _write_line_pdf(a, long_line)
    _write_line_pdf(b, short_line)

    window = CompareWindow()
    qtbot.addWidget(window)
    window.show()
    window._row_a.set_text(str(a))
    window._row_b.set_text(str(b))
    window._run_compare()

    assert window._report is not None
    assert window._report.deleted_count == 1
    assert window._change_list.count() == 1
    item = window._change_list.item(0)
    assert "Removed" in item.text()
    assert "Zustand" in item.text()

    # Selecting the change jumps to page 1 and paints a highlight on A.
    window._change_list.setCurrentRow(0)
    assert window._page_index == 0
    highlights = window._highlights_for_page("a", 0)
    assert highlights
    assert any(r[1] <= 260 <= r[3] for r, _color in highlights)

    window.close()
