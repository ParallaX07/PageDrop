"""Job handler for Office → PDF (Phase 26)."""

from __future__ import annotations

from pagedrop.core.backends.office import (
    BACKEND_AUTO,
    OfficeBackend,
    convert_office_to_pdf,
)
from pagedrop.core.jobs.runner import JobContext, SerializedJobRunner


def handle_office_to_pdf(ctx: JobContext) -> Path:
    """Convert one Office document to a staged PDF (validated before return)."""
    source = ctx.spec.inputs[0]
    raw_backend = str(ctx.spec.options.get("backend") or BACKEND_AUTO)
    backend: OfficeBackend
    if raw_backend in ("auto", "com", "libreoffice"):
        backend = raw_backend  # type: ignore[assignment]
    else:
        backend = BACKEND_AUTO
    soffice = ctx.spec.options.get("soffice_path")
    soffice_path = str(soffice) if soffice else None

    def on_progress(message: str) -> None:
        ctx.progress(0.4, message)

    result = convert_office_to_pdf(
        source,
        ctx.staged_output,
        backend=backend,
        soffice_path=soffice_path,
        cancel=ctx.cancel,
        on_progress=on_progress,
    )
    ctx.progress(0.9, f"Validated PDF via {result.backend_label}…")
    return ctx.staged_output


def register_office_conversion_handlers(runner: SerializedJobRunner) -> None:
    runner.register("office_to_pdf", handle_office_to_pdf)
