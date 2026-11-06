"""run_owned / reap_owned: pipes are drained, trees are reaped, waits stay bounded."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from pagedrop.core.backends import process_tree
from pagedrop.core.backends.process_tree import reap_owned, run_owned
from pagedrop.core.jobs.cancel import CancelToken

_SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_run_owned_returns_output_and_exit_code() -> None:
    result = run_owned(
        _py("import sys; print('out'); sys.stderr.write('err'); sys.exit(3)"), timeout=10
    )
    assert (result.returncode, result.stdout.strip(), result.stderr) == (3, "out", "err")
    assert not result.cancelled and not result.timed_out


def test_run_owned_drains_more_than_a_pipe_buffer_of_stderr() -> None:
    t0 = time.monotonic()
    result = run_owned(
        _py("import sys; sys.stderr.write('x' * 200_000); sys.exit(1)"), timeout=20
    )
    assert result.returncode == 1 and len(result.stderr) == 200_000
    assert not result.timed_out
    assert time.monotonic() - t0 < 10


def test_run_owned_sends_input_once_across_poll_iterations() -> None:
    result = run_owned(
        _py("import sys, time; data = sys.stdin.read(); time.sleep(0.5); print(data)"),
        input="payload",
        timeout=20,
        poll=0.05,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "payload"


def test_run_owned_survives_non_utf8_output() -> None:
    result = run_owned(
        _py("import sys; sys.stdout.buffer.write(b'ok\\xff\\xfe')"), timeout=10
    )
    assert result.returncode == 0
    assert result.stdout.startswith("ok")


def test_run_owned_timeout_kills_and_reports() -> None:
    t0 = time.monotonic()
    result = run_owned(_SLEEPER, timeout=0.3, poll=0.05)
    assert result.timed_out and not result.cancelled
    assert result.returncode is not None and result.returncode != 0
    assert time.monotonic() - t0 < 10


def test_run_owned_cancel_mid_run_kills_and_reports() -> None:
    token = CancelToken()
    threading.Timer(0.2, token.cancel).start()
    result = run_owned(_SLEEPER, timeout=30, cancel=token, poll=0.05)
    assert result.cancelled and not result.timed_out
    assert result.returncode is not None


def test_run_owned_already_cancelled_never_spawns(monkeypatch: pytest.MonkeyPatch) -> None:
    spawned: list[object] = []
    monkeypatch.setattr(process_tree, "popen_owned", lambda *a, **k: spawned.append(1))
    token = CancelToken()
    token.cancel()
    result = run_owned(_SLEEPER, timeout=30, cancel=token)
    assert result.cancelled and not spawned


def test_run_owned_unexpected_error_reaps_child_before_reraising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    procs: list[subprocess.Popen[str]] = []
    real = process_tree.popen_owned

    def spy(argv: list[str], **kwargs: object) -> subprocess.Popen[str]:
        procs.append(real(argv, **kwargs))
        return procs[-1]

    class _ExplodingToken:
        calls = 0

        def is_cancelled(self) -> bool:
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("boom")
            return False

    monkeypatch.setattr(process_tree, "popen_owned", spy)
    with pytest.raises(RuntimeError, match="boom"):
        run_owned(_SLEEPER, timeout=30, cancel=_ExplodingToken(), poll=0.05)  # type: ignore[arg-type]
    assert len(procs) == 1 and procs[0].poll() is not None


def test_reap_owned_stays_bounded_when_a_grandchild_holds_the_pipe(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],"
        " start_new_session=True)\n"
        f"open({str(pid_file)!r}, 'w').write(str(g.pid))\n"
        "time.sleep(60)\n"
    )
    proc = process_tree.popen_owned(_py(script))
    grandchild = 0
    try:
        deadline = time.monotonic() + 20
        while not pid_file.exists() or not pid_file.read_text():
            assert time.monotonic() < deadline, "child never started"
            time.sleep(0.02)
        grandchild = int(pid_file.read_text())
        t0 = time.monotonic()
        reap_owned(proc, timeout=0.5)
        assert time.monotonic() - t0 < 5
        assert proc.poll() is not None
    finally:
        if grandchild:
            process_tree.kill_process_tree(grandchild)
        if proc.poll() is None:
            proc.kill()
            proc.wait()
