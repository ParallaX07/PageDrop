"""AcroForm fill / create / flatten. XFA is unsupported."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import fitz

from pagedrop.core.jobs.errors import JobError
from pagedrop.core.jobs.paths import reject_source_overwrite
from pagedrop.core.pdf_loader import open_pdf

FieldType = Literal["text", "checkbox", "combobox", "listbox", "radiobutton", "other"]

_ACROFORM_REF = re.compile(r"/AcroForm\s+(\d+)\s+0\s+R")


class FormError(JobError):
    """Raised when a form operation cannot complete."""


class XfaUnsupportedError(FormError):
    """XFA forms are out of scope for PageDrop."""

    def __init__(self, path: str = "") -> None:
        self.path = path
        super().__init__(
            "XFA forms are not supported. Export or recreate as AcroForm fields."
        )


@dataclass(frozen=True)
class FormFieldInfo:
    name: str
    field_type: FieldType
    value: str
    page_index: int
    rect: tuple[float, float, float, float]


@dataclass(frozen=True)
class FormCreateOp:
    """Create an AcroForm widget on a page."""

    page_index: int
    field_name: str
    field_type: Literal["text", "checkbox"] = "text"
    rect: tuple[float, float, float, float] = (40.0, 40.0, 200.0, 60.0)
    value: str = ""


@dataclass(frozen=True)
class FormFillOp:
    """Set field values by name (document-wide)."""

    values: Mapping[str, str]


def _save(doc: fitz.Document, output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path, garbage=3, deflate=True)


def document_has_xfa(doc: fitz.Document) -> bool:
    """True when the catalog AcroForm dictionary references ``/XFA``."""
    try:
        catalog = doc.xref_object(doc.pdf_catalog())
    except Exception:
        return False
    match = _ACROFORM_REF.search(catalog)
    if not match:
        return "/XFA" in catalog
    try:
        form_obj = doc.xref_object(int(match.group(1)))
    except Exception:
        return False
    return "/XFA" in form_obj


def ensure_no_xfa(doc: fitz.Document, *, path: str = "") -> None:
    if document_has_xfa(doc):
        raise XfaUnsupportedError(path)


def _widget_type(field_type: int) -> FieldType:
    mapping = {
        fitz.PDF_WIDGET_TYPE_TEXT: "text",
        fitz.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
        fitz.PDF_WIDGET_TYPE_COMBOBOX: "combobox",
        fitz.PDF_WIDGET_TYPE_LISTBOX: "listbox",
        fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "radiobutton",
    }
    return mapping.get(field_type, "other")  # type: ignore[return-value]


def list_form_fields(
    source_pdf: str,
    *,
    password: str | None = None,
) -> list[FormFieldInfo]:
    """List AcroForm widgets. Raises ``XfaUnsupportedError`` for XFA docs."""
    doc = open_pdf(source_pdf, password=password)
    try:
        ensure_no_xfa(doc, path=source_pdf)
        fields: list[FormFieldInfo] = []
        for page_index, page in enumerate(doc):
            for widget in page.widgets() or []:
                rect = widget.rect
                fields.append(
                    FormFieldInfo(
                        name=str(widget.field_name or ""),
                        field_type=_widget_type(int(widget.field_type)),
                        value=str(widget.field_value or ""),
                        page_index=page_index,
                        rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                    )
                )
        return fields
    finally:
        doc.close()


def fill_form_fields(
    source_pdf: str,
    output_path: str,
    values: Mapping[str, str],
    *,
    password: str | None = None,
) -> int:
    """Write a filled copy. Returns the number of widgets updated."""
    reject_source_overwrite(output_path, source_pdf)
    if not values:
        raise FormError("No form field values to apply")
    doc = open_pdf(source_pdf, password=password)
    try:
        ensure_no_xfa(doc, path=source_pdf)
        updated = apply_form_fill(doc, values)
        _save(doc, output_path)
        return updated
    finally:
        doc.close()


def _coerce_field_value(widget: fitz.Widget, value: str) -> object:
    if int(widget.field_type) == fitz.PDF_WIDGET_TYPE_CHECKBOX:
        low = value.strip().lower()
        if low in ("1", "true", "yes", "on", "checked"):
            return True
        if low in ("0", "false", "no", "off", "", "unchecked"):
            return False
    return value


def apply_form_fill(doc: fitz.Document, values: Mapping[str, str]) -> int:
    """Set widget values on an open *doc*. Returns widgets updated."""
    ensure_no_xfa(doc)
    updated = 0
    for page in doc:
        for widget in page.widgets() or []:
            name = str(widget.field_name or "")
            if name not in values:
                continue
            widget.field_value = _coerce_field_value(widget, values[name])  # type: ignore[assignment]
            widget.update()
            updated += 1
    return updated


def create_form_fields(
    source_pdf: str,
    output_path: str,
    fields: Sequence[FormCreateOp],
    *,
    password: str | None = None,
) -> None:
    """Create AcroForm widgets on a copy of *source_pdf*."""
    reject_source_overwrite(output_path, source_pdf)
    if not fields:
        raise FormError("No form fields to create")
    doc = open_pdf(source_pdf, password=password)
    try:
        ensure_no_xfa(doc, path=source_pdf)
        apply_form_creates(doc, fields)
        _save(doc, output_path)
    finally:
        doc.close()


def apply_form_creates(doc: fitz.Document, fields: Sequence[FormCreateOp]) -> None:
    ensure_no_xfa(doc)
    for field in fields:
        if field.page_index < 0 or field.page_index >= doc.page_count:
            raise FormError(
                f"Page index {field.page_index} out of range ({doc.page_count} pages)"
            )
        if not field.field_name.strip():
            raise FormError("Form field name is required")
        page = doc[field.page_index]
        widget = fitz.Widget()
        widget.field_name = field.field_name
        widget.rect = fitz.Rect(*field.rect)
        if field.field_type == "checkbox":
            widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
            widget.field_value = field.value or False  # type: ignore[assignment]
        else:
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.field_value = field.value
        page.add_widget(widget)


def flatten_forms(
    source_pdf: str,
    output_path: str,
    *,
    password: str | None = None,
) -> None:
    """Bake form appearances into page content (widgets removed as interactive)."""
    reject_source_overwrite(output_path, source_pdf)
    doc = open_pdf(source_pdf, password=password)
    try:
        ensure_no_xfa(doc, path=source_pdf)
        apply_form_flatten(doc)
        _save(doc, output_path)
    finally:
        doc.close()


def apply_form_flatten(doc: fitz.Document) -> None:
    ensure_no_xfa(doc)
    doc.bake(annots=False, widgets=True)
