"""Pending viewer markup — annotations, forms, and redaction marks with undo/redo.

Annotation / form ops are applied on Save As (via ``write_pdf``).
Redaction marks are applied only through the dedicated redaction export
(``pagedrop.core.redact``) — never via ordinary Save As.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pagedrop.core.annotations import AnnotationOp, apply_annotation_ops
from pagedrop.core.forms import (
    FormCreateOp,
    apply_form_creates,
    apply_form_fill,
    apply_form_flatten,
)
from pagedrop.core.pdf_editor import MAX_UNDO
from pagedrop.core.redact import RedactionRegion

if TYPE_CHECKING:
    import fitz

MarkupKind = Literal[
    "annotation", "form_fill", "form_create", "form_flatten", "redaction"
]

# ponytail: undo depth shares PdfEditModel.MAX_UNDO (50). Each entry is a
# pending markup op; raise only with measured memory pain (or coalescing).


@dataclass(frozen=True)
class MarkupEntry:
    kind: MarkupKind
    annotation: AnnotationOp | None = None
    form_fill: Mapping[str, str] | None = None
    form_create: FormCreateOp | None = None
    redaction: RedactionRegion | None = None


class MarkupSession:
    """Stack of pending markup ops for one editor tab."""

    def __init__(self) -> None:
        self._ops: list[MarkupEntry] = []
        self._redo: list[MarkupEntry] = []

    def ops(self) -> list[MarkupEntry]:
        return list(self._ops)

    def is_dirty(self) -> bool:
        return bool(self._ops)

    def can_undo(self) -> bool:
        return bool(self._ops)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear(self) -> None:
        self._ops.clear()
        self._redo.clear()

    def push_annotation(self, op: AnnotationOp) -> None:
        self._push(MarkupEntry(kind="annotation", annotation=op))

    def replace_annotation(self, old: AnnotationOp, new: AnnotationOp) -> bool:
        """Replace a pending annotation in place (edit free text, etc.)."""
        for i, entry in enumerate(self._ops):
            if entry.kind == "annotation" and entry.annotation == old:
                self._ops[i] = MarkupEntry(kind="annotation", annotation=new)
                self._redo.clear()
                return True
        return False

    def remove_annotation(self, op: AnnotationOp) -> bool:
        """Remove a pending annotation (Delete on a selected text/image box)."""
        for i, entry in enumerate(self._ops):
            if entry.kind == "annotation" and entry.annotation == op:
                if i == len(self._ops) - 1:
                    return self.undo()
                self._ops.pop(i)
                self._redo.clear()
                return True
        return False

    def push_form_fill(self, values: Mapping[str, str]) -> None:
        self._push(MarkupEntry(kind="form_fill", form_fill=dict(values)))

    def push_form_create(self, field: FormCreateOp) -> None:
        self._push(MarkupEntry(kind="form_create", form_create=field))

    def push_form_flatten(self) -> None:
        self._push(MarkupEntry(kind="form_flatten"))

    def push_redaction(self, region: RedactionRegion) -> None:
        self._push(MarkupEntry(kind="redaction", redaction=region))

    def redaction_regions(self) -> list[RedactionRegion]:
        return [
            entry.redaction
            for entry in self._ops
            if entry.kind == "redaction" and entry.redaction is not None
        ]

    def non_redaction_ops(self) -> list[MarkupEntry]:
        """Annotation / form entries only (safe for ordinary Save As)."""
        return [entry for entry in self._ops if entry.kind != "redaction"]

    def clear_redactions(self) -> None:
        self._ops = [entry for entry in self._ops if entry.kind != "redaction"]
        self._redo.clear()

    def clear_non_redactions(self) -> None:
        """Drop annotation/form ops after Save As; keep pending redaction marks."""
        self._ops = [entry for entry in self._ops if entry.kind == "redaction"]
        self._redo.clear()

    def undo(self) -> bool:
        if not self._ops:
            return False
        self._redo.append(self._ops.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._ops.append(self._redo.pop())
        return True

    def _push(self, entry: MarkupEntry) -> None:
        self._ops.append(entry)
        self._redo.clear()
        if len(self._ops) > MAX_UNDO:
            del self._ops[0 : len(self._ops) - MAX_UNDO]


def apply_markup_entries(doc: fitz.Document, entries: Sequence[MarkupEntry]) -> None:
    """Apply pending annotation/form markup to an assembled document (mutates *doc*).

    Redaction entries are skipped here — they require ``redact_document`` /
    ``redact_pdf`` (GC rewrite + fresh-process verify).
    """
    annot_batch: list[AnnotationOp] = []

    def flush_annots() -> None:
        nonlocal annot_batch
        if annot_batch:
            apply_annotation_ops(doc, annot_batch)
            annot_batch = []

    for entry in entries:
        if entry.kind == "redaction":
            continue
        if entry.kind == "annotation":
            assert entry.annotation is not None
            annot_batch.append(entry.annotation)
            continue
        flush_annots()
        if entry.kind == "form_fill":
            assert entry.form_fill is not None
            apply_form_fill(doc, entry.form_fill)
        elif entry.kind == "form_create":
            assert entry.form_create is not None
            apply_form_creates(doc, [entry.form_create])
        elif entry.kind == "form_flatten":
            apply_form_flatten(doc)
        else:
            raise ValueError(f"Unknown markup kind: {entry.kind!r}")
    flush_annots()
