"""LibreOffice (soffice) conversion adapter.

Invokes a separately installed ``soffice`` in headless mode with a **temporary
user profile** so the user's interactive LibreOffice session is undisturbed.
Timeout and cancel kill only the owned process tree and always remove the
profile directory.

Never bundles LibreOffice. Detection lives in :mod:`pagedrop.core.capabilities`.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Callable

from pagedrop.core.backends.process_tree import run_owned
from pagedrop.core.capabilities import LIBREOFFICE, find_soffice, probe
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import (
    BackendUnavailableError,
    JobCancelledError,
    JobError,
)
from pagedrop.utils.temp_manager import claim_backend_temp, release_backend_temp

# Default wall-clock budget for one conversion (large decks / slow disks).
DEFAULT_TIMEOUT_SEC = 300.0

# Consent-only install hints (UI opens download or copies this — never runs installers).
DOWNLOAD_URL = "https://www.libreoffice.org/download/"
WINGET_INSTALL_COMMAND = (
    "winget install --id TheDocumentFoundation.LibreOffice -e"
)


class LibreOfficeConversionError(JobError):
    """soffice failed, timed out, or produced no output."""

    def __init__(self, message: str, code: str = "libreoffice_error") -> None:
        self.code = code
        super().__init__(message)


def libreoffice_available(*, soffice_path: str | None = None) -> bool:
    """True when a usable soffice binary is detected (or *soffice_path* exists)."""
    if soffice_path:
        return Path(soffice_path).is_file()
    return probe(LIBREOFFICE).available


def convert_via_libreoffice(
    input_path: str | Path,
    output_path: str | Path,
    *,
    convert_to: str = "pdf",
    infilter: str | None = None,
    soffice_path: str | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    cancel: CancelToken | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Convert *input_path* to *convert_to* format at *output_path* via headless LO.

    *infilter* is passed as ``--infilter=…`` when set (e.g. ``writer_pdf_import``
    so PDF opens in Writer and can export DOCX).

    Raises:
        BackendUnavailableError: soffice not found
        JobCancelledError: cancel token fired
        LibreOfficeConversionError: conversion failed or timed out
    """
    target = convert_to.strip().lower()
    if not target:
        raise LibreOfficeConversionError(
            "LibreOffice convert-to target is empty", code="bad_target"
        )
    suffix = f".{target.split(':', 1)[0]}"

    binary = soffice_path or find_soffice()
    if not binary or not Path(binary).is_file():
        status = probe(LIBREOFFICE)
        raise BackendUnavailableError(
            LIBREOFFICE,
            status.reason or "engine_missing",
            status.detail or "LibreOffice (soffice) not found",
        )

    src = Path(input_path).resolve()
    dst = Path(output_path).resolve()
    if not src.is_file():
        raise LibreOfficeConversionError(f"Input not found: {src}", code="input_missing")
    if src == dst:
        raise LibreOfficeConversionError(
            "Output path must not overwrite the source file",
            code="source_overwrite",
        )
    dst.parent.mkdir(parents=True, exist_ok=True)

    if on_progress is not None:
        on_progress("Converting with LibreOffice…")

    profile_dir = claim_backend_temp(
        Path(tempfile.mkdtemp(prefix="pagedrop_lo_profile_"))
    )
    outdir = claim_backend_temp(Path(tempfile.mkdtemp(prefix="pagedrop_lo_out_")))
    try:
        argv = build_convert_argv(
            binary,
            src,
            outdir,
            profile_dir,
            convert_to=target,
            infilter=infilter,
        )
        result = run_owned(argv, stdin=None, timeout=max(0.1, float(timeout_sec)), cancel=cancel)
        if result.cancelled:
            raise JobCancelledError("LibreOffice conversion cancelled")
        if result.timed_out:
            raise LibreOfficeConversionError(
                f"LibreOffice conversion timed out after {timeout_sec:.0f}s",
                code="timeout",
            )
        stdout, stderr = result.stdout, result.stderr
        if result.returncode not in (0, None):
            detail = (stderr or stdout or "").strip() or f"exit {result.returncode}"
            raise LibreOfficeConversionError(
                f"LibreOffice conversion failed: {detail}",
                code="soffice_failed",
            )

        produced = _expected_output(outdir, src, suffix=suffix)
        if produced is None or not produced.is_file():
            detail = (stderr or stdout or "").strip()
            raise LibreOfficeConversionError(
                f"LibreOffice produced no {suffix.lstrip('.').upper()}"
                f"{': ' + detail if detail else ''}",
                code="empty_output",
            )
        if dst.exists():
            dst.unlink()
        shutil.move(str(produced), str(dst))
        return dst
    finally:
        release_backend_temp(profile_dir)
        release_backend_temp(outdir)
        shutil.rmtree(profile_dir, ignore_errors=True)
        shutil.rmtree(outdir, ignore_errors=True)


def build_convert_argv(
    soffice: str | Path,
    input_path: Path,
    outdir: Path,
    profile_dir: Path,
    *,
    convert_to: str = "pdf",
    infilter: str | None = None,
) -> list[str]:
    """Build ``soffice --headless --convert-to …`` with a temp user profile."""
    argv = [
        str(soffice),
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        "--norestore",
        f"-env:UserInstallation={_user_installation_uri(profile_dir)}",
    ]
    # PDF defaults to Draw; Writer import is required for DOCX (and similar) export.
    if infilter:
        argv.append(f"--infilter={infilter}")
    argv.extend(
        [
            "--convert-to",
            convert_to,
            "--outdir",
            str(outdir.resolve()),
            str(input_path.resolve()),
        ]
    )
    return argv


def _user_installation_uri(profile_dir: Path) -> str:
    """``file://`` URI for ``-env:UserInstallation=`` (spaces / Unicode safe)."""
    resolved = profile_dir.resolve()
    # Path.as_uri() quotes correctly; LO accepts file:///… on all platforms.
    return resolved.as_uri()


def _expected_output(outdir: Path, src: Path, *, suffix: str) -> Path | None:
    """LibreOffice writes ``<stem>.<ext>`` into *outdir* (same stem as the source)."""
    candidate = outdir / f"{src.stem}{suffix}"
    if candidate.is_file():
        return candidate
    matches = sorted(outdir.glob(f"*{suffix}"))
    if len(matches) == 1:
        return matches[0]
    return None


def _expected_pdf(outdir: Path, src: Path) -> Path | None:
    """Compatibility alias — prefer :func:`_expected_output`."""
    return _expected_output(outdir, src, suffix=".pdf")
