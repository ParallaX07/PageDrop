"""Path-only handlers for editor Save As work."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core.jobs.runner import JobContext, SerializedJobRunner
from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import PdfLoadError, open_pdf
from pagedrop.core.pdf_writer import write_pdf
from pagedrop.core.redact import redact_edit_model


def handle_editor_save(ctx: JobContext) -> Path:
    """Write one immutable editor snapshot to the runner's staged output."""
    model = ctx.spec.options["model"]
    if not isinstance(model, PdfEditModel):
        raise ValueError("Editor save needs a PDF edit-model snapshot")
    markup = ctx.spec.options.get("markup")
    regions = ctx.spec.options.get("regions")
    ctx.progress(0.2, "Saving PDF…")
    if regions:
        redact_edit_model(
            model,
            ctx.staged_output,
            regions,
            markup=markup,
            passwords=ctx.credentials.snapshot(),
            scope=ctx.spec.options.get("scope"),
            verify=True,
        )
    else:
        write_pdf(
            model, str(ctx.staged_output), markup=markup, passwords=ctx.credentials.snapshot()
        )
        with open_pdf(str(ctx.staged_output)) as output:
            if output.page_count != model.logical_count():
                raise PdfLoadError("Saved PDF has an unexpected page count")
    ctx.cancel.check()
    return ctx.staged_output


def register_editor_handlers(runner: SerializedJobRunner) -> None:
    # The writer/redactor already acquire FITZ_LOCK around their actual MuPDF work.
    # Keeping verification outside that lock preserves the I4 thread policy.
    runner.register("editor_save", handle_editor_save, holds_fitz=False)
