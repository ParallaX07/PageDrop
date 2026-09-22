"""Crash-safe JSON snapshots for unsaved editor tabs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pagedrop.core.annotations import ANNOT_KINDS, AnnotationOp
from pagedrop.core.forms import FormCreateOp
from pagedrop.core.markup import MarkupEntry
from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.redact import RedactionRegion

RECOVERY_VERSION = 1


class RecoveryError(RuntimeError):
    """A recovery draft could not be written or restored."""


@dataclass(frozen=True)
class RecoveredDraft:
    model: PdfEditModel
    markup: list[MarkupEntry]
    custom_title: str | None
    drop_initialized: bool


def recovery_directory(settings_file: str) -> Path:
    """Keep drafts beside the app settings, outside disposable temp storage."""
    return Path(settings_file).resolve().parent / "recovery"


def write_draft(
    path: Path,
    model: PdfEditModel,
    markup: list[MarkupEntry],
    *,
    custom_title: str | None,
    drop_initialized: bool,
) -> None:
    payload = {
        "version": RECOVERY_VERSION,
        "pid": os.getpid(),
        "original_path": model.original_path,
        "pages": [asdict(page) for page in model.iter_pages()],
        "markup": [asdict(entry) for entry in markup],
        "custom_title": custom_title,
        "drop_initialized": drop_initialized,
    }
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise RecoveryError(f"Could not update the recovery draft: {exc}") from exc


def read_draft(path: Path) -> RecoveredDraft:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid recovery document")
        if payload.get("version") != RECOVERY_VERSION:
            raise ValueError("unsupported recovery version")
        original = str(payload["original_path"])
        pages = [_page_ref(item) for item in payload["pages"]]
        if not pages:
            raise ValueError("draft has no pages")
        missing = sorted(
            {page.source_path for page in pages if not Path(page.source_path).is_file()}
        )
        if missing:
            raise ValueError(f"source file is missing: {missing[0]}")
        markup = [_markup_entry(item) for item in payload.get("markup", [])]
        model = PdfEditModel.from_recovery(original, pages)
        live_ids = {page.instance_id for page in pages}
        if any(
            entry.page_instance_id is not None
            and entry.page_instance_id not in live_ids
            for entry in markup
        ):
            raise ValueError("draft contains markup for an unknown page")
        title = payload.get("custom_title")
        if title is not None and not isinstance(title, str):
            raise ValueError("invalid tab title")
        return RecoveredDraft(
            model=model,
            markup=markup,
            custom_title=title,
            drop_initialized=bool(payload.get("drop_initialized", False)),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"Could not read recovery draft {path.name}: {exc}") from exc


def draft_owner_pid(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        value = payload.get("pid")
        return int(value) if value is not None else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _page_ref(value: Any) -> PageRef:
    if not isinstance(value, dict):
        raise ValueError("invalid page reference")
    source_index = int(value["source_index"])
    rotation = int(value.get("rotation", 0))
    instance_id = str(value["instance_id"])
    if source_index < 0 or rotation not in {0, 90, 180, 270} or not instance_id:
        raise ValueError("invalid page reference")
    return PageRef(
        source_path=str(value["source_path"]),
        source_index=source_index,
        rotation=rotation,
        instance_id=instance_id,
    )


def _annotation(value: Any) -> AnnotationOp:
    if not isinstance(value, dict) or value.get("kind") not in ANNOT_KINDS:
        raise ValueError("invalid annotation")
    data = dict(value)
    data["rects"] = tuple(tuple(float(n) for n in rect) for rect in data.get("rects", ()))
    data["points"] = tuple(tuple(float(n) for n in point) for point in data.get("points", ()))
    data["strokes"] = tuple(
        tuple(tuple(float(n) for n in point) for point in stroke)
        for stroke in data.get("strokes", ())
    )
    data["color"] = tuple(float(n) for n in data.get("color", (1.0, 0.92, 0.23)))
    return AnnotationOp(**data)


def _markup_entry(value: Any) -> MarkupEntry:
    if not isinstance(value, dict):
        raise ValueError("invalid markup entry")
    kind = value.get("kind")
    if kind not in {"annotation", "form_fill", "form_create", "form_flatten", "redaction"}:
        raise ValueError("invalid markup kind")
    annotation = value.get("annotation")
    form_create = value.get("form_create")
    redaction = value.get("redaction")
    if form_create is not None and not isinstance(form_create, dict):
        raise ValueError("invalid form field")
    if isinstance(form_create, dict):
        field_type = form_create.get("field_type", "text")
        if field_type not in {"text", "checkbox"}:
            raise ValueError("invalid form field type")
        form_create = FormCreateOp(
            page_index=int(form_create["page_index"]),
            field_name=str(form_create["field_name"]),
            field_type=field_type,
            rect=tuple(float(n) for n in form_create.get("rect", (40, 40, 200, 60))),
            value=str(form_create.get("value", "")),
        )
    if redaction is not None and not isinstance(redaction, dict):
        raise ValueError("invalid redaction")
    if isinstance(redaction, dict):
        redaction = RedactionRegion(
            page_index=int(redaction["page_index"]),
            rect=tuple(float(n) for n in redaction["rect"]),
            fill=tuple(float(n) for n in redaction.get("fill", (0, 0, 0))),
            expected_absent=tuple(str(s) for s in redaction.get("expected_absent", ())),
        )
    form_fill = value.get("form_fill")
    if form_fill is not None and not isinstance(form_fill, dict):
        raise ValueError("invalid form values")
    return MarkupEntry(
        kind=kind,
        description=str(value.get("description", "")),
        affected_count=int(value.get("affected_count", 1)),
        page_instance_id=(
            str(value["page_instance_id"])
            if value.get("page_instance_id") is not None
            else None
        ),
        annotation=_annotation(annotation) if annotation is not None else None,
        form_fill={str(k): str(v) for k, v in form_fill.items()} if form_fill else None,
        form_create=form_create,
        redaction=redaction,
    )
