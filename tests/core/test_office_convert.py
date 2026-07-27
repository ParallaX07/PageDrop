"""Office → PDF orchestration — capability report, auto route, stage/validate, retry."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest

from pagedrop.core.backends import office, process_tree
from pagedrop.core.backends.office import (
    OfficeCapabilityReport,
    OfficeComFailedNeedsRetry,
    OfficeConversionError,
    capability_report,
    com_supports_path,
    convert_office_to_pdf,
    resolve_backend,
    validate_pdf,
)
from pagedrop.core.backends.office_com import OfficeComConversionError
from pagedrop.core.capabilities import (
    LIBREOFFICE,
    OFFICE_COM,
    AbsenceReason,
    CapabilityStatus,
    clear_cache,
    set_configured_office_backend,
    set_configured_soffice_path,
)
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import BackendUnavailableError, JobCancelledError


@pytest.fixture(autouse=True)
def _reset_office_config() -> None:
    set_configured_soffice_path(None)
    set_configured_office_backend("auto")
    clear_cache()
    yield
    set_configured_soffice_path(None)
    set_configured_office_backend("auto")
    clear_cache()


def _pdf_bytes(pages: int = 1) -> bytes:
    doc = fitz.open()
    try:
        for _ in range(pages):
            doc.new_page(width=200, height=200)
        return doc.tobytes()
    finally:
        doc.close()


def _mock_report(
    *, com: bool, lo: bool, apps: list[str] | None = None
) -> OfficeCapabilityReport:
    com_status = (
        CapabilityStatus(
            id=OFFICE_COM,
            available=True,
            detail="mocked",
            extras={"apps": apps or []},
        )
        if com
        else CapabilityStatus(
            id=OFFICE_COM,
            available=False,
            reason=AbsenceReason.ENGINE_MISSING,
            detail="no com",
        )
    )
    lo_status = (
        CapabilityStatus(
            id=LIBREOFFICE,
            available=True,
            detail="mocked",
            extras={"path": "/bin/soffice"},
        )
        if lo
        else CapabilityStatus(
            id=LIBREOFFICE,
            available=False,
            reason=AbsenceReason.ENGINE_MISSING,
            detail="no lo",
        )
    )
    return OfficeCapabilityReport(
        com=com_status,
        libreoffice=lo_status,
        preferred="auto",
        soffice_path=None,
    )


def test_detect_com_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_probe(cid: str, refresh: bool = False) -> CapabilityStatus:
        if cid == OFFICE_COM:
            return CapabilityStatus(
                id=OFFICE_COM,
                available=True,
                detail="mocked",
                extras={"apps": ["word", "excel"]},
            )
        return CapabilityStatus(
            id=LIBREOFFICE,
            available=False,
            reason=AbsenceReason.ENGINE_MISSING,
            detail="no lo",
        )

    monkeypatch.setattr("pagedrop.core.backends.office.probe", fake_probe)
    report = capability_report()
    assert report.com.available
    assert report.com.extras["apps"] == ["word", "excel"]
    assert not report.libreoffice.available


def test_detect_libreoffice_mocked_path_and_which(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "soffice"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    set_configured_soffice_path(str(fake))
    clear_cache()
    report = capability_report(refresh=True)
    assert report.libreoffice.available
    assert Path(str(report.libreoffice.extras["path"])) == fake.resolve()

    # PATH / which when no configured path
    set_configured_soffice_path(None)
    monkeypatch.delenv("PAGEDROP_LO_PATH", raising=False)
    monkeypatch.delenv("LIBREOFFICE_PATH", raising=False)
    monkeypatch.setattr(
        "pagedrop.core.capabilities.shutil.which",
        lambda name: str(fake) if name == "soffice" else None,
    )
    monkeypatch.setattr(
        "pagedrop.core.capabilities._windows_registry_soffice", lambda: None
    )
    clear_cache()
    via_which = capability_report(refresh=True)
    assert via_which.libreoffice.available
    assert Path(str(via_which.libreoffice.extras["path"])) == fake.resolve()


def test_auto_prefers_com_when_format_supported() -> None:
    report = _mock_report(com=True, lo=True, apps=["word", "excel"])
    assert resolve_backend("doc.docx", preference="auto", report=report) == "com"
    assert resolve_backend("sheet.xlsx", preference="auto", report=report) == "com"
    # PowerPoint ProgID absent → LibreOffice
    assert resolve_backend("deck.pptx", preference="auto", report=report) == "libreoffice"


def test_com_failure_offers_explicit_lo_retry_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.docx"
    src.write_bytes(b"docx")
    dst = tmp_path / "a.pdf"
    report = _mock_report(com=True, lo=True, apps=["word"])

    monkeypatch.setattr(office, "capability_report", lambda **_k: report)
    monkeypatch.setattr(
        office.office_com,
        "convert_via_com",
        MagicMock(side_effect=OfficeComConversionError("boom", code="fail")),
    )
    lo_mock = MagicMock()
    monkeypatch.setattr(office.libreoffice, "convert_via_libreoffice", lo_mock)

    with pytest.raises(OfficeComFailedNeedsRetry) as exc:
        convert_office_to_pdf(src, dst, backend="auto")
    assert exc.value.retry_with_libreoffice is True
    lo_mock.assert_not_called()  # no silent swap

    def fake_lo(inp, out, **_kwargs):
        Path(out).write_bytes(_pdf_bytes(1))
        return Path(out)

    lo_mock.side_effect = fake_lo
    result = convert_office_to_pdf(src, dst, backend="libreoffice")
    assert result.backend == "libreoffice"
    assert result.path.is_file()
    lo_mock.assert_called_once()


def test_missing_backend_actionable_error() -> None:
    report = _mock_report(com=False, lo=False)
    with pytest.raises(BackendUnavailableError):
        resolve_backend("a.docx", preference="auto", report=report)


def test_stage_validate_promote_rejects_non_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.docx"
    src.write_bytes(b"docx")
    dst = tmp_path / "out.pdf"
    report = _mock_report(com=False, lo=True)
    monkeypatch.setattr(office, "capability_report", lambda **_k: report)

    def fake_lo(inp, out, **_kwargs):
        Path(out).write_bytes(b"%PDF-not-really")
        return Path(out)

    monkeypatch.setattr(office.libreoffice, "convert_via_libreoffice", fake_lo)
    with pytest.raises(OfficeConversionError) as exc:
        convert_office_to_pdf(src, dst, backend="libreoffice")
    assert exc.value.code == "invalid_pdf"
    assert not dst.exists()


def test_stage_validate_promote_happy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.docx"
    src.write_bytes(b"docx")
    dst = tmp_path / "out.pdf"
    report = _mock_report(com=False, lo=True)
    monkeypatch.setattr(office, "capability_report", lambda **_k: report)

    def fake_lo(inp, out, **_kwargs):
        Path(out).write_bytes(_pdf_bytes(2))
        return Path(out)

    monkeypatch.setattr(office.libreoffice, "convert_via_libreoffice", fake_lo)
    result = convert_office_to_pdf(src, dst, backend="libreoffice")
    assert result.page_count == 2
    assert dst.is_file()
    assert validate_pdf(dst) == 2


def test_source_hash_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.docx"
    src.write_bytes(b"stable-office-bytes")
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    dst = tmp_path / "out.pdf"
    report = _mock_report(com=False, lo=True)
    monkeypatch.setattr(office, "capability_report", lambda **_k: report)

    def fake_lo(inp, out, **_kwargs):
        Path(out).write_bytes(_pdf_bytes())
        return Path(out)

    monkeypatch.setattr(office.libreoffice, "convert_via_libreoffice", fake_lo)
    convert_office_to_pdf(src, dst, backend="libreoffice")
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before


def test_cancel_kills_owned_process_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Orchestration cancel must reap the owned LO helper (fake sleeper subprocess)."""
    src = tmp_path / "a.docx"
    src.write_bytes(b"docx")
    dst = tmp_path / "out.pdf"
    fake_bin = tmp_path / "soffice"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    report = _mock_report(com=False, lo=True)
    monkeypatch.setattr(office, "capability_report", lambda **_k: report)
    monkeypatch.setattr(office.libreoffice, "build_convert_argv", lambda *a, **k: ["fake"])

    owned: list[subprocess.Popen] = []
    killed: list[int] = []
    real_kill = office.libreoffice.kill_process_tree

    def fake_popen(argv, **kwargs):
        child = process_tree.popen_owned(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
        )
        owned.append(child)
        return child

    def tracking_kill(pid: int) -> None:
        killed.append(pid)
        real_kill(pid)

    monkeypatch.setattr(office.libreoffice, "popen_owned", fake_popen)
    monkeypatch.setattr(office.libreoffice, "kill_process_tree", tracking_kill)
    token = CancelToken()

    def cancel_soon() -> None:
        time.sleep(0.2)
        token.cancel()

    threading.Thread(target=cancel_soon, daemon=True).start()
    with pytest.raises(JobCancelledError):
        convert_office_to_pdf(
            src,
            dst,
            backend="libreoffice",
            soffice_path=str(fake_bin),
            cancel=token,
            timeout_sec=30,
        )
    assert owned, "expected a fake helper process"
    assert killed == [owned[0].pid]
    owned[0].wait(timeout=5)
    assert owned[0].poll() is not None
    assert not dst.exists()


def test_unicode_and_spaces_in_filenames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "café report (1).docx"
    src.write_bytes(b"docx-unicode")
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    out_dir = tmp_path / "out folder"
    out_dir.mkdir()
    dst = out_dir / "résumé copy.pdf"
    report = _mock_report(com=False, lo=True)
    monkeypatch.setattr(office, "capability_report", lambda **_k: report)

    def fake_lo(inp, out, **_kwargs):
        assert Path(inp).name == src.name
        Path(out).write_bytes(_pdf_bytes(1))
        return Path(out)

    monkeypatch.setattr(office.libreoffice, "convert_via_libreoffice", fake_lo)
    result = convert_office_to_pdf(src, dst, backend="libreoffice")
    assert result.path == dst.resolve()
    assert dst.is_file()
    assert result.page_count >= 1
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before


def test_com_supports_path_uses_apps() -> None:
    assert com_supports_path("x.docx", apps=["word"])
    assert not com_supports_path("x.pptx", apps=["word"])
