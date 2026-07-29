"""Job handlers for document modification tools (Phase 28)."""

from __future__ import annotations

from pathlib import Path

from pagedrop.core import modify_ops as ops
from pagedrop.core.jobs.errors import OutputExistsError
from pagedrop.core.jobs.runner import JobContext, SerializedJobRunner


def _password(ctx: JobContext, path: str | None = None) -> str | None:
    return ctx.credentials.get(path or ctx.spec.inputs[0])


def handle_crop(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Cropping PDF…")
    ops.crop_pdf(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        left=float(ctx.spec.options.get("left", 0)),
        right=float(ctx.spec.options.get("right", 0)),
        top=float(ctx.spec.options.get("top", 0)),
        bottom=float(ctx.spec.options.get("bottom", 0)),
        mode=str(ctx.spec.options.get("mode", "cropbox")),  # type: ignore[arg-type]
        password=_password(ctx),
        cancel=ctx.cancel,
    )
    return ctx.staged_output


def handle_watermark(ctx: JobContext) -> Path:
    kind = str(ctx.spec.options.get("kind", "text"))
    ctx.progress(0.3, "Applying watermark…")
    pages = ctx.spec.options.get("pages")
    page_list = [int(p) for p in pages] if pages is not None else None
    diag = ctx.spec.options.get("diagonal_percent")
    diagonal_percent = float(diag) if diag is not None else None
    cx = ctx.spec.options.get("center_x")
    cy = ctx.spec.options.get("center_y")
    common = {
        "opacity": float(ctx.spec.options.get("opacity", 0.35)),
        "rotate": float(ctx.spec.options.get("rotate", 45)),
        "position": str(ctx.spec.options.get("position", "center")),
        "center_x": float(cx) if cx is not None else None,
        "center_y": float(cy) if cy is not None else None,
        "diagonal_percent": diagonal_percent,
        "pages": page_list,
        "flatten": bool(ctx.spec.options.get("flatten", False)),
        "password": _password(ctx),
        "cancel": ctx.cancel,
    }
    if kind == "image":
        ops.add_image_watermark(
            ctx.spec.inputs[0],
            str(ctx.staged_output),
            image_path=str(ctx.spec.options["image_path"]),
            scale=float(ctx.spec.options["scale"])
            if ctx.spec.options.get("scale") is not None
            else None,
            **common,  # type: ignore[arg-type]
        )
    else:
        color = ctx.spec.options.get("color") or (0.55, 0.55, 0.55)
        fontsize = ctx.spec.options.get("fontsize")
        ops.add_text_watermark(
            ctx.spec.inputs[0],
            str(ctx.staged_output),
            text=str(ctx.spec.options.get("text", "")),
            fontsize=float(fontsize) if fontsize is not None else None,
            color=(float(color[0]), float(color[1]), float(color[2])),
            **common,  # type: ignore[arg-type]
        )
    return ctx.staged_output


def handle_header_footer(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Adding header and footer…")
    ops.add_header_footer(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        header=str(ctx.spec.options.get("header", "")),
        footer=str(ctx.spec.options.get("footer", "")),
        fontsize=float(ctx.spec.options.get("fontsize", 10)),
        password=_password(ctx),
        cancel=ctx.cancel,
    )
    return ctx.staged_output


def handle_page_numbers(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Adding page numbers…")
    ops.add_page_numbers(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        template=str(ctx.spec.options.get("template", "{page}")),
        position=str(ctx.spec.options.get("position", "bottom-center")),  # type: ignore[arg-type]
        start=int(ctx.spec.options.get("start", 1)),
        fontsize=float(ctx.spec.options.get("fontsize", 10)),
        password=_password(ctx),
        cancel=ctx.cancel,
    )
    return ctx.staged_output


def handle_bates(ctx: JobContext) -> Path:
    sources = list(ctx.spec.inputs)
    opts = ctx.spec.options
    prefix = str(opts.get("prefix", ""))
    start = int(opts.get("start", 1))
    digits = int(opts.get("digits", 6))
    position = str(opts.get("position", "bottom-right"))
    fontsize = float(opts.get("fontsize", 9))

    if len(sources) == 1:
        ctx.progress(0.3, "Applying Bates numbers…")
        ops.add_bates_numbers(
            sources[0],
            str(ctx.staged_output),
            prefix=prefix,
            start=start,
            digits=digits,
            position=position,  # type: ignore[arg-type]
            fontsize=fontsize,
            password=_password(ctx),
            cancel=ctx.cancel,
        )
        return ctx.staged_output

    out_dir = Path(str(opts["output_dir"]))
    ctx.progress(0.2, "Applying Bates numbers across files…")
    passwords = {p: pw for p in sources if (pw := _password(ctx, p))}
    written = ops.add_bates_across_files(
        sources,
        ctx.staging.job_dir,
        prefix=prefix,
        start=start,
        digits=digits,
        position=position,  # type: ignore[arg-type]
        fontsize=fontsize,
        passwords=passwords,
        cancel=ctx.cancel,
    )
    ctx.cancel.check()
    if not written:
        raise ValueError("No Bates outputs produced")
    for extra in written[1:]:
        dest = out_dir / extra.name
        if dest.exists() and not ctx.spec.overwrite:
            raise OutputExistsError(str(dest))
        ctx.staging.promote(extra, dest)
    # Rename first staged file to match user-facing first output name.
    first_dest_name = written[0].name
    renamed = ctx.staging.job_dir / first_dest_name
    if written[0] != renamed:
        written[0].replace(renamed)
        return renamed
    return written[0]


def handle_bookmarks(ctx: JobContext) -> Path:
    action = str(ctx.spec.options.get("action", "set"))
    ctx.progress(0.3, "Updating bookmarks…")
    if action == "toc_page":
        ops.generate_toc_page(
            ctx.spec.inputs[0],
            str(ctx.staged_output),
            title=str(ctx.spec.options.get("title", "Table of contents")),
            password=_password(ctx),
        )
    elif action == "clear":
        ops.set_bookmarks(
            ctx.spec.inputs[0],
            str(ctx.staged_output),
            [],
            password=_password(ctx),
        )
    elif action == "set":
        raw = ctx.spec.options.get("bookmarks") or []
        entries = [
            ops.BookmarkEntry(int(row[0]), str(row[1]), int(row[2])) for row in raw
        ]
        ops.set_bookmarks(
            ctx.spec.inputs[0],
            str(ctx.staged_output),
            entries,
            password=_password(ctx),
        )
    elif action == "pages":
        ops.bookmarks_one_per_page(
            ctx.spec.inputs[0],
            str(ctx.staged_output),
            password=_password(ctx),
        )
    else:
        raise ValueError(f"Unknown bookmarks action: {action!r}")
    return ctx.staged_output


def handle_annotations(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Processing annotations…")
    ops.remove_or_flatten_annotations(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        action=str(ctx.spec.options.get("action", "remove")),  # type: ignore[arg-type]
        include_widgets=bool(ctx.spec.options.get("include_widgets", True)),
        password=_password(ctx),
        cancel=ctx.cancel,
    )
    return ctx.staged_output


def handle_blank_pages(ctx: JobContext) -> Path:
    ctx.progress(0.3, "Removing blank pages…")
    ops.remove_blank_pages(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        ink_threshold=float(ctx.spec.options.get("ink_threshold", 0.01)),
        password=_password(ctx),
        cancel=ctx.cancel,
    )
    return ctx.staged_output


def handle_color_effects(ctx: JobContext) -> Path:
    effect = str(ctx.spec.options.get("effect", "greyscale"))
    ctx.progress(0.3, "Applying color effect…")
    bg = ctx.spec.options.get("background_rgb") or (0.95, 0.95, 0.9)
    ops.apply_color_effect(
        ctx.spec.inputs[0],
        str(ctx.staged_output),
        effect=effect,  # type: ignore[arg-type]
        background_rgb=(float(bg[0]), float(bg[1]), float(bg[2])),
        dpi=int(ctx.spec.options.get("dpi", 150)),
        password=_password(ctx),
        cancel=ctx.cancel,
    )
    return ctx.staged_output


MODIFY_HANDLERS: dict[str, object] = {
    "crop": handle_crop,
    "watermark": handle_watermark,
    "header_footer": handle_header_footer,
    "page_numbers": handle_page_numbers,
    "bates": handle_bates,
    "bookmarks": handle_bookmarks,
    "annotations": handle_annotations,
    "blank_pages": handle_blank_pages,
    "color_effects": handle_color_effects,
}


def register_modify_handlers(runner: SerializedJobRunner) -> None:
    for job_type, handler in MODIFY_HANDLERS.items():
        runner.register(job_type, handler)  # type: ignore[arg-type]
