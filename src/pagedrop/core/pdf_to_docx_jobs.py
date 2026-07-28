"""Job handler for PDF → Word (DOCX) via LibreOffice (Phase 32)."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core.jobs.runner import JobContext, SerializedJobRunner
from pagedrop.core.pdf_to_docx import convert_pdf_to_docx


def handle_pdf_to_docx(ctx: JobContext) -> Path:
    """Convert one PDF to a staged DOCX (validated before return)."""
    source = ctx.spec.inputs[0]
    soffice = ctx.spec.options.get("soffice_path")
    soffice_path = str(soffice) if soffice else None

    def on_progress(message: str) -> None:
        ctx.progress(0.4, message)

    convert_pdf_to_docx(
        source,
        ctx.staged_output,
        soffice_path=soffice_path,
        cancel=ctx.cancel,
        on_progress=on_progress,
    )
    ctx.progress(0.9, "Validated DOCX…")
    return ctx.staged_output


def register_pdf_to_docx_handlers(runner: SerializedJobRunner) -> None:
    runner.register("pdf_to_docx", handle_pdf_to_docx)
