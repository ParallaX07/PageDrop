"""LibreOffice adapter — detect, convert argv, timeout/cancel tree kill, profile cleanup."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pagedrop.core.backends import libreoffice, process_tree
from pagedrop.core.backends.libreoffice import (
    DOWNLOAD_URL,
    WINGET_INSTALL_COMMAND,
    LibreOfficeConversionError,
    build_convert_argv,
    convert_via_libreoffice,
)
from pagedrop.core.capabilities import (
    LIBREOFFICE,
    AbsenceReason,
    CapabilityStatus,
    clear_cache,
    find_soffice,
    set_configured_soffice_path,
)
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import BackendUnavailableError, JobCancelledError


@pytest.fixture(autouse=True)
def _reset_configured_soffice() -> None:
    set_configured_soffice_path(None)
    clear_cache()
    yield
    set_configured_soffice_path(None)
    clear_cache()


def test_find_soffice_prefers_configured_over_which(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "custom" / "soffice"
    configured.parent.mkdir()
    configured.write_text("#!/bin/sh\n", encoding="utf-8")
    configured.chmod(0o755)
    other = tmp_path / "path" / "soffice"
    other.parent.mkdir()
    other.write_text("#!/bin/sh\n", encoding="utf-8")
    other.chmod(0o755)

    monkeypatch.delenv("PAGEDROP_LO_PATH", raising=False)
    monkeypatch.delenv("LIBREOFFICE_PATH", raising=False)
    monkeypatch.setattr(
        "pagedrop.core.capabilities.shutil.which", lambda _name: str(other)
    )
    monkeypatch.setattr(
        "pagedrop.core.capabilities._windows_registry_soffice", lambda: None
    )

    assert find_soffice(str(configured)) == str(configured.resolve())
    set_configured_soffice_path(str(configured))
    assert find_soffice() == str(configured.resolve())


def test_find_soffice_uses_path_when_no_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on_path = tmp_path / "soffice"
    on_path.write_text("#!/bin/sh\n", encoding="utf-8")
    on_path.chmod(0o755)
    monkeypatch.delenv("PAGEDROP_LO_PATH", raising=False)
    monkeypatch.delenv("LIBREOFFICE_PATH", raising=False)
    monkeypatch.setattr(
        "pagedrop.core.capabilities.shutil.which",
        lambda name: str(on_path) if name == "soffice" else None,
    )
    monkeypatch.setattr(
        "pagedrop.core.capabilities._windows_registry_soffice", lambda: None
    )
    assert find_soffice() == str(on_path.resolve())


def test_find_soffice_registry_before_common_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "reg" / "soffice.exe"
    registry.parent.mkdir()
    registry.write_bytes(b"MZ")
    monkeypatch.delenv("PAGEDROP_LO_PATH", raising=False)
    monkeypatch.delenv("LIBREOFFICE_PATH", raising=False)
    monkeypatch.setattr("pagedrop.core.capabilities.shutil.which", lambda _n: None)
    monkeypatch.setattr(
        "pagedrop.core.capabilities._windows_registry_soffice",
        lambda: str(registry),
    )
    assert find_soffice() == str(registry.resolve())


def test_build_convert_argv_uses_temp_user_profile(tmp_path: Path) -> None:
    soffice = tmp_path / "soffice"
    src = tmp_path / "doc.docx"
    outdir = tmp_path / "out"
    profile = tmp_path / "profile"
    outdir.mkdir()
    profile.mkdir()
    src.write_bytes(b"PK")
    argv = build_convert_argv(soffice, src, outdir, profile)
    assert argv[0] == str(soffice)
    assert "--headless" in argv
    assert "--convert-to" in argv
    assert argv[argv.index("--convert-to") + 1] == "pdf"
    assert "--outdir" in argv
    env_arg = next(a for a in argv if a.startswith("-env:UserInstallation="))
    assert profile.resolve().as_uri() in env_arg
    assert str(src.resolve()) in argv


def test_build_convert_argv_docx_target(tmp_path: Path) -> None:
    soffice = tmp_path / "soffice"
    src = tmp_path / "doc.pdf"
    outdir = tmp_path / "out"
    profile = tmp_path / "profile"
    outdir.mkdir()
    profile.mkdir()
    src.write_bytes(b"%PDF")
    argv = build_convert_argv(
        soffice,
        src,
        outdir,
        profile,
        convert_to="docx",
        infilter="writer_pdf_import",
    )
    assert argv[argv.index("--convert-to") + 1] == "docx"
    assert "--infilter=writer_pdf_import" in argv


def test_convert_timeout_kills_owned_and_cleans_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "doc.docx"
    src.write_bytes(b"PK")
    dst = tmp_path / "out.pdf"
    fake_bin = tmp_path / "soffice"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    created: list[Path] = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def tracking_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        created.append(Path(path))
        return path

    monkeypatch.setattr("pagedrop.core.backends.libreoffice.tempfile.mkdtemp", tracking_mkdtemp)
    monkeypatch.setattr(
        libreoffice,
        "find_soffice",
        lambda configured_path=None: str(fake_bin),
    )

    def fake_popen(argv, **kwargs):
        return process_tree.popen_owned(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
        )

    monkeypatch.setattr(libreoffice, "popen_owned", fake_popen)
    monkeypatch.setattr(libreoffice, "build_convert_argv", lambda *a, **k: ["fake"])

    t0 = time.monotonic()
    with pytest.raises(LibreOfficeConversionError) as exc:
        convert_via_libreoffice(src, dst, timeout_sec=0.4, soffice_path=str(fake_bin))
    assert exc.value.code == "timeout"
    assert time.monotonic() - t0 < 10.0
    for path in created:
        assert not path.exists(), f"temp dir left behind: {path}"


def test_convert_cancel_kills_owned_and_cleans_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "doc.docx"
    src.write_bytes(b"PK")
    dst = tmp_path / "out.pdf"
    fake_bin = tmp_path / "soffice"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    token = CancelToken()

    created: list[Path] = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def tracking_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        created.append(Path(path))
        return path

    monkeypatch.setattr("pagedrop.core.backends.libreoffice.tempfile.mkdtemp", tracking_mkdtemp)
    monkeypatch.setattr(
        libreoffice,
        "popen_owned",
        lambda argv, **kwargs: process_tree.popen_owned(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
        ),
    )
    monkeypatch.setattr(libreoffice, "build_convert_argv", lambda *a, **k: ["fake"])

    def cancel_soon() -> None:
        time.sleep(0.2)
        token.cancel()

    threading.Thread(target=cancel_soon, daemon=True).start()
    with pytest.raises(JobCancelledError):
        convert_via_libreoffice(
            src, dst, timeout_sec=30, cancel=token, soffice_path=str(fake_bin)
        )
    for path in created:
        assert not path.exists(), f"temp dir left behind: {path}"


def test_convert_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(libreoffice, "find_soffice", lambda configured_path=None: None)
    monkeypatch.setattr(
        libreoffice,
        "probe",
        lambda _cid: CapabilityStatus(
            id=LIBREOFFICE,
            available=False,
            reason=AbsenceReason.ENGINE_MISSING,
            detail="missing",
        ),
    )
    with pytest.raises(BackendUnavailableError) as exc:
        convert_via_libreoffice(tmp_path / "a.docx", tmp_path / "a.pdf")
    assert exc.value.capability_id == LIBREOFFICE


def test_convert_promotes_pdf_and_leaves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "report.docx"
    src.write_bytes(b"source-bytes")
    before = src.read_bytes()
    dst = tmp_path / "report.pdf"
    fake_bin = tmp_path / "soffice"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    def fake_popen(argv, **kwargs):
        # Mimic soffice: write PDF into --outdir from argv.
        outdir = Path(argv[argv.index("--outdir") + 1])
        (outdir / "report.pdf").write_bytes(b"%PDF-1.4 fake")
        proc = MagicMock()
        proc.pid = 1
        proc.poll.return_value = 0
        proc.returncode = 0
        proc.stdout = MagicMock(read=lambda: "")
        proc.stderr = MagicMock(read=lambda: "")
        return proc

    monkeypatch.setattr(libreoffice, "popen_owned", fake_popen)
    # Real argv builder so outdir is correct; skip kill on fake pid.
    monkeypatch.setattr(libreoffice, "kill_process_tree", lambda _pid: None)

    result = convert_via_libreoffice(src, dst, soffice_path=str(fake_bin))
    assert result == dst
    assert dst.read_bytes().startswith(b"%PDF")
    assert src.read_bytes() == before


def test_install_hints_are_consent_only() -> None:
    assert DOWNLOAD_URL == "https://www.libreoffice.org/download/"
    assert "winget install" in WINGET_INSTALL_COMMAND
    assert "TheDocumentFoundation.LibreOffice" in WINGET_INSTALL_COMMAND
    assert " -e" in WINGET_INSTALL_COMMAND or WINGET_INSTALL_COMMAND.endswith("-e")


def test_missing_libreoffice_dialog_has_download_and_recheck(qtbot) -> None:
    from PyQt6.QtWidgets import QWidget

    from pagedrop.ui.dialogs import build_missing_libreoffice_dialog

    host = QWidget()
    qtbot.addWidget(host)
    dialog = build_missing_libreoffice_dialog(host, subject="Convert", detail="not found")
    names = {b.objectName() for b in dialog.buttons() if b.objectName()}
    assert "lo_recheck" in names
    assert "lo_download" in names
    texts = [b.text() for b in dialog.buttons()]
    assert any("Download" in t for t in texts)
    assert any("Recheck" in t for t in texts)
    if sys.platform == "win32":
        assert "lo_winget" in names
        assert WINGET_INSTALL_COMMAND in dialog.informativeText()
    else:
        assert "lo_winget" not in names
        assert "libreoffice.org" in DOWNLOAD_URL
