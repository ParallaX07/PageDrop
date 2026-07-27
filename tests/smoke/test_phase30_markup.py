"""Phase 30 smoke — highlight, form fill, security-grade redaction."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core.annotations import AnnotationOp, add_annotations, list_annotation_summaries
from pagedrop.core.forms import FormCreateOp, create_form_fields, fill_form_fields, list_form_fields
from pagedrop.core.redact import (
    RedactionRegion,
    RedactionVerifyError,
    redact_pdf,
    verify_redacted_pdf_fresh_process,
)

SECRET = "PHASE30SECRET"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_pdf(path: Path, text: str = f"Hello {SECRET} world") -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        page.insert_text((40, 80), text, fontsize=14)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def _secret_rect(path: Path) -> tuple[float, float, float, float]:
    doc = fitz.open(str(path))
    try:
        hits = doc[0].search_for(SECRET)
        assert hits, f"{SECRET!r} not found"
        r = hits[0]
        return (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
    finally:
        doc.close()


def test_smoke_highlight_form_and_redact(tmp_path: Path) -> None:
    src = _text_pdf(tmp_path / "src.pdf")
    source_hash = _file_hash(src)

    # Highlight persists on a new path (Save As / export only).
    highlighted = tmp_path / "highlight.pdf"
    add_annotations(
        str(src),
        str(highlighted),
        [AnnotationOp(kind="highlight", page_index=0, rects=((40, 60, 160, 95),))],
    )
    assert _file_hash(src) == source_hash
    assert highlighted.resolve() != src.resolve()
    types = [t for _, t, _ in list_annotation_summaries(str(highlighted))]
    assert "Highlight" in types

    # Form create → fill round-trip; source untouched.
    created = tmp_path / "form.pdf"
    create_form_fields(
        str(src),
        str(created),
        [FormCreateOp(0, "Name", "text", (40, 200, 200, 220))],
    )
    filled = tmp_path / "filled.pdf"
    fill_form_fields(str(created), str(filled), {"Name": "Ada"})
    assert _file_hash(src) == source_hash
    values = {f.name: str(f.value) for f in list_form_fields(str(filled))}
    assert values["Name"] == "Ada"

    # Redact secret → fresh-process unextractable; failed verify leaves no output.
    out = tmp_path / "redacted.pdf"
    redact_pdf(src, out, [RedactionRegion(0, _secret_rect(src))], verify=True)
    assert _file_hash(src) == source_hash
    assert out.is_file()
    report = verify_redacted_pdf_fresh_process(out, absent_text=[SECRET])
    assert report.ok, report.failures
    doc = fitz.open(str(out))
    try:
        assert SECRET not in (doc[0].get_text() or "")
        assert not doc[0].search_for(SECRET)
    finally:
        doc.close()

    bad = tmp_path / "should_not_exist.pdf"
    with pytest.raises(RedactionVerifyError):
        redact_pdf(
            src,
            bad,
            [RedactionRegion(0, (0.0, 0.0, 8.0, 8.0))],
            extra_absent=[SECRET],
            verify=True,
        )
    assert not bad.exists()
    assert _file_hash(src) == source_hash
