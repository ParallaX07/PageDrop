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
import time
from pathlib import Path
from typing import Callable

from pagedrop.core.backends.process_tree import kill_process_tree, popen_owned
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

_POLL_SEC = 0.1

# Consent-only install hints (UI opens these on user click — never silent).
DOWNLOAD_URL = "https://www.libreoffice.org/download/"
WINGET_INSTALL_ARGV = (
    "winget",
    "install",
    "--id",
    "TheDocumentFoundation.LibreOffice",
    "-e",
)
WINGET_INSTALL_COMMAND = " ".join(WINGET_INSTALL_ARGV)


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
    owned_pid: int | None = None
    try:
        argv = build_convert_argv(
            binary,
            src,
            outdir,
            profile_dir,
            convert_to=target,
            infilter=infilter,
        )
        proc = popen_owned(argv, stdin=None)
        owned_pid = proc.pid
        deadline = time.monotonic() + max(0.1, float(timeout_sec))
        while proc.poll() is None:
            if cancel is not None and cancel.is_cancelled():
                kill_process_tree(owned_pid)
                _wait_reap(proc)
                raise JobCancelledError("LibreOffice conversion cancelled")
            if time.monotonic() >= deadline:
                kill_process_tree(owned_pid)
                _wait_reap(proc)
                raise LibreOfficeConversionError(
                    f"LibreOffice conversion timed out after {timeout_sec:.0f}s",
                    code="timeout",
                )
            time.sleep(_POLL_SEC)

        stdout = proc.stdout.read() if proc.stdout else ""
        stderr = proc.stderr.read() if proc.stderr else ""
        if proc.returncode not in (0, None):
            detail = (stderr or stdout or "").strip() or f"exit {proc.returncode}"
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
    except (JobCancelledError, LibreOfficeConversionError, BackendUnavailableError):
        raise
    except Exception:
        if owned_pid is not None:
            kill_process_tree(owned_pid)
        raise
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


def _wait_reap(proc: object, timeout: float = 5.0) -> None:
    """Wait for a killed helper; ignore wait timeout (tree kill is best-effort)."""
    wait = getattr(proc, "wait", None)
    if wait is None:
        return
    try:
        wait(timeout=timeout)
    except Exception:  # noqa: BLE001 — TimeoutExpired / already dead
        try:
            kill_process_tree(int(getattr(proc, "pid", 0) or 0))
        except Exception:  # noqa: BLE001
            pass
