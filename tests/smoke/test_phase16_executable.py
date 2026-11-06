"""Smoke tests — built executable launch and helper re-entry flags.

The launch test checks the binary stays alive. The re-entry probes run the
binary with each helper flag the app uses to start its own worker processes
(redaction verifier, lossy compressor, Office COM worker) and check the reply.
A frozen process always exits 0 from the entry point, so the probes assert on
the reply (JSON on stdout, or the output file), never the return code.

Skipped unless PAGEDROP_EXE points at a built binary:

    # Windows (onedir)
    $env:PAGEDROP_EXE = ".\\dist\\pagedrop\\pagedrop.exe"
    uv run pytest tests/smoke/test_phase16_executable.py -v

    # Linux/macOS (onedir)
    PAGEDROP_EXE=./dist/pagedrop/pagedrop uv run pytest tests/smoke/test_phase16_executable.py -v

Full release gate (run before tagging):

    uv run pytest tests/ -v --ignore=tests/smoke/test_phase16_executable.py
    PAGEDROP_EXE=./dist/pagedrop/pagedrop uv run pytest tests/smoke/test_phase16_executable.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import fitz
import pytest

from pagedrop.core.optimize_secure import COMPRESS_WORKER_FLAG
from pagedrop.core.redact import REDACT_VERIFY_FLAG
from tests.conftest import file_sha256

_ALIVE_SECONDS = 5
_STARTUP_TIMEOUT = 30
_RUN_TIMEOUT = 120


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


# --- helper re-entry probes -------------------------------------------------

_needs_exe = pytest.mark.skipif(_exe_path() is None, reason="PAGEDROP_EXE not set")
_COM_WORKER_FLAG = "--pagedrop-office-com-worker"
_SECRET = "frozen-probe-secret"


def _run_frozen(args: list[str], stdin_text: str) -> subprocess.CompletedProcess[str]:
    """Run the built binary with *args*, feeding *stdin_text*; never checks the exit code."""
    exe = _exe_path()
    assert exe is not None
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return subprocess.run(
        [str(exe), *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=_RUN_TIMEOUT,
        env=env,
    )


def _text_pdf(path: Path) -> Path:
    doc = fitz.open()
    try:
        doc.new_page(width=300, height=200).insert_text((30, 60), f"keep {_SECRET} here")
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _reply(proc: subprocess.CompletedProcess[str]) -> dict:
    lines = proc.stdout.strip().splitlines()
    assert len(lines) == 1, f"expected one JSON line\nstdout: {proc.stdout!r}\nstderr: {proc.stderr!r}"
    return json.loads(lines[0])


@_needs_exe
@pytest.mark.timeout(180)
def test_frozen_redact_verifier_reads_the_file(tmp_path: Path):
    src = _text_pdf(tmp_path / "src.pdf")
    before = file_sha256(src)
    args = [REDACT_VERIFY_FLAG, "--verify-json"]

    absent = _reply(_run_frozen(args, json.dumps({"path": str(src), "absent_text": ["not in this pdf"]})))
    assert absent["failures"] == []

    present = _reply(_run_frozen(args, json.dumps({"path": str(src), "absent_text": [_SECRET]})))
    assert present["failures"], "verifier must flag text that is still in the PDF"
    assert file_sha256(src) == before


@_needs_exe
@pytest.mark.timeout(180)
def test_frozen_redact_verifier_fails_closed_on_empty_stdin():
    reply = _reply(_run_frozen([REDACT_VERIFY_FLAG, "--verify-json"], ""))
    assert reply["failures"]


@_needs_exe
@pytest.mark.timeout(180)
def test_frozen_compress_worker_writes_output(tmp_path: Path):
    src = _text_pdf(tmp_path / "src.pdf")
    out = tmp_path / "out.pdf"
    before = file_sha256(src)
    payload = {
        "source": str(src),
        "output": str(out),
        "name": "probe",
        "dpi": 72,
        "jpeg_quality": 50,
        "dpi_threshold": 100,
        "password": None,
    }
    proc = _run_frozen([COMPRESS_WORKER_FLAG, "--compress-json"], json.dumps(payload))
    assert out.is_file(), f"no output written\nstderr: {proc.stderr!r}"
    assert out.resolve() != src.resolve()
    with fitz.open(str(out)) as doc:
        assert doc.page_count == 1
    assert file_sha256(src) == before


@_needs_exe
@pytest.mark.timeout(180)
@pytest.mark.parametrize("stdin_text", ["", "not json"], ids=["empty", "bad-json"])
def test_frozen_com_worker_rejects_bad_request(stdin_text: str):
    reply = _reply(_run_frozen([_COM_WORKER_FLAG], stdin_text))
    assert reply["ok"] is False
    assert reply["code"] == "bad_request"


@_needs_exe
@pytest.mark.timeout(180)
@pytest.mark.skipif(sys.platform != "win32", reason="Office COM is Windows only")
def test_frozen_com_worker_bundles_pywin32(tmp_path: Path):
    """The request must get past the pywin32 import; the document is junk, not real Office work."""
    src = tmp_path / "probe.docx"
    src.write_bytes(b"not a real document")
    request = {"input": str(src), "output": str(tmp_path / "probe.pdf")}
    reply = _reply(_run_frozen([_COM_WORKER_FLAG], json.dumps(request)))
    assert reply["ok"] is False
    assert reply["code"] != "pywin32_missing", reply
