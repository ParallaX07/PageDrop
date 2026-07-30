"""Smoke tests — built executable launch.

Skipped unless PAGEDROP_EXE points at a built binary:

    # Windows
    $env:PAGEDROP_EXE = ".\\dist\\pagedrop.exe"
    uv run pytest tests/smoke/test_phase16_executable.py -v

    # Linux/macOS
    PAGEDROP_EXE=./dist/pagedrop uv run pytest tests/smoke/test_phase16_executable.py -v

Full release gate (run before tagging):

    uv run pytest tests/ -v --ignore=tests/smoke/test_phase16_executable.py
    PAGEDROP_EXE=./dist/pagedrop uv run pytest tests/smoke/test_phase16_executable.py -v
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

_ALIVE_SECONDS = 5
_STARTUP_TIMEOUT = 30


def _exe_path() -> Path | None:
    raw = os.environ.get("PAGEDROP_EXE")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        pytest.fail(f"PAGEDROP_EXE does not exist: {path}")
    return path.resolve()


@pytest.mark.skipif(_exe_path() is None, reason="PAGEDROP_EXE not set")
def test_executable_stays_alive():
    """Built binary starts and does not exit within the smoke window."""
    exe = _exe_path()
    assert exe is not None

    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    proc = subprocess.Popen(
        [str(exe)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        deadline = time.monotonic() + _STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            code = proc.poll()
            if code is not None:
                stdout, stderr = proc.communicate(timeout=5)
                pytest.fail(
                    f"Executable exited early (code {code})\n"
                    f"stdout: {stdout.decode(errors='replace')}\n"
                    f"stderr: {stderr.decode(errors='replace')}"
                )
            time.sleep(0.25)

        time.sleep(_ALIVE_SECONDS)
        code = proc.poll()
        assert code is None, f"Executable exited during alive window (code {code})"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
