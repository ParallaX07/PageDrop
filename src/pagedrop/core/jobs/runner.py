"""Serialized job runner — stage / promote / cancel; paths only.

PyMuPDF must not be shared with ad-hoc editor thumbnail / preview pools.
Handlers open documents by path inside the handler (see ``thread_policy``).
Fitz-using handlers take the shared ``FITZ_LOCK`` around the handler body so
tool jobs serialize with the viewer PDF service. Handlers that only wait on
external converters (Office COM / LibreOffice) register with
``holds_fitz=False`` so subprocess waits never stall interactive fitz work.
Long-term upgrade: dedicated PDF service process (multiprocessing) for
fitz-heavy handlers — same stage/promote/cancel API.
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
from pagedrop.core.pdf_service import FITZ_LOCK
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
    # Transient secrets (encrypt passwords, etc.) — never on JobSpec / disk.
    secrets: dict[str, str]

    def password(self, path: str | None = None) -> str | None:
        """Credential for *path*, or the first job input if omitted."""
        return self.credentials.get(path or self.spec.inputs[0])


@dataclass(frozen=True)
class _HandlerEntry:
    handler: JobHandler
    # When True, run under FITZ_LOCK (whole body is fitz work). When False,
    # handler must take FITZ_LOCK only around any fitz open/work/close itself.
    holds_fitz: bool = True


class SerializedJobRunner:
    """Run tool jobs; stage → handler → promote; cleanup on fail.

    Never shares ``fitz.Document`` instances with UI thread pools. Callers pass
    paths on ``JobSpec``; handlers open by path. Cancel removes partial staged
    output. Source overwrite is rejected like Save As.

    ``FITZ_LOCK`` stays process-global for all in-process fitz (UI
    thumbnail/merge/convert pools must take it too). Ceiling: one global gate
    stalls unrelated fitz while a long fitz *job* holds it. Upgrade: dedicated
    PDF service process (O10) so jobs never share MuPDF caches with the viewer;
    until then never hold the lock across Office / LibreOffice / other external
    waits (``holds_fitz=False``).
    """

    def __init__(self, temp_manager: TempManager | None = None) -> None:
        self._temp_manager = temp_manager or TempManager()
        self._handlers: dict[str, _HandlerEntry] = {}
        self._active_cancel: CancelToken | None = None
        self._active_lock = threading.Lock()

    @property
    def temp_manager(self) -> TempManager:
        return self._temp_manager

    def register(
        self,
        job_type: str,
        handler: JobHandler,
        *,
        holds_fitz: bool = True,
    ) -> None:
        """Register *handler* for *job_type*.

        *holds_fitz* (default True): wrap the handler in ``FITZ_LOCK``. Pass
        False for Office / LibreOffice / other long external waits; those
        handlers must lock only around any brief fitz validate/open/close.
        """
        self._handlers[job_type] = _HandlerEntry(handler, holds_fitz=holds_fitz)

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
        secrets: dict[str, str] | None = None,
    ) -> Path:
        """Execute *spec*; return the promoted user output path."""
        # Hygiene: only path-like option values — nested dicts/lists/ints are not Documents.
        option_paths = [
            v for v in spec.options.values() if isinstance(v, (str, Path))
        ]
        ensure_no_fitz_document(
            *spec.inputs,
            spec.output,
            *option_paths,
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
        runtime_secrets = dict(secrets or {})
        staging = JobStaging(self._temp_manager)
        staged = staging.stage_file(Path(spec.output).name)

        entry = self._handlers.get(spec.job_type)
        if entry is None:
            staging.cleanup()
            raise JobError(f"No handler registered for job type: {spec.job_type}")

        with self._active_lock:
            self._active_cancel = token

        try:
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
                secrets=runtime_secrets,
            )
            if entry.holds_fitz:
                with FITZ_LOCK:
                    result_staged = Path(entry.handler(ctx))
                    token.check()
            else:
                result_staged = Path(entry.handler(ctx))
                token.check()
            report(0.95, "Promoting output…")
            promoted = staging.promote(result_staged, Path(spec.output))
            report(1.0, "Done")
            return promoted
        except Exception:
            staging.cleanup()
            raise
        finally:
            runtime_secrets.clear()
            with self._active_lock:
                if self._active_cancel is token:
                    self._active_cancel = None
            if staging.job_dir.exists():
                try:
                    staging.job_dir.rmdir()
                except OSError:
                    pass
