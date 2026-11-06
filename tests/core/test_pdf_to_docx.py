"""Phase 32 — PDF → DOCX via LibreOffice (mocked + optional real LO smoke)."""

from __future__ import annotations

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
from pagedrop.core.jobs import (
    CancelToken,
    JobCancelledError,
    JobSpec,
    RuntimeCredentials,
    SerializedJobRunner,
)
from pagedrop.core.jobs.errors import BackendUnavailableError
from pagedrop.core.pdf_to_docx import PdfToDocxError, convert_pdf_to_docx
from pagedrop.core.pdf_to_docx_jobs import register_pdf_to_docx_handlers
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import file_sha256


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
    before = file_sha256(src)
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
    assert file_sha256(src) == before


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


def _encrypted_pdf(path: Path, password: str = "secret") -> Path:
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw="owner",
        )
        return path
    finally:
        doc.close()


class _JobHarness:
    """Run the PDF to Word job with a stubbed LibreOffice step."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.temp = TempManager()
        self.runner = SerializedJobRunner(self.temp)
        register_pdf_to_docx_handlers(self.runner)
        self.seen: list[tuple[Path, bool, bool]] = []
        self.mode = "ok"
        monkeypatch.setattr(
            "pagedrop.core.pdf_to_docx_jobs.convert_pdf_to_docx", self._convert
        )

    def _convert(self, source, output, *, cancel=None, **_kwargs):
        source = Path(source)
        doc = fitz.open(str(source))
        try:
            self.seen.append((source, doc.needs_pass, doc.is_encrypted))
        finally:
            doc.close()
        if self.mode == "fail":
            raise PdfToDocxError("converter exploded", code="invalid_docx")
        if self.mode == "cancel":
            cancel.cancel()
            cancel.check()
        Path(output).write_bytes(b"PK\x03\x04fake-docx")
        return Path(output)

    def run(self, src: Path, out: Path, password: str | None, **kwargs) -> Path:
        creds = RuntimeCredentials()
        if password is not None:
            creds.set(src, password)
        return self.runner.run(
            JobSpec.create("pdf_to_docx", inputs=[src], output=out),
            credentials=creds,
            **kwargs,
        )

    def leftovers(self) -> list[Path]:
        return [p for p in self.temp.get_dir().glob("job_*/*")]


@pytest.fixture
def job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    harness = _JobHarness(tmp_path, monkeypatch)
    try:
        yield harness
    finally:
        harness.temp.cleanup()


def test_job_converts_decrypted_copy_of_encrypted_input(
    tmp_path: Path, job: _JobHarness
) -> None:
    src = _encrypted_pdf(tmp_path / "locked.pdf")
    before = file_sha256(src)
    out = tmp_path / "locked.docx"

    result = job.run(src, out, "secret")

    assert result == out and out.read_bytes().startswith(b"PK")
    (converted, needs_pass, is_encrypted), = job.seen
    assert converted != src and not needs_pass and not is_encrypted
    assert file_sha256(src) == before
    assert job.leftovers() == []


def test_job_decrypts_while_holding_the_fitz_lock(
    tmp_path: Path, job: _JobHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pagedrop.core import optimize_secure
    from pagedrop.core.thread_policy import FITZ_LOCK

    src = _encrypted_pdf(tmp_path / "locked.pdf")
    held: list[bool] = []

    def tracking_decrypt(*args, **kwargs):
        held.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return optimize_secure.decrypt_pdf(*args, **kwargs)

    monkeypatch.setattr(
        "pagedrop.core.pdf_to_docx_jobs.decrypt_pdf", tracking_decrypt
    )

    job.run(src, tmp_path / "locked.docx", "secret")

    assert held == [True]


def test_job_removes_decrypted_copy_when_converter_fails(
    tmp_path: Path, job: _JobHarness
) -> None:
    src = _encrypted_pdf(tmp_path / "locked.pdf")
    before = file_sha256(src)
    job.mode = "fail"

    with pytest.raises(PdfToDocxError):
        job.run(src, tmp_path / "locked.docx", "secret")

    assert job.seen and job.seen[0][0] != src
    assert not (tmp_path / "locked.docx").exists()
    assert file_sha256(src) == before
    assert job.leftovers() == []


def test_job_removes_decrypted_copy_when_cancelled_mid_run(
    tmp_path: Path, job: _JobHarness
) -> None:
    src = _encrypted_pdf(tmp_path / "locked.pdf")
    before = file_sha256(src)
    job.mode = "cancel"

    with pytest.raises(JobCancelledError):
        job.run(src, tmp_path / "locked.docx", "secret", cancel=CancelToken())

    assert job.seen and job.seen[0][0] != src
    assert file_sha256(src) == before
    assert job.leftovers() == []


def test_job_passes_unencrypted_input_straight_through(
    tmp_path: Path, job: _JobHarness
) -> None:
    src = _make_pdf(tmp_path / "plain.pdf")
    before = file_sha256(src)
    out = tmp_path / "plain.docx"

    assert job.run(src, out, None) == out

    (converted, needs_pass, _), = job.seen
    assert converted == src and not needs_pass
    assert file_sha256(src) == before
    assert job.leftovers() == []


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
        before = file_sha256(src)
        dst = tmp_path / "smoke.docx"
        result = convert_pdf_to_docx(src, dst, soffice_path=lo, timeout_sec=120)
        assert result.is_file()
        assert result.read_bytes()[:2] == b"PK"
        assert file_sha256(src) == before
    finally:
        set_configured_soffice_path(None)
        clear_cache()
