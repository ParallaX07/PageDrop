"""Pending viewer markup — annotations, forms, and redaction marks with undo/redo.

Annotation / form ops are applied on Save As (via ``write_pdf``).
Redaction marks are applied on Save As via ``redact_edit_model`` (GC rewrite +
fresh-process verify) — never via ordinary ``write_pdf``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from pagedrop.core.annotations import AnnotationOp, apply_annotation_ops
from pagedrop.core.forms import (
    FormCreateOp,
    apply_form_creates,
    apply_form_fill,
    apply_form_flatten,
)
from pagedrop.core.pdf_editor import MAX_UNDO
from pagedrop.core.pdf_editor import PdfEditModel
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
    description: str = ""
    affected_count: int = 1
    # Page-scoped work remains attached to this logical occurrence until output.
    page_instance_id: str | None = None
    annotation: AnnotationOp | None = None
    form_fill: Mapping[str, str] | None = None
    form_create: FormCreateOp | None = None
    redaction: RedactionRegion | None = None


class MarkupSession:
    """Stack of pending markup ops for one editor tab."""

    def __init__(self) -> None:
        self._ops: list[MarkupEntry] = []
        self._redo: list[MarkupEntry] = []
        self._model: PdfEditModel | None = None

    def bind_model(self, model: PdfEditModel | None) -> None:
        """Bind UI authoring to the current tab's logical page occurrences."""
        self._model = model

    def _target_id(self, page_index: int, page_instance_id: str | None) -> str | None:
        if page_instance_id is not None:
            return page_instance_id
        if self._model is None or not 0 <= page_index < self._model.logical_count():
            return None
        return self._model.instance_id_at(page_index)

    def ops(self, model: PdfEditModel | None = None) -> list[MarkupEntry]:
        """Pending work, omitting work whose page was deleted from *model*."""
        if model is None:
            return list(self._ops)
        return [
            entry
            for entry in self._ops
            if entry.page_instance_id is None
            or model.logical_index_for_instance(entry.page_instance_id) is not None
        ]

    def is_dirty(self, model: PdfEditModel | None = None) -> bool:
        return bool(self.ops(model))

    def can_undo(self) -> bool:
        return bool(self._ops)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_description(self) -> str | None:
        return self._ops[-1].description if self._ops else None

    def redo_description(self) -> str | None:
        return self._redo[-1].description if self._redo else None

    def clear(self) -> None:
        self._ops.clear()
        self._redo.clear()

    def push_annotation(self, op: AnnotationOp, page_instance_id: str | None = None) -> None:
        self._push(MarkupEntry(kind="annotation", description=f"add {op.kind}", page_instance_id=self._target_id(op.page_index, page_instance_id), annotation=op))

    def replace_annotation(self, old: AnnotationOp, new: AnnotationOp) -> bool:
        """Replace a pending annotation in place (edit free text, etc.)."""
        for i, entry in enumerate(self._ops):
            if entry.kind == "annotation" and entry.annotation == old:
                self._ops[i] = replace(entry, annotation=new)
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
        self._push(MarkupEntry(kind="form_fill", description="fill form", affected_count=len(values), form_fill=dict(values)))

    def push_form_create(self, field: FormCreateOp, page_instance_id: str | None = None) -> None:
        self._push(MarkupEntry(kind="form_create", description="add form field", page_instance_id=self._target_id(field.page_index, page_instance_id), form_create=field))

    def push_form_flatten(self) -> None:
        self._push(MarkupEntry(kind="form_flatten", description="flatten forms"))

    def push_redaction(self, region: RedactionRegion, page_instance_id: str | None = None) -> None:
        self._push(MarkupEntry(kind="redaction", description="add redaction mark", page_instance_id=self._target_id(region.page_index, page_instance_id), redaction=region))

    def redaction_regions(self, model: PdfEditModel | None = None) -> list[RedactionRegion]:
        if model is None:
            return [
                entry.redaction
                for entry in self._ops
                if entry.kind == "redaction" and entry.redaction is not None
            ]
        return [
            entry.redaction
            for entry in resolve_markup_entries(self.ops(model), model)
            if entry.kind == "redaction" and entry.redaction is not None
        ]

    def non_redaction_ops(self, model: PdfEditModel | None = None) -> list[MarkupEntry]:
        """Annotation / form entries only (safe for ordinary Save As)."""
        return [entry for entry in self.ops(model) if entry.kind != "redaction"]

    def entries_for_instance(self, instance_id: str) -> list[MarkupEntry]:
        """Overlay entries for one live page occurrence."""
        return [entry for entry in self._ops if entry.page_instance_id == instance_id]

    def annotation_instance_id(self, op: AnnotationOp) -> str | None:
        return next(
            (entry.page_instance_id for entry in self._ops if entry.annotation == op),
            None,
        )

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


class MarkupTargetError(ValueError):
    """A page-scoped pending operation has no live page occurrence."""


def resolve_markup_entries(
    entries: Sequence[MarkupEntry], model: PdfEditModel | None
) -> list[MarkupEntry]:
    """Resolve page-instance targets to output indices immediately before writing."""
    resolved: list[MarkupEntry] = []
    for entry in entries:
        if entry.kind in ("form_fill", "form_flatten"):
            resolved.append(entry)
            continue
        if model is None or entry.page_instance_id is None:
            raise MarkupTargetError("Page-scoped markup requires a live page instance")
        index = model.logical_index_for_instance(entry.page_instance_id)
        if index is None:
            raise MarkupTargetError("Markup target page no longer exists")
        if entry.annotation is not None:
            resolved.append(replace(entry, annotation=replace(entry.annotation, page_index=index)))
        elif entry.form_create is not None:
            resolved.append(replace(entry, form_create=replace(entry.form_create, page_index=index)))
        elif entry.redaction is not None:
            resolved.append(replace(entry, redaction=replace(entry.redaction, page_index=index)))
        else:
            raise MarkupTargetError(f"{entry.kind} requires a page-scoped operation")
    return resolved
