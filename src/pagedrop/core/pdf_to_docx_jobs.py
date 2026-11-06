"""Job handler for PDF → Word (DOCX) via LibreOffice (Phase 32)."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core.jobs.runner import JobContext, SerializedJobRunner
from pagedrop.core.optimize_secure import decrypt_pdf
from pagedrop.core.pdf_to_docx import convert_pdf_to_docx
from pagedrop.core.thread_policy import FITZ_LOCK


def handle_pdf_to_docx(ctx: JobContext) -> Path:
    """Convert one PDF to a staged DOCX (validated before return)."""
    source = ctx.spec.inputs[0]
    soffice = ctx.spec.options.get("soffice_path")
    soffice_path = str(soffice) if soffice else None

    def on_progress(message: str) -> None:
        ctx.progress(0.4, message)

    password = ctx.password()
    # LibreOffice cannot open an encrypted PDF, so convert a decrypted copy.
    # The runner only rmdirs the job dir on success, so the plaintext copy is
    # removed here on every path.
    decrypted: Path | None = None
    try:
        convert_source = source
        if password:
            decrypted = ctx.staging.stage_file("decrypted_input.pdf")
            ctx.cancel.check()
            with FITZ_LOCK:
                decrypt_pdf(str(source), str(decrypted), password=password)
            ctx.cancel.check()
            convert_source = decrypted
        convert_pdf_to_docx(
            convert_source,
            ctx.staged_output,
            soffice_path=soffice_path,
            cancel=ctx.cancel,
            on_progress=on_progress,
        )
    finally:
        if decrypted is not None:
            decrypted.unlink(missing_ok=True)
    ctx.progress(0.9, "Validated DOCX…")
    return ctx.staged_output


def register_pdf_to_docx_handlers(runner: SerializedJobRunner) -> None:
    # The runner must not hold FITZ_LOCK across the LibreOffice wait; the
    # decrypt step takes the lock itself.
    runner.register("pdf_to_docx", handle_pdf_to_docx, holds_fitz=False)
