"""Parent-side Microsoft Office COM → PDF launcher.

Spawns :mod:`pagedrop.helpers.office_com_worker` in a dedicated process with
JSON stdin/stdout IPC. Timeout and cancel kill **only** the owned helper
process tree (never an arbitrary WINWORD/EXCEL/POWERPNT the user started).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable

from pagedrop.core.backends.process_tree import kill_process_tree, popen_owned
from pagedrop.core.capabilities import OFFICE_COM, probe
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import (
    BackendUnavailableError,
    JobCancelledError,
    JobError,
)

# Default wall-clock budget for one conversion (large decks / slow disks).
DEFAULT_TIMEOUT_SEC = 300.0

# Poll interval while waiting on the helper (cancel responsiveness).
_POLL_SEC = 0.1


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

    request = {"input": str(src), "output": str(dst)}
    if on_progress is not None:
        on_progress("Converting with Microsoft Office…")

    proc = popen_owned(worker_argv())
    owned_pid = proc.pid
    stdout_data = ""
    stderr_data = ""
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(request, ensure_ascii=False))
        proc.stdin.close()

        deadline = time.monotonic() + max(0.1, float(timeout_sec))
        while proc.poll() is None:
            if cancel is not None and cancel.is_cancelled():
                kill_process_tree(owned_pid)
                proc.wait(timeout=5)
                raise JobCancelledError("Office COM conversion cancelled")
            if time.monotonic() >= deadline:
                kill_process_tree(owned_pid)
                proc.wait(timeout=5)
                raise OfficeComConversionError(
                    f"Office COM conversion timed out after {timeout_sec:.0f}s",
                    code="timeout",
                )
            time.sleep(_POLL_SEC)

        stdout_data = proc.stdout.read() if proc.stdout else ""
        stderr_data = proc.stderr.read() if proc.stderr else ""
    except (JobCancelledError, OfficeComConversionError):
        raise
    except Exception:
        kill_process_tree(owned_pid)
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        # Reap if still alive (belt-and-braces — should already be dead).
        if proc.poll() is None:
            kill_process_tree(owned_pid)
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass

    response = _parse_response(stdout_data, stderr_data, proc.returncode)
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
