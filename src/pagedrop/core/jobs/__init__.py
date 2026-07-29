"""Shared Tools / batch job infrastructure.

Stage under ``TempManager``, promote on success, cleanup on cancel/fail.
Credentials are runtime-only; ``JobSpec`` is persistable without secrets.
"""

from __future__ import annotations

from pagedrop.core.jobs.cancel import CancelToken, check_cancel
from pagedrop.core.jobs.credentials import RuntimeCredentials
from pagedrop.core.jobs.errors import (
    BackendUnavailableError,
    JobCancelledError,
    JobError,
    OutputExistsError,
    SourceOverwriteError,
)
from pagedrop.core.jobs.paths import (
    ensure_output_destination,
    paths_refer_to_same_file,
    reject_source_overwrite,
)
from pagedrop.core.jobs.preflight import PasswordPrompt, preflight_pdf_inputs
from pagedrop.core.jobs.runner import JobContext, JobHandler, SerializedJobRunner
from pagedrop.core.jobs.spec import JobSpec, ProgressCallback
from pagedrop.core.jobs.staging import JobStaging

__all__ = [
    "BackendUnavailableError",
    "CancelToken",
    "JobCancelledError",
    "JobContext",
    "JobError",
    "JobHandler",
    "JobSpec",
    "JobStaging",
    "OutputExistsError",
    "PasswordPrompt",
    "ProgressCallback",
    "RuntimeCredentials",
    "SerializedJobRunner",
    "SourceOverwriteError",
    "check_cancel",
    "ensure_output_destination",
    "paths_refer_to_same_file",
    "preflight_pdf_inputs",
    "reject_source_overwrite",
]
