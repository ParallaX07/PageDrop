"""Job handlers for Phase 24 organize / layout tools (Qt-free)."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core import pdf_tools
from pagedrop.core.jobs.errors import JobError, OutputExistsError
from pagedrop.core.jobs.runner import JobContext, SerializedJobRunner

# ponytail: full-file read into RAM for embfile_add; 64 MiB is enough for
# typical embeds. Raise only with a measured large-attachment need (or stream
# if PyMuPDF gains a path-based embfile API).
MAX_ATTACHMENT_BYTES = 64 * 1024 * 1024

def handle_split_ranges(ctx: JobContext) -> Path:
    ranges = [tuple(r) for r in ctx.spec.options["ranges"]]
    base_name = str(ctx.spec.options.get("base_name", "range"))
    out_dir = Path(ctx.spec.options["output_dir"])
    ctx.progress(0.2, "Extracting ranges…")
    staged = pdf_tools.extract_ranges_to_folder(
        ctx.spec.inputs[0],
        ranges,  # type: ignore[arg-type]
        ctx.staging.job_dir,
        base_name=base_name,
        password=ctx.password(),
        cancel=ctx.cancel,
    )
    ctx.cancel.check()
    if not staged:
        raise ValueError("No ranges extracted")
    for extra in staged[1:]:
        dest = out_dir / extra.name
        if dest.exists() and not ctx.spec.overwrite:
            raise OutputExistsError(str(dest))
        ctx.staging.promote(extra, dest)
    # Runner promotes the first staged file to spec.output.
    return staged[0]

def handle_reverse(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Reversing pages…")
    pdf_tools.reverse_pdf_pages(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        add_blank_page=bool(ctx.spec.options.get("add_blank_page", False)),
        blank_size_from=str(ctx.spec.options.get("blank_size_from", "last")),
        password=ctx.password(),
        cancel=ctx.cancel,
    )
    return ctx.staged_output

def handle_alternate(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Alternating pages…")
    a, b = ctx.spec.inputs[0], ctx.spec.inputs[1]
    pdf_tools.alternate_pdfs(
        a,
        b,
        str(ctx.staged_output),
        start_with_a=bool(ctx.spec.options.get("start_with_a", True)),
        password_a=ctx.password(a),
        password_b=ctx.password(b),
        cancel=ctx.cancel,
    )
    return ctx.staged_output

def handle_n_up(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Building N-up…")
    pdf_tools.n_up_pdf(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        rows=int(ctx.spec.options["rows"]),
        cols=int(ctx.spec.options["cols"]),
        margin_pt=float(ctx.spec.options.get("margin_pt", 0.0)),
        password=ctx.password(),
        cancel=ctx.cancel,
    )
    return ctx.staged_output

def handle_booklet(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Building booklet…")
    pdf_tools.booklet_pdf(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        margin_pt=float(ctx.spec.options.get("margin_pt", 0.0)),
        password=ctx.password(),
        cancel=ctx.cancel,
    )
    return ctx.staged_output

def handle_posterize(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Posterizing…")
    pdf_tools.posterize_pdf(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        rows=int(ctx.spec.options["rows"]),
        cols=int(ctx.spec.options["cols"]),
        password=ctx.password(),
        cancel=ctx.cancel,
    )
    return ctx.staged_output

def handle_divide(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Dividing pages…")
    pdf_tools.divide_pdf_pages(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        direction=str(ctx.spec.options["direction"]),
        password=ctx.password(),
        cancel=ctx.cancel,
    )
    return ctx.staged_output

def handle_combine_long(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Combining pages…")
    pdf_tools.combine_pages_to_single_long(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        password=ctx.password(),
        cancel=ctx.cancel,
    )
    return ctx.staged_output

def handle_normalize(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Normalizing page size…")
    pdf_tools.normalize_pdf_page_size(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        float(ctx.spec.options["width_pt"]),
        float(ctx.spec.options["height_pt"]),
        strategy=str(ctx.spec.options.get("strategy", "fit")),
        margins_pt=float(ctx.spec.options.get("margins_pt", 0.0)),
        password=ctx.password(),
        cancel=ctx.cancel,
    )
    return ctx.staged_output

def handle_metadata_strip(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Stripping metadata…")
    pdf_tools.metadata_strip(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        strip_xmp_v1=bool(ctx.spec.options.get("strip_xmp", True)),
        password=ctx.password(),
    )
    return ctx.staged_output

def handle_metadata_set(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Updating metadata…")
    updates = dict(ctx.spec.options.get("updates") or {})
    pdf_tools.metadata_set(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        updates=updates,
        password=ctx.password(),
    )
    return ctx.staged_output

def handle_page_labels(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Setting page labels…")
    labels = list(ctx.spec.options.get("labels") or [])
    pdf_tools.page_labels_set(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        labels=labels,
        password=ctx.password(),
    )
    return ctx.staged_output

def handle_attachment_add(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Adding attachment…")
    file_path = Path(str(ctx.spec.options["file_path"]))
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise JobError(f"Cannot read attachment: {exc}") from exc
    if size > MAX_ATTACHMENT_BYTES:
        limit_mib = MAX_ATTACHMENT_BYTES // (1024 * 1024)
        raise JobError(
            f"Attachment is too large ({size / (1024 * 1024):.1f} MiB). "
            f"Maximum is {limit_mib} MiB."
        )
    data = file_path.read_bytes()
    pdf_tools.attachment_add(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        name=str(ctx.spec.options["name"]),
        data=data,
        overwrite=bool(ctx.spec.options.get("replace", False)),
        password=ctx.password(),
    )
    return ctx.staged_output

def handle_attachment_remove(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Removing attachment…")
    pdf_tools.attachment_remove(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        name=str(ctx.spec.options["name"]),
        password=ctx.password(),
    )
    return ctx.staged_output

def handle_attachment_extract(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Extracting attachments…")
    pdf_tools.attachment_extract_all_zip(
        ctx.spec.inputs[0],
        ctx.staged_output,
        password=ctx.password(),
    )
    return ctx.staged_output

def handle_zip(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Creating ZIP…")
    pdf_tools.zip_pdfs(ctx.spec.inputs, ctx.staged_output)
    return ctx.staged_output

def handle_compare(ctx: JobContext) -> Path:
    ctx.progress(0.2, "Comparing pages…")
    a, b = ctx.spec.inputs[0], ctx.spec.inputs[1]
    result = pdf_tools.compare_pdfs_heatmap(
        a,
        b,
        ctx.staged_output,
        dpi=int(ctx.spec.options.get("dpi", 120)),
        password_a=ctx.password(a),
        password_b=ctx.password(b),
        cancel=ctx.cancel,
    )
    # Stash ratio for UI status via options mutation is forbidden; write a
    # promoted sidecar note next to the exported heatmap PDF.
    ratio_dest = Path(ctx.spec.output).with_suffix(".compare_ratio.txt")
    ratio_staged = ctx.staging.stage_file(ratio_dest.name)
    ratio_staged.write_text(f"{result.overall_diff_ratio:.4f}", encoding="utf-8")
    ctx.staging.promote(ratio_staged, ratio_dest)
    return ctx.staged_output

ORGANIZE_HANDLERS: dict[str, object] = {
    "split": handle_split_ranges,
    "alternate": handle_alternate,
    "reverse": handle_reverse,
    "n_up": handle_n_up,
    "booklet": handle_booklet,
    "posterize": handle_posterize,
    "divide": handle_divide,
    "combine": handle_combine_long,
    "normalize": handle_normalize,
    "metadata_strip": handle_metadata_strip,
    "metadata_set": handle_metadata_set,
    "page_labels": handle_page_labels,
    "attachment_add": handle_attachment_add,
    "attachment_remove": handle_attachment_remove,
    "attachment_extract": handle_attachment_extract,
    "zip": handle_zip,
    "compare": handle_compare,
}

def register_organize_handlers(runner: SerializedJobRunner) -> None:
    for job_type, handler in ORGANIZE_HANDLERS.items():
        runner.register(job_type, handler)  # type: ignore[arg-type]
