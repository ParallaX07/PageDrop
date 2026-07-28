"""Annotation authoring — apply markup ops to a fitz document or new PDF path.

Viewer overlays stage ops in ``MarkupSession``; Save As applies them via
``write_pdf``. Originals are never modified.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import fitz

from pagedrop.core.jobs.errors import JobError
from pagedrop.core.jobs.paths import reject_source_overwrite
from pagedrop.core.pdf_loader import open_pdf

AnnotKind = Literal[
    "highlight",
    "underline",
    "strikeout",
    "ink",
    "rect",
    "circle",
    "line",
    "stamp",
    "freetext",
    "comment",
    "image",
]

ANNOT_KINDS: tuple[AnnotKind, ...] = (
    "highlight",
    "underline",
    "strikeout",
    "ink",
    "rect",
    "circle",
    "line",
    "stamp",
    "freetext",
    "comment",
    "image",
)

# Built-in rubber-stamp icons (PyMuPDF stamp= index).
STAMP_APPROVED = 0
STAMP_CONFIDENTIAL = 2
STAMP_DRAFT = 13
STAMP_FINAL = 6

MOVABLE_ANNOT_KINDS = frozenset({"freetext", "image"})


class AnnotationError(JobError):
    """Raised when an annotation op cannot be applied."""


@dataclass(frozen=True)
class AnnotationOp:
    """One annotation targeted at a 0-based page index in the output document."""

    kind: AnnotKind
    page_index: int
    # Geometry in unrotated PDF page space (origin top-left).
    rects: tuple[tuple[float, float, float, float], ...] = ()
    points: tuple[tuple[float, float], ...] = ()  # line: p0, p1
    strokes: tuple[tuple[tuple[float, float], ...], ...] = ()  # ink
    text: str = ""
    stamp_id: int = STAMP_APPROVED
    color: tuple[float, float, float] = (1.0, 0.92, 0.23)
    fontsize: float = 11.0
    # Free-text border (PDF appearance + viewer chrome).
    border: bool = False
    # Absolute path for kind == "image" (copied into the output PDF on Save As).
    image_path: str = ""


def _save(doc: fitz.Document, output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path, garbage=3, deflate=True)


def _rect(op: AnnotationOp) -> fitz.Rect:
    if not op.rects:
        raise AnnotationError(f"{op.kind} requires a rect")
    return fitz.Rect(*op.rects[0])


def apply_annotation_op(page: fitz.Page, op: AnnotationOp) -> fitz.Annot | None:
    """Apply a single annotation op to *page*; returns the created annot if any."""
    if op.kind == "highlight":
        if not op.rects:
            raise AnnotationError("highlight requires at least one rect")
        annot = page.add_highlight_annot([fitz.Rect(*r) for r in op.rects])
    elif op.kind == "underline":
        if not op.rects:
            raise AnnotationError("underline requires at least one rect")
        annot = page.add_underline_annot([fitz.Rect(*r) for r in op.rects])
    elif op.kind == "strikeout":
        if not op.rects:
            raise AnnotationError("strikeout requires at least one rect")
        annot = page.add_strikeout_annot([fitz.Rect(*r) for r in op.rects])
    elif op.kind == "ink":
        if not op.strokes:
            raise AnnotationError("ink requires strokes")
        # PyMuPDF wants seq of seq of float pairs (not Point objects).
        annot = page.add_ink_annot(
            [[(float(x), float(y)) for x, y in stroke] for stroke in op.strokes]
        )
    elif op.kind == "rect":
        annot = page.add_rect_annot(_rect(op))
    elif op.kind == "circle":
        annot = page.add_circle_annot(_rect(op))
    elif op.kind == "line":
        if len(op.points) < 2:
            raise AnnotationError("line requires two points")
        p0, p1 = op.points[0], op.points[1]
        annot = page.add_line_annot(fitz.Point(*p0), fitz.Point(*p1))
    elif op.kind == "stamp":
        annot = page.add_stamp_annot(_rect(op), stamp=int(op.stamp_id))
    elif op.kind == "freetext":
        # border_color requires richtext; width alone is enough for a plain border.
        annot = page.add_freetext_annot(
            _rect(op),
            op.text or " ",
            fontsize=max(4.0, float(op.fontsize) or 11.0),
            text_color=op.color,
            border_width=1.0 if op.border else 0.0,
        )
    elif op.kind == "comment":
        if op.points:
            point = fitz.Point(*op.points[0])
        elif op.rects:
            r = op.rects[0]
            point = fitz.Point(r[0], r[1])
        else:
            raise AnnotationError("comment requires a point or rect")
        annot = page.add_text_annot(point, op.text or "")
    elif op.kind == "image":
        path = (op.image_path or "").strip()
        if not path or not Path(path).is_file():
            raise AnnotationError("image requires a readable file path")
        page.insert_image(_rect(op), filename=path, keep_proportion=False)
        return None
    else:
        raise AnnotationError(f"Unknown annotation kind: {op.kind!r}")

    if op.kind in ("highlight", "underline", "strikeout", "ink", "rect", "circle", "line"):
        annot.set_colors(stroke=op.color)
    annot.update()
    return annot


def apply_annotation_ops(doc: fitz.Document, ops: Sequence[AnnotationOp]) -> None:
    """Apply *ops* in order to *doc* (mutates; caller saves)."""
    for op in ops:
        if op.page_index < 0 or op.page_index >= doc.page_count:
            raise AnnotationError(
                f"Page index {op.page_index} out of range ({doc.page_count} pages)"
            )
        apply_annotation_op(doc[op.page_index], op)


def add_annotations(
    source_pdf: str,
    output_path: str,
    ops: Sequence[AnnotationOp],
    *,
    password: str | None = None,
) -> None:
    """Copy *source_pdf* to *output_path* with *ops* applied. Source unchanged."""
    reject_source_overwrite(output_path, source_pdf)
    if not ops:
        raise AnnotationError("No annotation operations to apply")
    doc = open_pdf(source_pdf, password=password)
    try:
        apply_annotation_ops(doc, ops)
        _save(doc, output_path)
    finally:
        doc.close()


def list_annotation_summaries(
    source_pdf: str,
    *,
    password: str | None = None,
) -> list[tuple[int, str, str]]:
    """Return ``(page_index, type_name, content)`` for each annotation."""
    doc = open_pdf(source_pdf, password=password)
    try:
        rows: list[tuple[int, str, str]] = []
        for i, page in enumerate(doc):
            for annot in page.annots() or []:
                type_name = annot.type[1] if annot.type else "Unknown"
                content = (annot.info or {}).get("content") or ""
                rows.append((i, type_name, content))
        return rows
    finally:
        doc.close()
