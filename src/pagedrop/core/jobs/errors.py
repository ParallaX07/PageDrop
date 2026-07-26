"""Typed errors for Tools / batch jobs."""

from __future__ import annotations

from pagedrop.core.capabilities import AbsenceReason


class JobError(Exception):
    """Base class for job-layer failures (not bare Exception for UI)."""


class JobCancelledError(JobError):
    """Raised when a cancel token fires or the user aborts a prompt."""


class BackendUnavailableError(JobError):
    """Raised when a required optional capability is absent."""

    def __init__(
        self,
        capability_id: str,
        reason: AbsenceReason | str,
        detail: str = "",
    ) -> None:
        self.capability_id = capability_id
        if isinstance(reason, AbsenceReason):
            self.reason = reason
        else:
            self.reason = AbsenceReason(reason)
        self.detail = detail
        message = f"Backend unavailable: {capability_id} ({self.reason.value})"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class OutputExistsError(JobError):
    """Raised when the destination path already exists and overwrite is off."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Output already exists: {path}")


class SourceOverwriteError(JobError):
    """Raised when the output path resolves to a job input (Save As rule)."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(
            f"Cannot write over a source file; choose a different path: {path}"
        )
