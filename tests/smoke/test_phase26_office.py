"""Phase 26 smoke — Office → PDF via real COM / LibreOffice (env-gated).

Normal CI skips these. Enable with:

- ``PAGEDROP_LO_PATH=/path/to/soffice`` for ``@pytest.mark.libreoffice``
- ``PAGEDROP_OFFICE_COM=1`` for ``@pytest.mark.office_com`` (Windows + Office)
"""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import fitz
import pytest

from pagedrop.core.backends.office import convert_office_to_pdf
from pagedrop.core.capabilities import clear_cache, set_configured_soffice_path


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_tiny_docx(path: Path, text: str = "PageDrop office smoke") -> Path:
    """Minimal OOXML .docx (ZIP) — enough for LO / Word to open."""
    body = escape(text)
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{body}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
    return path


@pytest.mark.libreoffice
def test_smoke_libreoffice_docx_to_pdf(tmp_path: Path) -> None:
    lo = os.environ.get("PAGEDROP_LO_PATH", "").strip()
    if not lo:
        pytest.skip("set PAGEDROP_LO_PATH to run LibreOffice smoke")
    if not Path(lo).is_file():
        pytest.skip(f"PAGEDROP_LO_PATH is not a file: {lo}")

    set_configured_soffice_path(lo)
    clear_cache()
    try:
        src = _write_tiny_docx(tmp_path / "smoke note.docx")
        before = _file_hash(src)
        dst = tmp_path / "smoke note.pdf"
        result = convert_office_to_pdf(
            src, dst, backend="libreoffice", soffice_path=lo, timeout_sec=120
        )
        assert result.backend == "libreoffice"
        assert result.path.is_file()
        assert result.page_count >= 1
        with fitz.open(result.path) as doc:
            assert doc.page_count >= 1
        assert _file_hash(src) == before
    finally:
        set_configured_soffice_path(None)
        clear_cache()


@pytest.mark.office_com
def test_smoke_office_com_docx_to_pdf(tmp_path: Path) -> None:
    if os.environ.get("PAGEDROP_OFFICE_COM", "").strip() != "1":
        pytest.skip("set PAGEDROP_OFFICE_COM=1 to run Office COM smoke")

    clear_cache()
    src = _write_tiny_docx(tmp_path / "com smoke.docx")
    before = _file_hash(src)
    dst = tmp_path / "com smoke.pdf"
    result = convert_office_to_pdf(src, dst, backend="com", timeout_sec=120)
    assert result.backend == "com"
    assert result.path.is_file()
    assert result.page_count >= 1
    with fitz.open(result.path) as doc:
        assert doc.page_count >= 1
    assert _file_hash(src) == before
