"""Phase 17 unit tests — PdfMergeModel."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core.pdf_merge import PdfMergeModel


def _touch_pdfs(tmp_path, names: list[str]) -> list[Path]:
    paths = [tmp_path / f"{name}.pdf" for name in names]
    for path in paths:
        path.touch()
    return paths


def test_add_remove_reorder_paths(tmp_path):
    paths = _touch_pdfs(tmp_path, ["a", "b", "c"])
    model = PdfMergeModel()

    model.add_files([str(p) for p in paths])
    assert model.file_count() == 3
    assert [Path(p).name for p in model.all_paths()] == ["a.pdf", "b.pdf", "c.pdf"]

    model.remove_at(1)
    assert model.file_count() == 2
    assert Path(model.path_at(0)).name == "a.pdf"
    assert Path(model.path_at(1)).name == "c.pdf"

    model.reorder(1, 0)
    assert Path(model.path_at(0)).name == "c.pdf"
    assert Path(model.path_at(1)).name == "a.pdf"


def test_move_up_down_at_bounds(tmp_path):
    paths = _touch_pdfs(tmp_path, ["a", "b", "c"])
    model = PdfMergeModel()
    model.add_files([str(p) for p in paths])
    original = model.all_paths()

    model.move_up([0])
    assert model.all_paths() == original

    model.move_down([2])
    assert model.all_paths() == original

    model.move_up([1])
    assert Path(model.path_at(0)).name == "b.pdf"
    assert Path(model.path_at(1)).name == "a.pdf"
    assert Path(model.path_at(2)).name == "c.pdf"

    model.move_down([0])
    assert Path(model.path_at(0)).name == "a.pdf"
    assert Path(model.path_at(1)).name == "b.pdf"
    assert Path(model.path_at(2)).name == "c.pdf"


def test_path_at_returns_resolved_path(tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.touch()
    model = PdfMergeModel()
    model.add_files([str(pdf)])
    assert Path(model.path_at(0)).name == "report.pdf"
    model.clear()
    assert model.file_count() == 0
