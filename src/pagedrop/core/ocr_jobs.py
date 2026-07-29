"""Job handlers for OCR and table extract (Phase 29)."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core import native_conversions as nc
from pagedrop.core import ocr as ocr_ops
from pagedrop.core.jobs.runner import JobContext, SerializedJobRunner

def _pages(ctx: JobContext) -> list[int] | None:
    pages = ctx.spec.options.get("pages")
    if pages is None:
        return None
    return [int(p) for p in pages]

def handle_ocr_pdf(ctx: JobContext) -> Path:
    opts = ctx.spec.options
    language = str(opts.get("language", "eng"))
    dpi = int(opts.get("dpi", 300))
    tessdata = opts.get("tessdata")
    tessdata_path = str(tessdata) if tessdata else None

    def progress(frac: float, message: str) -> None:
        ctx.progress(frac, message)
        ctx.cancel.check()

    ocr_ops.ocr_pdf(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        language=language,
        pages=_pages(ctx),
        dpi=dpi,
        password=ctx.password(),
        tessdata=tessdata_path,
        progress=progress,
        cancel=ctx.cancel,
    )
    return ctx.staged_output

def handle_extract_tables(ctx: JobContext) -> Path:
    format_id = str(ctx.spec.options.get("format_id", "csv"))
    ctx.progress(0.3, "Extracting tables…")
    ctx.cancel.check()
    written = nc.export_pdf(
        ctx.spec.inputs[0],
        ctx.staged_output,
        format_id=format_id,
        pages=_pages(ctx),
        password=ctx.password(),
        overwrite=True,
    )
    ctx.cancel.check()
    # Single-file formats write exactly one path.
    return Path(written[0])

OCR_HANDLERS: dict[str, object] = {
    "ocr_pdf": handle_ocr_pdf,
    "extract_tables": handle_extract_tables,
}

def register_ocr_handlers(runner: SerializedJobRunner) -> None:
    # ponytail: ocr_pdf keeps holds_fitz=True (default) — whole-job FITZ_LOCK
    # stalls thumbs/viewer for long OCR runs. Upgrade: O10 process service
    # (parked; do not drop the lock without that boundary).
    for job_type, handler in OCR_HANDLERS.items():
        runner.register(job_type, handler)  # type: ignore[arg-type]
