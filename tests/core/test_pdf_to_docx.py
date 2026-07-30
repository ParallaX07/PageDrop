"""Phase 32 — PDF → DOCX via LibreOffice (mocked + optional real LO smoke)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest

from pagedrop.core.backends import libreoffice
from pagedrop.core.capabilities import (
    LIBREOFFICE,
    AbsenceReason,
    CapabilityStatus,
    clear_cache,
    set_configured_soffice_path,
)
from pagedrop.core.jobs.errors import BackendUnavailableError
from pagedrop.core.pdf_to_docx import PdfToDocxError, convert_pdf_to_docx


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_pdf(path: Path, text: str = "PageDrop word export") -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), text, fontsize=14)
        doc.save(str(path))
        return path
    finally:
        doc.close()


@pytest.fixture(autouse=True)
def _reset_soffice() -> None:
    set_configured_soffice_path(None)
    clear_cache()
    yield
    set_configured_soffice_path(None)
    clear_cache()


def test_pdf_to_docx_promotes_and_leaves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_pdf(tmp_path / "report.pdf")
    before = _file_hash(src)
    dst = tmp_path / "report.docx"
    fake_bin = tmp_path / "soffice"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    def fake_popen(argv, **kwargs):
        outdir = Path(argv[argv.index("--outdir") + 1])
        assert argv[argv.index("--convert-to") + 1] == "docx"
        assert "--infilter=writer_pdf_import" in argv
        (outdir / "report.docx").write_bytes(b"PK\x03\x04fake-docx")
        proc = MagicMock()
        proc.pid = 1
        proc.poll.return_value = 0
        proc.returncode = 0
        proc.stdout = MagicMock(read=lambda: "")
        proc.stderr = MagicMock(read=lambda: "")
        return proc

    monkeypatch.setattr(libreoffice, "popen_owned", fake_popen)
    monkeypatch.setattr(libreoffice, "kill_process_tree", lambda _pid: None)
    monkeypatch.setattr(libreoffice, "find_soffice", lambda configured_path=None: str(fake_bin))

    result = convert_pdf_to_docx(src, dst, soffice_path=str(fake_bin))
    assert result == dst
    assert dst.read_bytes().startswith(b"PK")
    assert _file_hash(src) == before


def test_pdf_to_docx_rejects_non_pdf(tmp_path: Path) -> None:
    src = tmp_path / "note.txt"
    src.write_text("hello", encoding="utf-8")
    with pytest.raises(PdfToDocxError) as exc:
        convert_pdf_to_docx(src, tmp_path / "out.docx")
    assert exc.value.code == "bad_input"


def test_pdf_to_docx_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "a.pdf")
    monkeypatch.setattr(
        "pagedrop.core.pdf_to_docx.find_soffice", lambda configured_path=None: None
    )
    monkeypatch.setattr(
        "pagedrop.core.pdf_to_docx.probe",
        lambda _cid, refresh=False: CapabilityStatus(
            id=LIBREOFFICE,
            available=False,
            reason=AbsenceReason.ENGINE_MISSING,
            detail="missing",
        ),
    )
    with pytest.raises(BackendUnavailableError) as exc:
        convert_pdf_to_docx(src, tmp_path / "a.docx")
    assert exc.value.capability_id == LIBREOFFICE


def test_pdf_to_docx_rejects_invalid_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_pdf(tmp_path / "bad.pdf")
    dst = tmp_path / "bad.docx"
    fake_bin = tmp_path / "soffice"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    def fake_popen(argv, **kwargs):
        outdir = Path(argv[argv.index("--outdir") + 1])
        (outdir / "bad.docx").write_bytes(b"not-a-zip")
        proc = MagicMock()
        proc.pid = 1
        proc.poll.return_value = 0
        proc.returncode = 0
        proc.stdout = MagicMock(read=lambda: "")
        proc.stderr = MagicMock(read=lambda: "")
        return proc

    monkeypatch.setattr(libreoffice, "popen_owned", fake_popen)
    monkeypatch.setattr(libreoffice, "kill_process_tree", lambda _pid: None)
    monkeypatch.setattr(libreoffice, "find_soffice", lambda configured_path=None: str(fake_bin))

    with pytest.raises(PdfToDocxError) as exc:
        convert_pdf_to_docx(src, dst, soffice_path=str(fake_bin))
    assert exc.value.code == "invalid_docx"


@pytest.mark.libreoffice
def test_smoke_libreoffice_pdf_to_docx(tmp_path: Path) -> None:
    lo = os.environ.get("PAGEDROP_LO_PATH", "").strip()
    if not lo:
        pytest.skip("set PAGEDROP_LO_PATH to run LibreOffice smoke")
    if not Path(lo).is_file():
        pytest.skip(f"PAGEDROP_LO_PATH is not a file: {lo}")

    set_configured_soffice_path(lo)
    clear_cache()
    try:
        src = _make_pdf(tmp_path / "smoke.pdf", "Phase 32 PDF to Word")
        before = _file_hash(src)
        dst = tmp_path / "smoke.docx"
        result = convert_pdf_to_docx(src, dst, soffice_path=lo, timeout_sec=120)
        assert result.is_file()
        assert result.read_bytes()[:2] == b"PK"
        assert _file_hash(src) == before
    finally:
        set_configured_soffice_path(None)
        clear_cache()
