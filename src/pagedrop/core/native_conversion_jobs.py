"""Job handlers for Phase 25 native import / export (Qt-free)."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core.jobs.runner import JobContext, SerializedJobRunner
from pagedrop.core.native_conversions import (
    MULTI_PAGE_EXPORT_IDS,
    collision_safe_path,
    export_pdf,
    import_to_pdf,
)

def handle_import_to_pdf(ctx: JobContext) -> Path:
    """Convert one or more native-import documents to PDF."""
    inputs = list(ctx.spec.inputs)
    if not inputs:
        raise ValueError("No files to convert")
    output_dir = ctx.spec.options.get("output_dir")
    n = len(inputs)

    if n == 1 and not output_dir:
        ctx.progress(0.3, f"Converting {Path(inputs[0]).name}…")
        import_to_pdf(inputs[0], ctx.staged_output, overwrite=True)
        return ctx.staged_output

    out_dir = Path(str(output_dir or Path(ctx.spec.output).parent))
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs: list[tuple[Path, Path]] = []
    for index, source in enumerate(inputs):
        ctx.cancel.check()
        ctx.progress(index / max(n, 1), f"Converting {Path(source).name}…")
        name = f"{Path(source).stem}.pdf"
        staged = ctx.staging.stage_file(f"{index:03d}_{name}")
        import_to_pdf(source, staged, overwrite=True)
        dest = out_dir / name
        if dest.exists() and not ctx.spec.overwrite:
            dest = collision_safe_path(dest)
        pairs.append((staged, dest))

    first_staged, _first_dest = pairs[0]
    for staged, dest in pairs[1:]:
        ctx.staging.promote(staged, dest)
    if first_staged != ctx.staged_output:
        first_staged.replace(ctx.staged_output)
    return ctx.staged_output

def handle_export_from_pdf(ctx: JobContext) -> Path:
    """Export a PDF to a registered format (single- or multi-file)."""
    source = ctx.spec.inputs[0]
    format_id = str(ctx.spec.options["format_id"])
    pages = ctx.spec.options.get("pages")
    dpi = float(ctx.spec.options.get("dpi", 144))
    jpeg_quality = int(ctx.spec.options.get("jpeg_quality", 90))
    password = ctx.password()
    ctx.progress(0.2, f"Exporting {format_id.upper()}…")

    if format_id in MULTI_PAGE_EXPORT_IDS:
        out_dir = Path(str(ctx.spec.options["output_dir"]))
        out_dir.mkdir(parents=True, exist_ok=True)
        base_name = str(
            ctx.spec.options.get("base_name", Path(source).stem)
        )
        template = ctx.staging.job_dir / f"{base_name}.bin"
        written = export_pdf(
            source,
            template,
            format_id=format_id,
            pages=pages,
            dpi=dpi,
            jpeg_quality=jpeg_quality,
            password=password,
            overwrite=True,
            cancel=ctx.cancel,
        )
        if not written:
            raise ValueError("Export produced no files")
        for index, staged in enumerate(written):
            dest = out_dir / staged.name
            if dest.exists() and not ctx.spec.overwrite:
                dest = collision_safe_path(dest)
            if index == 0:
                if staged != ctx.staged_output:
                    staged.replace(ctx.staged_output)
                # Runner promotes staged_output → spec.output (first dest).
                continue
            ctx.staging.promote(staged, dest)
        return ctx.staged_output

    export_pdf(
        source,
        ctx.staged_output,
        format_id=format_id,
        pages=pages,
        dpi=dpi,
        jpeg_quality=jpeg_quality,
        password=password,
        overwrite=True,
        cancel=ctx.cancel,
    )
    return ctx.staged_output

NATIVE_CONVERSION_HANDLERS: dict[str, object] = {
    "import_to_pdf": handle_import_to_pdf,
    "export_from_pdf": handle_export_from_pdf,
}

def register_native_conversion_handlers(runner: SerializedJobRunner) -> None:
    for job_type, handler in NATIVE_CONVERSION_HANDLERS.items():
        runner.register(job_type, handler)  # type: ignore[arg-type]
