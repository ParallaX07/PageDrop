"""Cooperative cancel for long-running jobs."""

from __future__ import annotations

import threading

from pagedrop.core.jobs.errors import JobCancelledError


class CancelToken:
    """Thread-safe cancel flag; ``check()`` raises ``JobCancelledError``."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise JobCancelledError("Job cancelled")


def check_cancel(cancel: CancelToken | None) -> None:
    """No-op when *cancel* is None; otherwise ``cancel.check()``."""
    if cancel is not None:
        cancel.check()
