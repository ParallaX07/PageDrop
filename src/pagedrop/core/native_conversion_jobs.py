"""Job handlers for Phase 25 native import / export (Qt-free)."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core.jobs.runner import JobContext, SerializedJobRunner
from pagedrop.core.native_conversions import (
    MULTI_PAGE_EXPORT_IDS,
    batch_output_paths,
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
    dests = batch_output_paths(inputs, out_dir, avoid_existing=not ctx.spec.overwrite)
    pairs: list[tuple[Path, Path]] = []
    for index, (source, dest) in enumerate(zip(inputs, dests, strict=True)):
        ctx.cancel.check()
        ctx.progress(index / max(n, 1), f"Converting {Path(source).name}…")
        staged = ctx.staging.stage_file(f"{index:03d}_{dest.name}")
        import_to_pdf(source, staged, overwrite=True)
        pairs.append((staged, dest))

    first_staged, _first_dest = pairs[0]
    ctx.extra_outputs.extend(pairs[1:])
    return first_staged

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
        for staged in written[1:]:
            dest = out_dir / staged.name
            if dest.exists() and not ctx.spec.overwrite:
                dest = collision_safe_path(dest)
            ctx.extra_outputs.append((staged, dest))
        # Runner promotes the first staged file to spec.output, then the extras.
        return written[0]

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
