"""Unsaved editor work survives an unclean process exit."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core.annotations import AnnotationOp
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.utils.temp_manager import TempManager


def test_markup_draft_round_trip(qtbot, five_page_pdf: Path, tmp_path: Path) -> None:
    recovery_dir = tmp_path / "recovery"
    first_temp = TempManager()
    first = PdfTab(first_temp, recovery_dir=recovery_dir)
    qtbot.addWidget(first)
    first.load_pdf(str(five_page_pdf))
    assert first.edit_model is not None
    first.markup_session.push_annotation(
        AnnotationOp(
            kind="ink",
            page_index=2,
            strokes=(((20.0, 20.0), (30.0, 40.0), (50.0, 45.0)),),
        ),
        first.edit_model.instance_id_at(2),
    )
    first.markup_session.push_annotation(
        AnnotationOp(
            kind="rect",
            page_index=4,
            rects=((20.0, 30.0, 80.0, 100.0),),
        ),
        first.edit_model.instance_id_at(4),
    )
    first._on_markup_changed()

    draft = first.recovery_path
    assert draft is not None and draft.is_file()

    restored_temp = TempManager()
    restored = PdfTab(restored_temp, recovery_dir=recovery_dir)
    qtbot.addWidget(restored)
    restored.restore_recovery_draft(draft)

    assert restored.is_dirty
    assert restored.edit_model is not None
    assert restored.edit_model.logical_count() == 5
    recovered_ops = [entry.annotation for entry in restored.peek_markup_ops()]
    assert [op.kind for op in recovered_ops if op is not None] == ["ink", "rect"]
    assert recovered_ops == [entry.annotation for entry in first.peek_markup_ops()]


def test_clean_close_removes_recovery_draft(
    qtbot, five_page_pdf: Path, tmp_path: Path
) -> None:
    temp = TempManager()
    tab = PdfTab(temp, recovery_dir=tmp_path / "recovery")
    qtbot.addWidget(tab)
    tab.load_pdf(str(five_page_pdf))
    assert tab.edit_model is not None
    tab.markup_session.push_annotation(
        AnnotationOp(kind="rect", page_index=0, rects=((10, 10, 40, 40),)),
        tab.edit_model.instance_id_at(0),
    )
    tab._on_markup_changed()
    draft = tab.recovery_path
    assert draft is not None and draft.exists()

    tab.close_loader()
    assert not draft.exists()
