"""Vector PDF reports for page-number-matched text comparisons."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Literal

import fitz

from pagedrop.core.jobs.cancel import CancelToken, check_cancel
from pagedrop.core.pdf_tools import CompareChange, CompareReport
from pagedrop.core.jobs.paths import reject_source_overwrite


CompareLayout = Literal["split", "alternating"]
ProgressCallback = Callable[[float, str], None]

_HEADER_PT = 64.0
_FOOTER_PT = 42.0
_GUTTER_PT = 24.0
_MARGIN_PT = 12.0
_TEXT_PT = 8.0
_SMALL_TEXT_PT = 6.5
_OVERLAY_OPACITY = 0.28
_RED = (0.88, 0.16, 0.16)
_GREEN = (0.16, 0.62, 0.28)
_APPENDIX_MEDIABOX = fitz.Rect(0, 0, 612, 792)
_APPENDIX_WHERE = fitz.Rect(48, 48, 564, 744)


def transform_rect(
    source_rect: tuple[float, float, float, float] | fitz.Rect,
    source_page_rect: fitz.Rect,
    destination_rect: fitz.Rect,
) -> fitz.Rect:
    """Map a rectangle between displayed page rectangles."""
    rect = fitz.Rect(source_rect)
    sx = destination_rect.width / source_page_rect.width
    sy = destination_rect.height / source_page_rect.height
    return fitz.Rect(
        destination_rect.x0 + (rect.x0 - source_page_rect.x0) * sx,
        destination_rect.y0 + (rect.y0 - source_page_rect.y0) * sy,
        destination_rect.x0 + (rect.x1 - source_page_rect.x0) * sx,
        destination_rect.y0 + (rect.y1 - source_page_rect.y0) * sy,
    )


def write_compare_report(
    original: fitz.Document,
    revised: fitz.Document,
    report: CompareReport,
    original_filename: str | Path,
    revised_filename: str | Path,
    output_path: str | Path,
    *,
    layout: CompareLayout = "split",
    include_summary: bool = False,
    include_revisions: bool = False,
    cancel: CancelToken | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    """Write comparison pages from two already-open documents.

    The caller owns *original* and *revised*.
    """
    if layout not in {"split", "alternating"}:
        raise ValueError("layout must be 'split' or 'alternating'")
    if not isinstance(include_summary, bool) or not isinstance(include_revisions, bool):
        raise TypeError("include_summary and include_revisions must be bool")

    output = Path(output_path)
    source_paths = [
        fingerprint.path
        for fingerprint in (
            report.source_fingerprint_a,
            report.source_fingerprint_b,
        )
        if fingerprint is not None
    ]
    source_paths.extend(
        str(name)
        for name in (getattr(original, "name", ""), getattr(revised, "name", ""))
        if name
    )
    reject_source_overwrite(output, *source_paths)

    positions = max(report.page_count_a, report.page_count_b)
    if positions == 0:
        raise ValueError("Cannot write a comparison report for two empty PDFs")

    _emit(progress, 0.0, "Composing comparison pages…")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, staged_name = tempfile.mkstemp(
        dir=str(output.parent), prefix=f".{output.name}.", suffix=".stage"
    )
    os.close(fd)
    staged = Path(staged_name)
    document: fitz.Document | None = fitz.open()
    bookmarks: list[list[object]] = []
    try:
        for position in range(positions):
            check_cancel(cancel)
            changes = _changes_for_position(report.changes, position)
            if layout == "split":
                _write_split_page(
                    document,
                    original,
                    revised,
                    report,
                    position,
                    changes,
                    str(original_filename),
                    str(revised_filename),
                    cancel=cancel,
                )
                bookmarks.append(
                    [
                        1,
                        _position_title(report, position),
                        document.page_count,
                    ]
                )
            else:
                for side in ("original", "revised"):
                    check_cancel(cancel)
                    _write_alternating_page(
                        document,
                        original,
                        revised,
                        report,
                        position,
                        side,
                        changes,
                        str(original_filename),
                        str(revised_filename),
                        cancel=cancel,
                    )
                    bookmarks.append(
                        [
                            1,
                            _side_title(report, position, side),
                            document.page_count,
                        ]
                    )
            _emit(
                progress,
                (position + 1) / positions,
                f"Composed comparison position {position + 1} of {positions}…",
            )

        assert document is not None
        if include_summary:
            check_cancel(cancel)
            summary_page = document.page_count + 1
            _append_story(
                document,
                _summary_html(
                    report,
                    str(original_filename),
                    str(revised_filename),
                ),
                output.parent,
                cancel=cancel,
            )
            bookmarks.append([1, "Summary", summary_page])
            _emit(progress, 0.95, "Appended Summary")
        if include_revisions:
            check_cancel(cancel)
            revisions_page = document.page_count + 1
            _append_revisions(
                document,
                report,
                output.parent,
                cancel=cancel,
            )
            bookmarks.append([1, "Revisions", revisions_page])
            _emit(progress, 0.98, "Appended Revisions")
        document.set_toc(bookmarks)
        check_cancel(cancel)
        document.save(str(staged))
        document.close()
        document = None
        check_cancel(cancel)
        os.replace(staged, output)
        _emit(progress, 1.0, "Comparison report composed")
        return output
    finally:
        if document is not None:
            document.close()
        staged.unlink(missing_ok=True)


def _append_revisions(
    document: fitz.Document,
    report: CompareReport,
    temporary_directory: Path,
    *,
    cancel: CancelToken | None,
) -> None:
    if not report.changes:
        _append_story(
            document,
            _section_html(
                "Revisions",
                '<p class="empty">No text changes detected</p>',
            ),
            temporary_directory,
            cancel=cancel,
        )
        return

    for number, change in enumerate(report.changes, start=1):
        check_cancel(cancel)
        _append_story(
            document,
            _revision_html(change, number, include_section_title=number == 1),
            temporary_directory,
            cancel=cancel,
            continuation_label=f"Revision {number}",
        )


def _append_story(
    document: fitz.Document,
    html_document: str,
    temporary_directory: Path,
    *,
    cancel: CancelToken | None,
    continuation_label: str | None = None,
) -> int:
    fd, staged_name = tempfile.mkstemp(
        dir=str(temporary_directory), prefix=".compare-appendix-", suffix=".pdf"
    )
    os.close(fd)
    staged = Path(staged_name)
    try:
        _write_story(staged, html_document, cancel=cancel)
        check_cancel(cancel)
        appendix = fitz.open(str(staged))
        try:
            if continuation_label is not None:
                for page_number in range(1, appendix.page_count):
                    check_cancel(cancel)
                    appendix[page_number].insert_text(
                        (48, 30),
                        f"{continuation_label} (continued)",
                        fontsize=9,
                        color=(0.25, 0.25, 0.25),
                    )
            page_count = appendix.page_count
            document.insert_pdf(appendix)
            return page_count
        finally:
            appendix.close()
    finally:
        staged.unlink(missing_ok=True)


def _write_story(
    output: Path,
    html_document: str,
    *,
    cancel: CancelToken | None,
) -> None:
    story = fitz.Story(html=html_document)
    writer = fitz.DocumentWriter(str(output))
    try:
        more = True
        while more:
            check_cancel(cancel)
            device = writer.begin_page(_APPENDIX_MEDIABOX)
            more, _ = story.place(_APPENDIX_WHERE)
            story.draw(device)
            writer.end_page()
    finally:
        writer.close()


def _summary_html(
    report: CompareReport,
    original_filename: str,
    revised_filename: str,
) -> str:
    compared_pairs = max(report.page_count_a, report.page_count_b)
    empty_state = (
        '<p class="empty">No text changes detected</p>' if not report.changes else ""
    )
    return _section_html(
        "Summary",
        f"""
        <p><b>Original filename:</b> {escape(original_filename)}</p>
        <p><b>Revised filename:</b> {escape(revised_filename)}</p>
        <p><b>Original page count:</b> {report.page_count_a}</p>
        <p><b>Revised page count:</b> {report.page_count_b}</p>
        <p><b>Generation time:</b> {escape(datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z'))}</p>
        <p><b>Compared page-pair count:</b> {compared_pairs}</p>
        <p><b>Changed page-pair count:</b> {report.changed_page_pair_count}</p>
        <p><b>Removed groups:</b> {report.deleted_count}</p>
        <p><b>Added groups:</b> {report.added_count}</p>
        <p><b>Replaced groups:</b> {report.modified_count}</p>
        <p class="limitation">Text comparison, matched by page number. Image, formatting, and moved-content differences are not classified.</p>
        {empty_state}
        """,
    )


def _revision_html(
    change: CompareChange,
    number: int,
    *,
    include_section_title: bool,
) -> str:
    kind = {
        "deleted": "Removed",
        "added": "Added",
        "modified": "Replaced",
    }[change.kind]
    title = f"<h1>Revisions</h1>" if include_section_title else ""
    return _section_html(
        "",
        f"""
        {title}
        <h2>Revision {number}: {kind}</h2>
        <p><b>Original page:</b> {_page_reference(change.page_a)}</p>
        <p><b>Revised page:</b> {_page_reference(change.page_b)}</p>
        <h3>Before</h3>
        <div class="value">{_revision_value(change.before_text)}</div>
        <h3>After</h3>
        <div class="value">{_revision_value(change.after_text)}</div>
        """,
    )


def _section_html(title: str, body: str) -> str:
    heading = f"<h1>{escape(title)}</h1>" if title else ""
    return f"""
    <html><head><style>
    body {{ font-family: sans-serif; font-size: 10pt; color: #202020; }}
    h1 {{ font-size: 20pt; margin-bottom: 18pt; }}
    h2 {{ font-size: 14pt; margin-top: 8pt; margin-bottom: 12pt; }}
    h3 {{ font-size: 11pt; margin-top: 14pt; margin-bottom: 4pt; }}
    p {{ margin: 4pt 0; }}
    .value {{ border: 0.5pt solid #b8b8b8; padding: 8pt; margin-bottom: 8pt; }}
    .limitation {{ margin-top: 18pt; color: #505050; }}
    .empty {{ margin-top: 18pt; font-size: 12pt; }}
    </style></head><body>{heading}{body}</body></html>
    """


def _page_reference(page: int | None) -> str:
    return f"Page {page + 1}" if page is not None else "No corresponding page"


def _revision_value(value: str | None) -> str:
    if value is None or value == "":
        return "—"
    return escape(value).replace("\n", "<br/>")


def _emit(
    progress: ProgressCallback | None, fraction: float, message: str
) -> None:
    if progress is not None:
        progress(max(0.0, min(1.0, fraction)), message)


def _changes_for_position(
    changes: Sequence[CompareChange], position: int
) -> tuple[CompareChange, ...]:
    return tuple(
        change
        for change in changes
        if change.page_a == position or change.page_b == position
    )


def _position_title(report: CompareReport, position: int) -> str:
    original = f"Original {position + 1}" if position < report.page_count_a else "No Original page"
    revised = f"Revised {position + 1}" if position < report.page_count_b else "No Revised page"
    return f"{original} / {revised}"


def _side_title(report: CompareReport, position: int, side: str) -> str:
    label = "Original" if side == "original" else "Revised"
    if position >= (report.page_count_a if side == "original" else report.page_count_b):
        return f"{label} {position + 1} — No corresponding page"
    return f"{label} {position + 1}"


def _page_or_none(
    document: fitz.Document, position: int
) -> fitz.Page | None:
    return document[position] if position < len(document) else None


def _displayed_rect(page: fitz.Page | None, fallback: fitz.Rect | None = None) -> fitz.Rect:
    if page is not None:
        return fitz.Rect(page.rect)
    if fallback is not None:
        return fitz.Rect(fallback)
    return fitz.Rect(0, 0, 612, 792)


def _slot_rects(
    original_page: fitz.Page | None,
    revised_page: fitz.Page | None,
) -> tuple[fitz.Rect, fitz.Rect]:
    original_rect = _displayed_rect(original_page)
    revised_rect = _displayed_rect(revised_page, original_rect if original_page else None)
    if original_page is None:
        original_rect = fitz.Rect(revised_rect)
    return original_rect, revised_rect


def _write_split_page(
    output: fitz.Document,
    original: fitz.Document,
    revised: fitz.Document,
    report: CompareReport,
    position: int,
    changes: Sequence[CompareChange],
    original_filename: str,
    revised_filename: str,
    *,
    cancel: CancelToken | None,
) -> None:
    original_page = _page_or_none(original, position)
    revised_page = _page_or_none(revised, position)
    original_rect, revised_rect = _slot_rects(original_page, revised_page)
    width = original_rect.width + _GUTTER_PT + revised_rect.width
    height = _HEADER_PT + max(original_rect.height, revised_rect.height) + _FOOTER_PT
    sheet = output.new_page(width=width, height=height)
    original_dest = fitz.Rect(0, _HEADER_PT, original_rect.width, _HEADER_PT + original_rect.height)
    revised_x = original_rect.width + _GUTTER_PT
    revised_dest = fitz.Rect(revised_x, _HEADER_PT, revised_x + revised_rect.width, _HEADER_PT + revised_rect.height)
    _compose_source(sheet, original, position, original_page, original_rect, original_dest)
    _compose_source(sheet, revised, position, revised_page, revised_rect, revised_dest)
    _draw_changes(sheet, original_page, revised_page, original_dest, revised_dest, changes)
    _draw_chrome(
        sheet,
        report,
        position,
        "split",
        original_filename,
        revised_filename,
        original_dest,
        revised_dest,
        report_page_number=sheet.number + 1,
    )


def _write_alternating_page(
    output: fitz.Document,
    original: fitz.Document,
    revised: fitz.Document,
    report: CompareReport,
    position: int,
    side: str,
    changes: Sequence[CompareChange],
    original_filename: str,
    revised_filename: str,
    *,
    cancel: CancelToken | None,
) -> None:
    page = _page_or_none(original if side == "original" else revised, position)
    other = _page_or_none(revised if side == "original" else original, position)
    source_rect = _displayed_rect(page, _displayed_rect(other))
    height = _HEADER_PT + source_rect.height + _FOOTER_PT
    sheet = output.new_page(width=source_rect.width, height=height)
    destination = fitz.Rect(0, _HEADER_PT, source_rect.width, _HEADER_PT + source_rect.height)
    source = original if side == "original" else revised
    _compose_source(sheet, source, position, page, source_rect, destination)
    if side == "original":
        _draw_changes(sheet, page, other, destination, destination, changes, only_side="original")
    else:
        _draw_changes(sheet, other, page, destination, destination, changes, only_side="revised")
    _draw_chrome(
        sheet,
        report,
        position,
        side,
        original_filename,
        revised_filename,
        destination if side == "original" else destination,
        destination if side == "revised" else destination,
        report_page_number=sheet.number + 1,
    )


def _compose_source(
    sheet: fitz.Page,
    source: fitz.Document,
    position: int,
    page: fitz.Page | None,
    source_rect: fitz.Rect,
    destination: fitz.Rect,
) -> None:
    if page is not None and _has_importable_content(page):
        sheet.show_pdf_page(destination, source, position, keep_proportion=False, overlay=True)


def _has_importable_content(page: fitz.Page) -> bool:
    return bool(page.get_contents())


def _draw_changes(
    sheet: fitz.Page,
    original_page: fitz.Page | None,
    revised_page: fitz.Page | None,
    original_dest: fitz.Rect,
    revised_dest: fitz.Rect,
    changes: Sequence[CompareChange],
    *,
    only_side: str | None = None,
) -> None:
    for change in changes:
        if only_side != "revised" and original_page is not None and change.rects_a:
            _draw_rects(sheet, original_page, original_dest, change.rects_a, _RED)
        if only_side != "original" and revised_page is not None and change.rects_b:
            _draw_rects(sheet, revised_page, revised_dest, change.rects_b, _GREEN)


def _draw_rects(
    sheet: fitz.Page,
    source_page: fitz.Page,
    destination: fitz.Rect,
    rects: Sequence[tuple[float, float, float, float]],
    color: tuple[float, float, float],
) -> None:
    displayed_rect = source_page.rect
    for rect in rects:
        displayed = fitz.Rect(rect) * source_page.rotation_matrix
        mapped = transform_rect(displayed, displayed_page_rect(source_page), destination)
        sheet.draw_rect(
            mapped,
            color=color,
            fill=color,
            width=0,
            fill_opacity=_OVERLAY_OPACITY,
            overlay=True,
        )


def displayed_page_rect(page: fitz.Page) -> fitz.Rect:
    """Return the page rectangle in the coordinate space used by rotation_matrix."""
    return fitz.Rect(0, 0, page.rect.width, page.rect.height)


def _draw_chrome(
    sheet: fitz.Page,
    report: CompareReport,
    position: int,
    mode: str,
    original_filename: str,
    revised_filename: str,
    original_dest: fitz.Rect,
    revised_dest: fitz.Rect,
    *,
    report_page_number: int,
) -> None:
    if mode == "split":
        _label_page(
            sheet,
            original_dest,
            "Original",
            original_filename,
            position + 1,
            position in report.textless_pages_a,
            position < report.page_count_a,
        )
        _label_page(
            sheet,
            revised_dest,
            "Revised",
            revised_filename,
            position + 1,
            position in report.textless_pages_b,
            position < report.page_count_b,
        )
    else:
        is_original = mode == "original"
        dest = original_dest if is_original else revised_dest
        _label_page(
            sheet,
            dest,
            "Original" if is_original else "Revised",
            original_filename if is_original else revised_filename,
            position + 1,
            position in (
                report.textless_pages_a
                if is_original
                else report.textless_pages_b
            ),
            position < (report.page_count_a if is_original else report.page_count_b),
        )

    footer = fitz.Rect(
        _MARGIN_PT,
        sheet.rect.height - _FOOTER_PT + 3,
        sheet.rect.width - _MARGIN_PT,
        sheet.rect.height - _MARGIN_PT,
    )
    legend = (
        f"Report page {report_page_number}  |  Legend: Removed / replacement before = red; "
        "Added / replacement after = green"
    )
    sheet.insert_textbox(footer, legend, fontsize=_SMALL_TEXT_PT, color=(0.25, 0.25, 0.25))
    sheet.insert_textbox(
        fitz.Rect(_MARGIN_PT, footer.y1 - 28, sheet.rect.width - _MARGIN_PT, footer.y1 - 15),
        "Text comparison, matched by page number.",
        fontsize=_SMALL_TEXT_PT,
        color=(0.25, 0.25, 0.25),
    )
    sheet.insert_textbox(
        fitz.Rect(_MARGIN_PT, footer.y1 - 15, sheet.rect.width - _MARGIN_PT, footer.y1),
        "Image, formatting, and moved-content differences are not classified.",
        fontsize=_SMALL_TEXT_PT,
        color=(0.25, 0.25, 0.25),
    )
    if not report.changes:
        sheet.insert_text(
            (sheet.rect.width - 112, sheet.rect.height - 8),
            "No text changes detected",
            fontsize=_SMALL_TEXT_PT,
            color=(0.25, 0.25, 0.25),
        )


def _label_page(
    sheet: fitz.Page,
    destination: fitz.Rect,
    side: str,
    filename: str,
    page_number: int,
    textless: bool,
    present: bool,
) -> None:
    title = side if present else f"{side} — No corresponding page"
    sheet.insert_text((destination.x0 + _MARGIN_PT, 16), title, fontsize=10, color=(0.12, 0.12, 0.12))
    sheet.insert_textbox(
        fitz.Rect(destination.x0 + _MARGIN_PT, 22, destination.x1 - _MARGIN_PT, 38),
        filename,
        fontsize=_TEXT_PT,
        color=(0.3, 0.3, 0.3),
    )
    if textless and present:
        sheet.insert_text(
            (destination.x0 + _MARGIN_PT, 51),
            "No extractable text on this page",
            fontsize=_SMALL_TEXT_PT,
            color=(0.45, 0.2, 0.2),
        )
    page_ref = f"Page {page_number}" if present else "No corresponding page"
    sheet.insert_text(
        (destination.x0 + _MARGIN_PT, 61),
        page_ref,
        fontsize=_SMALL_TEXT_PT,
        color=(0.3, 0.3, 0.3),
    )
