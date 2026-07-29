"""Phase 30 — annotation authoring core."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core.annotations import (
    ANNOT_KINDS,
    AnnotationError,
    AnnotationOp,
    add_annotations,
    list_annotation_summaries,
)
from pagedrop.core.jobs.errors import SourceOverwriteError
from pagedrop.core.markup import MarkupSession
from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_writer import write_pdf
from pagedrop.ui.pdf_viewer import _apply_box_transform


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_pdf(path: Path, text: str = "Hello world") -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 80), text, fontsize=14)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def _make_png(path: Path) -> Path:
    # Minimal valid 1×1 PNG (no Pillow dependency).
    path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
            "de0000000c4944415408d763f8ffff3f0005fe02fea75a86c00000000049454e44ae426082"
        )
    )
    return path


def test_all_annot_kinds_persist_source_unchanged(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    png = _make_png(tmp_path / "mark.png")
    source_hash = _file_hash(src)
    out = tmp_path / "ann.pdf"
    ops = [
        AnnotationOp(kind="highlight", page_index=0, rects=((40, 60, 120, 90),)),
        AnnotationOp(kind="underline", page_index=0, rects=((40, 60, 120, 90),)),
        AnnotationOp(kind="strikeout", page_index=0, rects=((40, 60, 120, 90),)),
        AnnotationOp(kind="ink", page_index=0, strokes=(((50, 300), (80, 280), (110, 310)),)),
        AnnotationOp(kind="rect", page_index=0, rects=((20, 20, 80, 60),), color=(1, 0, 0)),
        AnnotationOp(kind="circle", page_index=0, rects=((100, 20, 160, 60),)),
        AnnotationOp(kind="line", page_index=0, points=((20, 350), (200, 350))),
        AnnotationOp(kind="stamp", page_index=0, rects=((150, 150, 250, 190),)),
        AnnotationOp(kind="freetext", page_index=0, rects=((40, 200, 180, 240),), text="Note"),
        AnnotationOp(kind="comment", page_index=0, points=((250, 50),), text="Comment"),
        AnnotationOp(
            kind="image",
            page_index=0,
            rects=((40, 260, 120, 320),),
            image_path=str(png),
        ),
    ]
    assert {op.kind for op in ops} == set(ANNOT_KINDS)
    add_annotations(str(src), str(out), ops)
    assert _file_hash(src) == source_hash
    summaries = list_annotation_summaries(str(out))
    # Image is page content, not an annotation dictionary entry.
    assert len(summaries) == len(ops) - 1
    doc = fitz.open(str(out))
    try:
        assert doc[0].get_images()
    finally:
        doc.close()
    with pytest.raises(SourceOverwriteError):
        add_annotations(str(src), str(src), ops[:1])


def test_highlight_survives_write_pdf_markup(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    source_hash = _file_hash(src)
    model = PdfEditModel(str(src), 1)
    session = MarkupSession()
    session.push_annotation(
        AnnotationOp(kind="highlight", page_index=0, rects=((40, 60, 120, 90),))
    )
    assert session.is_dirty()
    assert session.can_undo()
    out = tmp_path / "saved.pdf"
    write_pdf(model, str(out), markup=session.ops())
    assert _file_hash(src) == source_hash
    types = [t for _, t, _ in list_annotation_summaries(str(out))]
    assert "Highlight" in types

    session.undo()
    assert not session.is_dirty()
    session.redo()
    assert session.is_dirty()


def test_underline_strikeout_color_and_freetext_border(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", "Line one")
    out = tmp_path / "marked.pdf"
    red = (0.9, 0.1, 0.1)
    ops = [
        AnnotationOp(
            kind="underline", page_index=0, rects=((40, 64, 120, 84),), color=red
        ),
        AnnotationOp(
            kind="strikeout", page_index=0, rects=((40, 64, 120, 84),), color=red
        ),
        AnnotationOp(
            kind="freetext",
            page_index=0,
            rects=((40, 200, 200, 240),),
            text="Bordered",
            color=(0.0, 0.0, 0.5),
            fontsize=18.0,
            border=True,
        ),
        AnnotationOp(
            kind="freetext",
            page_index=0,
            rects=((40, 250, 200, 290),),
            text="No border",
            border=False,
        ),
    ]
    add_annotations(str(src), str(out), ops)
    types = [t for _, t, _ in list_annotation_summaries(str(out))]
    assert "Underline" in types
    assert "StrikeOut" in types or "Strikeout" in types
    doc = fitz.open(str(out))
    try:
        fretexts = [
            a for a in doc[0].annots() or [] if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT
        ]
        assert len(fretexts) == 2
        contents = {(a.info or {}).get("content") for a in fretexts}
        assert "Bordered" in contents
        assert "No border" in contents
    finally:
        doc.close()


def test_markup_session_replace_annotation() -> None:
    session = MarkupSession()
    old = AnnotationOp(
        kind="freetext",
        page_index=0,
        rects=((10, 10, 80, 40),),
        text="Old",
        fontsize=11.0,
    )
    session.push_annotation(old)
    new = AnnotationOp(
        kind="freetext",
        page_index=0,
        rects=((20, 30, 120, 70),),
        text="New",
        color=(0.2, 0.2, 0.2),
        fontsize=16.0,
        border=True,
    )
    assert session.replace_annotation(old, new)
    assert session.ops()[0].annotation == new
    assert not session.replace_annotation(old, new)


def test_markup_session_remove_annotation() -> None:
    session = MarkupSession()
    a = AnnotationOp(kind="freetext", page_index=0, rects=((0, 0, 40, 20),), text="A")
    b = AnnotationOp(
        kind="image", page_index=0, rects=((50, 50, 100, 100),), image_path="/x.png"
    )
    session.push_annotation(a)
    session.push_annotation(b)
    assert session.remove_annotation(b)
    assert len(session.ops()) == 1
    assert session.ops()[0].annotation == a
    assert session.can_redo()
    assert session.redo()
    assert session.ops()[-1].annotation == b
    assert session.remove_annotation(a)
    assert [e.annotation for e in session.ops()] == [b]


def test_markup_session_undo_capped_at_max_undo() -> None:
    """O16: MarkupSession shares PdfEditModel.MAX_UNDO depth."""
    from pagedrop.core.pdf_editor import MAX_UNDO

    session = MarkupSession()
    for i in range(MAX_UNDO + 1):
        session.push_annotation(
            AnnotationOp(
                kind="freetext",
                page_index=0,
                rects=((0, 0, 10, 10),),
                text=str(i),
            )
        )
    ops = session.ops()
    assert len(ops) == MAX_UNDO
    assert ops[0].annotation is not None
    assert ops[0].annotation.text == "1"
    assert ops[-1].annotation is not None
    assert ops[-1].annotation.text == str(MAX_UNDO)


def test_apply_box_transform_move_and_resize() -> None:
    moved = _apply_box_transform((10, 20, 50, 60), "move", 5, -3)
    assert moved == (15, 17, 55, 57)
    se = _apply_box_transform((10, 20, 50, 60), "se", 10, 10)
    assert se == (10, 20, 60, 70)
    nw = _apply_box_transform((10, 20, 50, 60), "nw", 5, 5)
    assert nw[0] == 15 and nw[1] == 25


def test_merge_char_rects_joins_same_line() -> None:
    from pagedrop.ui.pdf_viewer import _merge_char_rects

    merged = _merge_char_rects(
        [
            (10.0, 20.0, 15.0, 30.0),
            (15.5, 20.0, 22.0, 30.0),
            (10.0, 40.0, 18.0, 50.0),
        ]
    )
    assert len(merged) == 2
    assert merged[0][0] == 10.0
    assert merged[0][2] == 22.0
    assert merged[1][1] == 40.0


def test_annotation_op_validation(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    out = tmp_path / "bad.pdf"
    with pytest.raises(AnnotationError):
        add_annotations(str(src), str(out), [])
    with pytest.raises(AnnotationError):
        add_annotations(
            str(src),
            str(out),
            [AnnotationOp(kind="highlight", page_index=0, rects=())],
        )
    with pytest.raises(AnnotationError):
        add_annotations(
            str(src),
            str(out),
            [AnnotationOp(kind="highlight", page_index=9, rects=((0, 0, 10, 10),))],
        )
    with pytest.raises(AnnotationError):
        add_annotations(
            str(src),
            str(out),
            [
                AnnotationOp(
                    kind="image",
                    page_index=0,
                    rects=((0, 0, 40, 40),),
                    image_path=str(tmp_path / "missing.png"),
                )
            ],
        )
