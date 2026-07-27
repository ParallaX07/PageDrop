"""Phase 29 — table extract (find_tables → CSV / JSON / XLSX)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz
import pytest

from pagedrop.core import native_conversions as nc
from pagedrop.core.capabilities import OPENPYXL, clear_cache
from pagedrop.core.jobs.errors import BackendUnavailableError


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_table_pdf(path: Path) -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        rows, cols = 3, 2
        x0, y0, cw, ch = 50, 50, 120, 40
        cells = [["Name", "Age"], ["Ada", "36"], ["Bob", "42"]]
        for r in range(rows + 1):
            y = y0 + r * ch
            page.draw_line((x0, y), (x0 + cols * cw, y))
        for c in range(cols + 1):
            x = x0 + c * cw
            page.draw_line((x, y0), (x, y0 + rows * ch))
        for r in range(rows):
            for c in range(cols):
                page.insert_text(
                    (x0 + c * cw + 8, y0 + r * ch + 24),
                    cells[r][c],
                    fontsize=12,
                )
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_tables_csv_and_json(tmp_path):
    source = _make_table_pdf(tmp_path / "table.pdf")
    before = _file_hash(source)

    csv_out = tmp_path / "t.csv"
    written = nc.export_pdf(source, csv_out, format_id="csv")
    text = written[0].read_text(encoding="utf-8")
    assert "Ada" in text and "36" in text

    json_out = tmp_path / "t.json"
    written_j = nc.export_pdf(source, json_out, format_id="tables_json")
    payload = json.loads(written_j[0].read_text(encoding="utf-8"))
    assert payload["source"] == "table.pdf"
    assert payload["tables"]
    flat = " ".join(
        str(cell)
        for table in payload["tables"]
        for row in table["rows"]
        for cell in row
    )
    assert "Ada" in flat and "Bob" in flat
    assert _file_hash(source) == before


def test_tables_xlsx_requires_openpyxl_when_absent(tmp_path, monkeypatch):
    clear_cache()

    class _Absent:
        available = False
        reason = None
        detail = "missing"
        id = OPENPYXL

    monkeypatch.setattr(
        "pagedrop.core.native_conversions.probe",
        lambda capability_id, refresh=False: _Absent()
        if capability_id == OPENPYXL
        else type("P", (), {"available": True, "reason": None, "detail": ""})(),
    )
    source = _make_table_pdf(tmp_path / "table.pdf")
    with pytest.raises(BackendUnavailableError) as excinfo:
        nc.export_pdf(source, tmp_path / "out.xlsx", format_id="xlsx")
    assert excinfo.value.capability_id == OPENPYXL
