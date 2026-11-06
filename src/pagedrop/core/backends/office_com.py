"""Parent-side Microsoft Office COM → PDF launcher.

Spawns :mod:`pagedrop.helpers.office_com_worker` in a dedicated process with
JSON stdin/stdout IPC. Timeout and cancel kill **only** the owned helper
process tree plus the one Office app the helper reports having launched (never
an arbitrary WINWORD/EXCEL/POWERPNT the user started).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

from pagedrop.core.backends.process_tree import kill_process_tree, run_owned
from pagedrop.core.capabilities import OFFICE_COM, probe
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import (
    BackendUnavailableError,
    JobCancelledError,
    JobError,
)
from pagedrop.utils.temp_manager import claim_backend_temp, release_backend_temp

# Default wall-clock budget for one conversion (large decks / slow disks).
DEFAULT_TIMEOUT_SEC = 300.0


class OfficeComConversionError(JobError):
    """COM helper returned a structured failure (or crashed)."""

    def __init__(self, message: str, code: str = "office_com_error") -> None:
        self.code = code
        super().__init__(message)


def worker_argv() -> list[str]:
    """Argv that starts the COM worker in a fresh interpreter / frozen exe."""
    if getattr(sys, "frozen", False):
        # Wired in main() before QApplication — same binary, worker mode.
        return [sys.executable, "--pagedrop-office-com-worker"]
    return [sys.executable, "-m", "pagedrop.helpers.office_com_worker"]


def com_available() -> bool:
    """True when the capability registry reports Office COM ready."""
    return probe(OFFICE_COM).available


def convert_via_com(
    input_path: str | Path,
    output_path: str | Path,
    *,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    cancel: CancelToken | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Convert *input_path* to PDF at *output_path* via the COM helper process.

    Raises:
        BackendUnavailableError: not Windows / no pywin32 / no Office ProgIDs
        JobCancelledError: cancel token fired
        OfficeComConversionError: helper reported failure or timed out
    """
    status = probe(OFFICE_COM)
    if not status.available:
        raise BackendUnavailableError(
            OFFICE_COM,
            status.reason or "engine_missing",
            status.detail,
        )

    src = Path(input_path).resolve()
    dst = Path(output_path).resolve()
    if not src.is_file():
        raise OfficeComConversionError(f"Input not found: {src}", code="input_missing")
    if src == dst:
        raise OfficeComConversionError(
            "Output path must not overwrite the source Office file",
            code="source_overwrite",
        )
    dst.parent.mkdir(parents=True, exist_ok=True)

    pid_dir = claim_backend_temp(Path(tempfile.mkdtemp(prefix="pagedrop_com_")))
    pid_file = pid_dir / "office.pid"
    request = {"input": str(src), "output": str(dst), "pid_file": str(pid_file)}
    if on_progress is not None:
        on_progress("Converting with Microsoft Office…")

    worker_pid = 0
    try:
        result = run_owned(
            worker_argv(),
            input=json.dumps(request),
            timeout=max(0.1, float(timeout_sec)),
            cancel=cancel,
        )
        worker_pid = result.pid
        if result.cancelled or result.timed_out:
            _kill_reported_office(pid_file, worker_pid)
        if result.cancelled:
            raise JobCancelledError("Office COM conversion cancelled")
        if result.timed_out:
            raise OfficeComConversionError(
                f"Office COM conversion timed out after {timeout_sec:.0f}s",
                code="timeout",
            )
        response = _parse_response(result.stdout, result.stderr, result.returncode)
        if response.get("code") == "worker_crash" and not response.get("ok"):
            # The worker died (or broke) without a clean answer; the Office app
            # it launched may still be running.
            _kill_reported_office(pid_file, worker_pid)
    except (JobCancelledError, OfficeComConversionError):
        raise
    except BaseException:
        _kill_reported_office(pid_file, worker_pid)
        raise
    finally:
        release_backend_temp(pid_dir)
        shutil.rmtree(pid_dir, ignore_errors=True)

    if not response.get("ok"):
        raise OfficeComConversionError(
            str(response.get("error") or "Office COM conversion failed"),
            code=str(response.get("code") or "office_com_error"),
        )
    out = Path(str(response.get("output") or dst))
    if not out.is_file():
        raise OfficeComConversionError(
            "COM helper reported success but PDF is missing",
            code="empty_output",
        )
    return out


def _kill_reported_office(pid_file: Path, worker_pid: int) -> None:
    """Kill the Office app the worker reported it started (best effort).

    The worker writes the PID of the app it launched into *pid_file*. It is
    killed only if it is a positive int that is neither this process nor the
    worker; no file (lookup failed or never reached) means nothing to do.
    """
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if pid > 0 and pid not in (os.getpid(), worker_pid):
        kill_process_tree(pid)


def _parse_response(
    stdout: str, stderr: str, returncode: int | None
) -> dict[str, object]:
    text = (stdout or "").strip()
    if text:
        # Worker prints one JSON object (last non-empty line wins if noisy).
        line = text.splitlines()[-1]
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    detail = (stderr or "").strip() or text or f"exit {returncode}"
    return {
        "ok": False,
        "error": f"COM helper returned unreadable output: {detail}",
        "code": "worker_crash",
    }
