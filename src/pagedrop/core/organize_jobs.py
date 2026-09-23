"""Job handlers for Phase 24 organize / layout tools (Qt-free)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from pagedrop.core import pdf_tools
from pagedrop.core import compare_report
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
    expected = None
    if (
        "source_fingerprint_a" in ctx.spec.options
        or "source_fingerprint_b" in ctx.spec.options
    ):
        expected = (
            _compare_report_fingerprint(
                ctx.spec.options.get("source_fingerprint_a"), "Original"
            ),
            _compare_report_fingerprint(
                ctx.spec.options.get("source_fingerprint_b"), "Revised"
            ),
        )
        _check_compare_report_sources((a, b), expected)
    result = pdf_tools.compare_pdfs_heatmap(
        a,
        b,
        ctx.staged_output,
        dpi=int(ctx.spec.options.get("dpi", 120)),
        password_a=ctx.password(a),
        password_b=ctx.password(b),
        cancel=ctx.cancel,
    )
    if expected is not None:
        _check_compare_report_sources((a, b), expected)
    # Stash ratio for UI status via options mutation is forbidden; write a
    # promoted sidecar note next to the exported heatmap PDF.
    ratio_dest = Path(ctx.spec.output).with_suffix(".compare_ratio.txt")
    ratio_staged = ctx.staging.stage_file(ratio_dest.name)
    ratio_staged.write_text(f"{result.overall_diff_ratio:.4f}", encoding="utf-8")
    ctx.staging.promote(ratio_staged, ratio_dest)
    return ctx.staged_output


_COMPARE_REPORT_OPTIONS = frozenset(
    {
        "layout",
        "include_summary",
        "include_revisions",
        "source_fingerprint_a",
        "source_fingerprint_b",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _compare_report_fingerprint(value: object, label: str) -> pdf_tools.SourceFingerprint:
    if not isinstance(value, Mapping) or set(value) != {
        "path",
        "size",
        "mtime_ns",
        "sha256",
    }:
        raise JobError(f"Malformed {label} source fingerprint")
    path = value["path"]
    size = value["size"]
    mtime_ns = value["mtime_ns"]
    sha256 = value["sha256"]
    if (
        not isinstance(path, str)
        or not path
        or type(size) is not int
        or size < 0
        or type(mtime_ns) is not int
        or mtime_ns < 0
        or not isinstance(sha256, str)
        or _SHA256_RE.fullmatch(sha256) is None
    ):
        raise JobError(f"Malformed {label} source fingerprint")
    return pdf_tools.SourceFingerprint(
        path=path,
        size=size,
        mtime_ns=mtime_ns,
        sha256=sha256,
    )


def _compare_report_options(ctx: JobContext) -> tuple[
    compare_report.CompareLayout,
    bool,
    bool,
    pdf_tools.SourceFingerprint,
    pdf_tools.SourceFingerprint,
]:
    if len(ctx.spec.inputs) != 2:
        raise JobError("Comparison report requires Original and Revised PDFs")
    options = dict(ctx.spec.options)
    if set(options) != _COMPARE_REPORT_OPTIONS:
        raise JobError(
            "Comparison report options must contain only layout, section flags, "
            "and source fingerprints"
        )
    layout = options["layout"]
    include_summary = options["include_summary"]
    include_revisions = options["include_revisions"]
    if not isinstance(layout, str) or layout not in {"split", "alternating"}:
        raise JobError("Comparison report layout must be split or alternating")
    if type(include_summary) is not bool or type(include_revisions) is not bool:
        raise JobError("Comparison report section flags must be boolean")
    return (
        layout,
        include_summary,
        include_revisions,
        _compare_report_fingerprint(options["source_fingerprint_a"], "Original"),
        _compare_report_fingerprint(options["source_fingerprint_b"], "Revised"),
    )


def _check_compare_report_sources(
    paths: tuple[str, str],
    expected: tuple[pdf_tools.SourceFingerprint, pdf_tools.SourceFingerprint],
) -> None:
    for path, fingerprint in zip(paths, expected, strict=True):
        current = pdf_tools.source_fingerprint(path)
        if current != fingerprint:
            raise pdf_tools.CompareSourceChangedError(
                f"Comparison source changed; compare again: {path}"
            )


def _validate_staged_compare_report(
    path: Path,
    *,
    layout: compare_report.CompareLayout,
    include_summary: bool,
    include_revisions: bool,
    comparison_positions: int,
) -> None:
    try:
        document = pdf_tools.open_pdf(str(path))
    except Exception as exc:
        if isinstance(exc, JobError):
            raise
        raise JobError(f"Comparison report validation failed: {exc}") from exc
    try:
        top_level = [
            title for level, title, _page in document.get_toc() if level == 1
        ]
        comparison_bookmarks = comparison_positions * (1 if layout == "split" else 2)
        if (
            len(document) < comparison_bookmarks
            or len(top_level) < comparison_bookmarks
        ):
            raise JobError(
                "Comparison report validation failed: missing comparison pages"
            )
        if layout == "split":
            expected_first = "Original 1 / Revised 1"
        else:
            expected_first = "Original 1"
        if top_level[0] != expected_first:
            raise JobError(
                "Comparison report validation failed: missing comparison bookmark"
            )
        required_sections = []
        if include_summary:
            required_sections.append("Summary")
        if include_revisions:
            required_sections.append("Revisions")
        missing = [title for title in required_sections if title not in top_level]
        if missing:
            raise JobError(
                "Comparison report validation failed: missing "
                + ", ".join(missing)
                + " bookmark"
            )
    finally:
        document.close()


def handle_compare_report(ctx: JobContext) -> Path:
    """Compose one staged comparison report and validate it before promotion."""
    layout, include_summary, include_revisions, fingerprint_a, fingerprint_b = (
        _compare_report_options(ctx)
    )
    paths = (ctx.spec.inputs[0], ctx.spec.inputs[1])
    expected = (fingerprint_a, fingerprint_b)
    ctx.progress(0.05, "Validating comparison sources…")
    _check_compare_report_sources(paths, expected)
    ctx.cancel.check()

    ctx.progress(0.10, "Comparing pages…")
    original = revised = None
    try:
        original = pdf_tools.open_pdf(paths[0], password=ctx.password(paths[0]))
        try:
            revised = pdf_tools.open_pdf(paths[1], password=ctx.password(paths[1]))
        except Exception:
            original.close()
            original = None
            raise
        report = pdf_tools._compare_documents(  # type: ignore[attr-defined]
            original,
            revised,
            cancel=ctx.cancel,
            source_fingerprint_a=fingerprint_a,
            source_fingerprint_b=fingerprint_b,
        )
        _check_compare_report_sources(paths, expected)
        ctx.progress(0.30, "Comparison complete…")

        def report_progress(fraction: float, message: str) -> None:
            if message == "Appended Summary":
                ctx.progress(0.76, "Appending Summary…")
            elif message == "Appended Revisions":
                ctx.progress(0.81, "Appending Revisions…")
            elif message == "Comparison report composed":
                ctx.progress(0.85, "Report composed…")
            else:
                ctx.progress(0.30 + min(1.0, fraction) * 0.50, "Composing report…")

        compare_report.write_compare_report(
            original,
            revised,
            report,
            Path(paths[0]).name,
            Path(paths[1]).name,
            ctx.staged_output,
            layout=layout,
            include_summary=include_summary,
            include_revisions=include_revisions,
            cancel=ctx.cancel,
            progress=report_progress,
        )
        _check_compare_report_sources(paths, expected)
    finally:
        if revised is not None:
            revised.close()
        if original is not None:
            original.close()

    ctx.cancel.check()
    ctx.progress(0.90, "Validating report…")
    _validate_staged_compare_report(
        ctx.staged_output,
        layout=layout,
        include_summary=include_summary,
        include_revisions=include_revisions,
        comparison_positions=max(report.page_count_a, report.page_count_b),
    )
    ctx.cancel.check()
    ctx.progress(0.93, "Report validated…")
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
    "compare_report": handle_compare_report,
}

def register_organize_handlers(runner: SerializedJobRunner) -> None:
    for job_type, handler in ORGANIZE_HANDLERS.items():
        runner.register(job_type, handler)  # type: ignore[arg-type]
