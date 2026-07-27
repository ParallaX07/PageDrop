"""Phase 30 — AcroForm fill / create / flatten (no XFA)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core.forms import (
    FormCreateOp,
    FormError,
    XfaUnsupportedError,
    create_form_fields,
    document_has_xfa,
    ensure_no_xfa,
    fill_form_fields,
    flatten_forms,
    list_form_fields,
)
from pagedrop.core.jobs.errors import SourceOverwriteError


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 80), "Form body", fontsize=14)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_create_fill_flatten_round_trip(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    source_hash = _file_hash(src)
    created = tmp_path / "created.pdf"
    create_form_fields(
        str(src),
        str(created),
        [
            FormCreateOp(0, "Name", "text", (40, 300, 200, 320)),
            FormCreateOp(0, "Agree", "checkbox", (40, 340, 60, 360)),
        ],
    )
    assert _file_hash(src) == source_hash
    fields = list_form_fields(str(created))
    names = {f.name for f in fields}
    assert names == {"Name", "Agree"}

    filled = tmp_path / "filled.pdf"
    updated = fill_form_fields(
        str(created), str(filled), {"Name": "Ada", "Agree": "Yes"}
    )
    assert updated == 2
    assert _file_hash(src) == source_hash
    values = {f.name: str(f.value) for f in list_form_fields(str(filled))}
    assert values["Name"] == "Ada"
    assert values["Agree"].lower() in ("yes", "true", "1", "on")

    flat = tmp_path / "flat.pdf"
    flatten_forms(str(filled), str(flat))
    assert list_form_fields(str(flat)) == []
    assert _file_hash(src) == source_hash

    with pytest.raises(SourceOverwriteError):
        fill_form_fields(str(created), str(created), {"Name": "x"})


def test_fill_requires_values(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    with pytest.raises(FormError):
        fill_form_fields(str(src), str(tmp_path / "out.pdf"), {})


def test_xfa_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    opened = fitz.open(str(src))
    try:
        assert document_has_xfa(opened) is False
        monkeypatch.setattr(
            "pagedrop.core.forms.document_has_xfa", lambda _doc: True
        )
        with pytest.raises(XfaUnsupportedError):
            ensure_no_xfa(opened, path=str(src))
    finally:
        opened.close()
