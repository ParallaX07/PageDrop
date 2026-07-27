"""Kill only process trees we own (helper subprocesses).

Used by Office COM / LibreOffice adapters on timeout and cancel. Never point
this at an arbitrary PID — only at processes started via the backend launchers.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any


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


def popen_owned(argv: list[str], **kwargs: Any) -> subprocess.Popen[str]:
    """``Popen`` configured so :func:`kill_process_tree` can reap children.

    POSIX: new session (``start_new_session``).
    Windows: new process group (``CREATE_NEW_PROCESS_GROUP``).
    """
    kwargs.setdefault("stdin", subprocess.PIPE)
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("text", True)
    if sys.platform == "win32":
        flags = kwargs.pop("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(argv, creationflags=flags, **kwargs)
    kwargs.setdefault("start_new_session", True)
    return subprocess.Popen(argv, **kwargs)
