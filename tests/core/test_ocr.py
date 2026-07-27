"""Phase 29 — OCR core (mock absent tessdata; real OCR gated on env)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import fitz
import pytest

from pagedrop.core import ocr as ocr_mod
from pagedrop.core.capabilities import (
    TESSDATA,
    AbsenceReason,
    clear_cache,
    probe,
    set_configured_tessdata_path,
)
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import BackendUnavailableError, JobCancelledError


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scan_like_pdf(path: Path, text: str = "HELLO OCR") -> Path:
    """Raster-only page (no digital text) for OCR smoke."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=200)
        # Draw text then bake to image page so source has no text layer.
        page.insert_text((40, 100), text, fontsize=28)
        pix = page.get_pixmap(dpi=150, alpha=False)
        out = fitz.open()
        img_page = out.new_page(width=page.rect.width, height=page.rect.height)
        img_page.insert_image(img_page.rect, pixmap=pix)
        out.save(str(path))
        out.close()
        return path
    finally:
        doc.close()


def test_ocr_raises_when_tessdata_absent(tmp_path, monkeypatch):
    clear_cache()
    set_configured_tessdata_path(None)
    monkeypatch.delenv("PAGEDROP_TESSDATA", raising=False)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setattr(ocr_mod, "resolve_tessdata_dir", lambda: None)
    monkeypatch.setattr(
        ocr_mod,
        "probe",
        lambda *_a, **_k: type(
            "S",
            (),
            {
                "available": False,
                "reason": AbsenceReason.DATA_MISSING,
                "detail": "missing in test",
            },
        )(),
    )
    source = tmp_path / "scan.pdf"
    _scan_like_pdf(source)
    with pytest.raises(BackendUnavailableError) as excinfo:
        ocr_mod.ocr_pdf(source, tmp_path / "out.pdf")
    assert excinfo.value.capability_id == TESSDATA
    assert excinfo.value.reason == AbsenceReason.DATA_MISSING


def test_configured_tessdata_path_preferred(tmp_path, monkeypatch):
    data = tmp_path / "my-tessdata"
    data.mkdir()
    (data / "eng.traineddata").write_bytes(b"fake")
    monkeypatch.delenv("PAGEDROP_TESSDATA", raising=False)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    set_configured_tessdata_path(str(data))
    clear_cache()
    status = probe(TESSDATA, refresh=True)
    assert status.available is True
    assert status.extras["languages"] == ["eng"]
    assert Path(status.extras["path"]) == data.resolve()
    set_configured_tessdata_path(None)
    clear_cache()


def test_ocr_cancel_between_pages(tmp_path, monkeypatch):
    data = tmp_path / "tessdata"
    data.mkdir()
    (data / "eng.traineddata").write_bytes(b"x")
    set_configured_tessdata_path(str(data))
    clear_cache()

    source = tmp_path / "multi.pdf"
    doc = fitz.open()
    try:
        for i in range(3):
            page = doc.new_page(width=200, height=200)
            page.insert_text((20, 80), f"P{i}", fontsize=20)
        doc.save(str(source))
    finally:
        doc.close()

    token = CancelToken()
    calls = {"n": 0}

    def boom_pdfocr(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            token.cancel()
        # Minimal valid 1-page PDF bytes so insert_pdf works if cancel is late.
        tiny = fitz.open()
        try:
            tiny.new_page(width=72, height=72)
            return tiny.tobytes()
        finally:
            tiny.close()

    monkeypatch.setattr(fitz.Pixmap, "pdfocr_tobytes", boom_pdfocr)
    out = tmp_path / "out.pdf"
    with pytest.raises(JobCancelledError):
        ocr_mod.ocr_pdf(
            source,
            out,
            tessdata=str(data),
            dpi=72,
            cancel=token,
        )
    assert not out.exists()
    set_configured_tessdata_path(None)
    clear_cache()


@pytest.mark.tessdata
def test_ocr_searchable_when_tessdata_env(tmp_path):
    tess = os.environ.get("PAGEDROP_TESSDATA", "").strip()
    if not tess or not Path(tess).is_dir():
        pytest.skip("PAGEDROP_TESSDATA not set to a tessdata directory")
    source = _scan_like_pdf(tmp_path / "scan.pdf", "UNIQUEOCRWORD")
    before = _file_hash(source)
    out = tmp_path / "searchable.pdf"
    ocr_mod.ocr_pdf(source, out, tessdata=tess, language="eng", dpi=150)
    assert out.is_file()
    assert _file_hash(source) == before
    doc = fitz.open(out)
    try:
        text = doc[0].get_text()
    finally:
        doc.close()
    assert "UNIQUEOCRWORD" in text.replace(" ", "")
