"""Kill only process trees we own (helper subprocesses).

Used by Office COM / LibreOffice adapters on timeout and cancel. Never point
this at an arbitrary PID — only at processes started via the backend launchers.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

from pagedrop.core.jobs.cancel import CancelToken


def kill_process_tree(pid: int) -> None:
    """Terminate *pid* and its descendants.

    Windows: ``taskkill /F /T`` (parent/child tree).
    POSIX: signal the process group when *pid* is a session leader (helpers are
    started with ``start_new_session=True``); otherwise SIGKILL the pid alone.
    """
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            check=False,
            capture_output=True,
            text=True,
        )
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return


def frozen_child_env() -> dict[str, str] | None:
    """Environment for PageDrop's own frozen helpers (``None``: inherit as-is).

    The frozen app clears the bundled ``LD_LIBRARY_PATH`` from its environment so
    external programs don't load bundled libraries. A helper that re-enters this
    exe inherits the bootloader's markers and skips setting the path itself, so
    it gets the bundle directory back to keep using the libraries it shipped with.
    """
    if not (getattr(sys, "frozen", False) and sys.platform.startswith("linux")):
        return None
    env = os.environ.copy()
    bundle = str(getattr(sys, "_MEIPASS", ""))
    if bundle:
        inherited = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = f"{bundle}:{inherited}" if inherited else bundle
    return env


def popen_owned(argv: list[str], **kwargs: Any) -> subprocess.Popen[str]:
    """``Popen`` configured so :func:`kill_process_tree` can reap children.

    POSIX: new session (``start_new_session``).
    Windows: new process group (``CREATE_NEW_PROCESS_GROUP``).
    """
    kwargs.setdefault("stdin", subprocess.PIPE)
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("text", True)
    # A child's stray non-UTF-8 bytes must not blow up the reader.
    kwargs.setdefault("errors", "replace")
    if sys.platform == "win32":
        flags = kwargs.pop("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(argv, creationflags=flags, **kwargs)
    kwargs.setdefault("start_new_session", True)
    return subprocess.Popen(argv, **kwargs)


def reap_owned(proc: subprocess.Popen[str], timeout: float = 5.0) -> None:
    """Kill *proc*'s tree and wait for it, never longer than about *timeout*.

    A grandchild that keeps a pipe open cannot stall this: after the bounded
    drain the child itself is killed and the pipe ends are closed.
    """
    kill_process_tree(proc.pid)
    try:
        proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
    except (OSError, ValueError):
        pass
    finally:
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except (OSError, ValueError):
                pass


@dataclass(frozen=True)
class OwnedResult:
    """Outcome of :func:`run_owned`; callers map it to their own typed errors."""

    returncode: int | None
    pid: int = 0
    stdout: str = ""
    stderr: str = ""
    cancelled: bool = False
    timed_out: bool = False


def run_owned(
    argv: list[str],
    *,
    timeout: float,
    input: str | None = None,
    cancel: CancelToken | None = None,
    poll: float = 0.1,
    **popen_kwargs: Any,
) -> OwnedResult:
    """Run an owned child to completion, draining its pipes while it runs.

    Cancel and timeout kill and reap the whole tree and are reported on the
    result. Any other exception also kills and reaps before it propagates.
    *input* is written once, on the first exchange. A failure to start the
    child raises ``OSError`` from :func:`popen_owned`.
    """
    if cancel is not None and cancel.is_cancelled():
        return OwnedResult(None, cancelled=True)
    proc = popen_owned(argv, **popen_kwargs)
    deadline = time.monotonic() + timeout
    pending_input = input
    try:
        while True:
            if cancel is not None and cancel.is_cancelled():
                reap_owned(proc)
                return OwnedResult(proc.returncode, proc.pid, cancelled=True)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reap_owned(proc)
                return OwnedResult(proc.returncode, proc.pid, timed_out=True)
            try:
                stdout, stderr = proc.communicate(pending_input, timeout=min(poll, remaining))
            except subprocess.TimeoutExpired:
                pending_input = None
                continue
            return OwnedResult(proc.returncode, proc.pid, stdout or "", stderr or "")
    except BaseException:
        reap_owned(proc)
        raise
