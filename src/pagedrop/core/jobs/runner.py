"""Serialized job runner — private lock, no UI QThreadPool, paths only.

PyMuPDF must not be shared with ad-hoc editor thumbnail / preview pools.
Handlers open documents by path inside the handler (see ``thread_policy``).
A process-wide lock serializes job bodies so tool jobs never pile onto UI
``QThreadPool`` workers. Long-term upgrade: dedicated PDF service process
(multiprocessing) for fitz-heavy handlers — same stage/promote/cancel API.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.credentials import RuntimeCredentials
from pagedrop.core.jobs.errors import JobError
from pagedrop.core.jobs.paths import ensure_output_destination
from pagedrop.core.jobs.spec import JobSpec, ProgressCallback, _noop_progress
from pagedrop.core.jobs.staging import JobStaging
from pagedrop.core.thread_policy import ensure_no_fitz_document
from pagedrop.utils.temp_manager import TempManager

JobHandler = Callable[["JobContext"], Path]
"""Write staged output; return the staged path to promote."""


@dataclass
class JobContext:
    """Runtime context for a registered handler."""

    spec: JobSpec
    staging: JobStaging
    staged_output: Path
    credentials: RuntimeCredentials
    cancel: CancelToken
    progress: ProgressCallback
    temp_manager: TempManager


class SerializedJobRunner:
    """Run tool jobs one at a time; stage → handler → promote; cleanup on fail.

    Never shares ``fitz.Document`` instances with UI thread pools. Callers pass
    paths on ``JobSpec``; handlers open by path. Cancel removes partial staged
    output. Source overwrite is rejected like Save As.
    """

    _run_lock = threading.Lock()

    def __init__(self, temp_manager: TempManager | None = None) -> None:
        self._temp_manager = temp_manager or TempManager()
        self._handlers: dict[str, JobHandler] = {}
        self._active_cancel: CancelToken | None = None
        self._active_lock = threading.Lock()

    @property
    def temp_manager(self) -> TempManager:
        return self._temp_manager

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    def cancel_active(self) -> None:
        with self._active_lock:
            if self._active_cancel is not None:
                self._active_cancel.cancel()

    def run(
        self,
        spec: JobSpec,
        *,
        credentials: RuntimeCredentials | None = None,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> Path:
        """Execute *spec*; return the promoted user output path."""
        ensure_no_fitz_document(
            *spec.inputs,
            spec.output,
            *spec.options.values(),
            what="JobSpec",
        )
        ensure_output_destination(
            spec.output,
            sources=spec.inputs,
            overwrite=spec.overwrite,
        )

        token = cancel or CancelToken()
        report = progress or _noop_progress
        creds = credentials or RuntimeCredentials()
        staging = JobStaging(self._temp_manager)
        staged = staging.stage_file(Path(spec.output).name)

        handler = self._handlers.get(spec.job_type)
        if handler is None:
            staging.cleanup()
            raise JobError(f"No handler registered for job type: {spec.job_type}")

        with self._active_lock:
            self._active_cancel = token

        try:
            with self._run_lock:
                token.check()
                report(0.0, "Starting…")
                ctx = JobContext(
                    spec=spec,
                    staging=staging,
                    staged_output=staged,
                    credentials=creds,
                    cancel=token,
                    progress=report,
                    temp_manager=self._temp_manager,
                )
                result_staged = Path(handler(ctx))
                token.check()
                report(0.95, "Promoting output…")
                promoted = staging.promote(result_staged, Path(spec.output))
                report(1.0, "Done")
                return promoted
        except Exception:
            staging.cleanup()
            raise
        finally:
            with self._active_lock:
                if self._active_cancel is token:
                    self._active_cancel = None
            if staging.job_dir.exists():
                try:
                    staging.job_dir.rmdir()
                except OSError:
                    pass
