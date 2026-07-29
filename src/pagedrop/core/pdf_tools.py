from __future__ import annotations

import difflib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, cast

import fitz

from pagedrop.core.jobs.cancel import CancelToken, check_cancel as _check_cancel
from pagedrop.core.jobs.paths import reject_source_overwrite
from pagedrop.core.pdf_loader import open_pdf
from pagedrop.core.pdf_service import FITZ_LOCK, attachments_for_path, extract_attachment


STANDARD_METADATA_KEYS: tuple[str, ...] = (
    "title",
    "author",
    "subject",
    "keywords",
    "creator",
    "producer",
    "creationDate",
    "modDate",
    "trapped",
)

# Compare streams one page-pair at a time; never keep full-doc pixmaps.
COMPARE_MAX_RENDER_WIDTH_PX = 2048
# Stride (px) for in-page sampling — fixed 3×3 cell probes miss thin text lines.
COMPARE_SAMPLE_STRIDE_PX = 4


def predicted_range_output_paths(
    ranges: list[tuple[int, int]],
    output_dir: str | Path,
    *,
    base_name: str = "range",
    zero_pad: int = 4,
) -> list[Path]:
    """Return the paths ``extract_ranges_to_folder`` would write for *ranges*."""
    out_dir = Path(output_dir)
    paths: list[Path] = []
    for start, end in ranges:
        if start < 0 or end < start:
            raise ValueError(f"Invalid range: {(start, end)}")
        name = (
            f"{base_name}_range_{start + 1:0{zero_pad}d}-"
            f"{end + 1:0{zero_pad}d}.pdf"
        )
        paths.append(out_dir / name)
    return paths


def extract_ranges_to_folder(
    source_pdf: str,
    ranges: list[tuple[int, int]],
    output_dir: str | Path,
    *,
    base_name: str = "range",
    zero_pad: int = 4,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> list[Path]:
    """Extract each inclusive (start,end) page range into a separate PDF.

    `start` / `end` are 0-based page indices.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    src = open_pdf(source_pdf, password=password)
    out_paths: list[Path] = []
    try:
        for start, end in ranges:
            _check_cancel(cancel)
            if start < 0 or end < start:
                raise ValueError(f"Invalid range: {(start, end)}")
            if end >= len(src):
                raise ValueError(f"Range out of bounds: {(start, end)}")

            out = fitz.open()
            try:
                out.insert_pdf(src, from_page=start, to_page=end)
                name = (
                    f"{base_name}_range_{start + 1:0{zero_pad}d}-"
                    f"{end + 1:0{zero_pad}d}.pdf"
                )
                out_path = out_dir / name
                reject_source_overwrite(out_path, source_pdf)
                out.save(str(out_path))
                out_paths.append(out_path)
            finally:
                out.close()
    finally:
        src.close()

    return out_paths


def alternate_pdfs(
    pdf_a: str,
    pdf_b: str,
    output_path: str,
    *,
    start_with_a: bool = True,
    password_a: str | None = None,
    password_b: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Create a new PDF by alternating pages from `pdf_a` and `pdf_b`.

    Extra pages from the longer input are appended after the shorter ends.
    """
    reject_source_overwrite(output_path, pdf_a, pdf_b)

    a = open_pdf(pdf_a, password=password_a)
    b = open_pdf(pdf_b, password=password_b)
    out = fitz.open()
    try:
        i = 0
        j = 0
        a_turn = start_with_a
        while i < len(a) or j < len(b):
            _check_cancel(cancel)
            if a_turn:
                if i < len(a):
                    out.insert_pdf(a, from_page=i, to_page=i)
                    i += 1
                a_turn = False
            else:
                if j < len(b):
                    out.insert_pdf(b, from_page=j, to_page=j)
                    j += 1
                a_turn = True

            # If one side is exhausted, keep pulling from the other.
            if i >= len(a):
                a_turn = False
            if j >= len(b):
                a_turn = True
        out.save(output_path)
    finally:
        a.close()
        b.close()
        out.close()


def reverse_pdf_pages(
    source_pdf: str,
    output_path: str,
    *,
    add_blank_page: bool = False,
    blank_size_from: str = "last",
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Reverse page order and optionally append a blank page.

    `blank_size_from` is 'last' or 'first' (in source order).
    """
    reject_source_overwrite(output_path, source_pdf)

    src = open_pdf(source_pdf, password=password)
    out = fitz.open()
    try:
        for pno in reversed(range(len(src))):
            _check_cancel(cancel)
            out.insert_pdf(src, from_page=pno, to_page=pno)

        if add_blank_page:
            if blank_size_from == "last":
                ref = src[len(src) - 1].rect
            elif blank_size_from == "first":
                ref = src[0].rect
            else:
                raise ValueError("blank_size_from must be 'last' or 'first'")
            out.new_page(width=ref.width, height=ref.height)
        out.save(output_path)
    finally:
        src.close()
        out.close()


def _page_rect_for_source(doc: fitz.Document, page_index: int) -> fitz.Rect:
    # MuPDF / MuPDF keeps rotation in `page.rect`; we mirror that behavior.
    return doc[page_index].rect


def normalize_pdf_page_size(
    source_pdf: str,
    output_path: str,
    target_width_pt: float,
    target_height_pt: float,
    *,
    strategy: str = "fit",
    margins_pt: float | tuple[float, float] = 0.0,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Normalize every page to an explicit target size.

    `strategy`:
    - 'fit': preserve aspect ratio (may leave empty space)
    - 'fill': stretch to fill (may distort)

    `margins_pt` is either a single float (uniform) or (x_margin, y_margin).
    """
    reject_source_overwrite(output_path, source_pdf)

    if target_width_pt <= 0 or target_height_pt <= 0:
        raise ValueError("target_* must be positive")

    src = open_pdf(source_pdf, password=password)
    out = fitz.open()
    try:
        if isinstance(margins_pt, tuple):
            mx, my = margins_pt
        else:
            mx = my = margins_pt

        if mx < 0 or my < 0:
            raise ValueError("margins_pt must be non-negative")

        keep_proportion = strategy == "fit"
        if strategy not in {"fit", "fill"}:
            raise ValueError("strategy must be 'fit' or 'fill'")

        dest = fitz.Rect(mx, my, target_width_pt - mx, target_height_pt - my)
        for pno in range(len(src)):
            _check_cancel(cancel)
            out_page = out.new_page(width=target_width_pt, height=target_height_pt)
            out_page.show_pdf_page(
                dest, src, pno, keep_proportion=keep_proportion, overlay=True
            )
        out.save(output_path)
    finally:
        src.close()
        out.close()


def n_up_pdf(
    source_pdf: str,
    output_path: str,
    *,
    rows: int,
    cols: int,
    margin_pt: float = 0.0,
    keep_proportion: bool = True,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Pack multiple pages onto a grid (row-major order)."""
    reject_source_overwrite(output_path, source_pdf)
    if rows <= 0 or cols <= 0:
        raise ValueError("rows/cols must be positive")

    src = open_pdf(source_pdf, password=password)
    out = fitz.open()
    try:
        first_rect = _page_rect_for_source(src, 0)
        out_w = float(first_rect.width)
        out_h = float(first_rect.height)

        usable_w = out_w - 2.0 * margin_pt
        usable_h = out_h - 2.0 * margin_pt
        if usable_w <= 0 or usable_h <= 0:
            raise ValueError("margin_pt too large for page size")

        cell_w = usable_w / cols
        cell_h = usable_h / rows

        per_sheet = rows * cols
        pno = 0
        while pno < len(src):
            _check_cancel(cancel)
            sheet = out.new_page(width=out_w, height=out_h)
            for r in range(rows):
                for c in range(cols):
                    if pno >= len(src):
                        break
                    dest = fitz.Rect(
                        margin_pt + c * cell_w,
                        margin_pt + r * cell_h,
                        margin_pt + (c + 1) * cell_w,
                        margin_pt + (r + 1) * cell_h,
                    )
                    sheet.show_pdf_page(
                        dest,
                        src,
                        pno,
                        keep_proportion=keep_proportion,
                        overlay=True,
                    )
                    pno += 1
        out.save(output_path)
    finally:
        src.close()
        out.close()


def booklet_pdf(
    source_pdf: str,
    output_path: str,
    *,
    margin_pt: float = 0.0,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Simple 2-up "booklet-like" imposition.

    This is a pragmatic arrangement (left/right spread from ends).
    Full duplex fold imposition rules can be added later if needed.
    """
    reject_source_overwrite(output_path, source_pdf)
    src = open_pdf(source_pdf, password=password)
    out = fitz.open()
    try:
        first_rect = _page_rect_for_source(src, 0)
        out_w = float(first_rect.width)
        out_h = float(first_rect.height)

        # Pad to even by adding virtual blanks.
        total = len(src)
        if total % 2 == 1:
            total_padded = total + 1
        else:
            total_padded = total

        half_w = (out_w - 2.0 * margin_pt) / 2.0
        dest_left = fitz.Rect(margin_pt, margin_pt, margin_pt + half_w, out_h - margin_pt)
        dest_right = fitz.Rect(
            margin_pt + half_w, margin_pt, out_w - margin_pt, out_h - margin_pt
        )

        for k in range(total_padded // 2):
            _check_cancel(cancel)
            sheet = out.new_page(width=out_w, height=out_h)
            left_idx = k
            right_idx = total_padded - 1 - k
            if left_idx < len(src):
                sheet.show_pdf_page(dest_left, src, left_idx, keep_proportion=True, overlay=True)
            if right_idx < len(src):
                sheet.show_pdf_page(
                    dest_right, src, right_idx, keep_proportion=True, overlay=True
                )
        out.save(output_path)
    finally:
        src.close()
        out.close()


def posterize_pdf(
    source_pdf: str,
    output_path: str,
    *,
    rows: int,
    cols: int,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Split each page into a grid of cropped tiles (each tile becomes a page)."""
    reject_source_overwrite(output_path, source_pdf)
    if rows <= 0 or cols <= 0:
        raise ValueError("rows/cols must be positive")

    src = open_pdf(source_pdf, password=password)
    out = fitz.open()
    try:
        first_rect = _page_rect_for_source(src, 0)
        w = float(first_rect.width)
        h = float(first_rect.height)

        tile_w = w / cols
        tile_h = h / rows

        dest = fitz.Rect(0, 0, w, h)
        for pno in range(len(src)):
            _check_cancel(cancel)
            for r in range(rows):
                for c in range(cols):
                    clip = fitz.Rect(c * tile_w, r * tile_h, (c + 1) * tile_w, (r + 1) * tile_h)
                    tile_page = out.new_page(width=w, height=h)
                    tile_page.show_pdf_page(
                        dest,
                        src,
                        pno,
                        keep_proportion=False,
                        overlay=True,
                        clip=clip,
                    )
        out.save(output_path)
    finally:
        src.close()
        out.close()


def divide_pdf_pages(
    source_pdf: str,
    output_path: str,
    *,
    direction: str,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Divide each page into 2 tiles and return a 2x page-count output.

    `direction`:
    - 'vertical': split into left/right
    - 'horizontal': split into top/bottom
    """
    reject_source_overwrite(output_path, source_pdf)
    if direction not in {"vertical", "horizontal"}:
        raise ValueError("direction must be 'vertical' or 'horizontal'")

    src = open_pdf(source_pdf, password=password)
    out = fitz.open()
    try:
        first_rect = _page_rect_for_source(src, 0)
        w = float(first_rect.width)
        h = float(first_rect.height)

        if direction == "vertical":
            half_w = w / 2.0
            dest_left = fitz.Rect(0, 0, half_w, h)
            dest_right = fitz.Rect(0, 0, half_w, h)
            clip_left = fitz.Rect(0, 0, half_w, h)
            clip_right = fitz.Rect(half_w, 0, w, h)
            for pno in range(len(src)):
                _check_cancel(cancel)
                page = out.new_page(width=half_w, height=h)
                page.show_pdf_page(
                    dest_left,
                    src,
                    pno,
                    keep_proportion=False,
                    overlay=True,
                    clip=clip_left,
                )
                page = out.new_page(width=half_w, height=h)
                page.show_pdf_page(
                    dest_right,
                    src,
                    pno,
                    keep_proportion=False,
                    overlay=True,
                    clip=clip_right,
                )
        else:
            half_h = h / 2.0
            dest_top = fitz.Rect(0, 0, w, half_h)
            dest_bottom = fitz.Rect(0, 0, w, half_h)
            clip_top = fitz.Rect(0, 0, w, half_h)
            clip_bottom = fitz.Rect(0, half_h, w, h)
            for pno in range(len(src)):
                _check_cancel(cancel)
                page = out.new_page(width=w, height=half_h)
                page.show_pdf_page(
                    dest_top,
                    src,
                    pno,
                    keep_proportion=False,
                    overlay=True,
                    clip=clip_top,
                )
                page = out.new_page(width=w, height=half_h)
                page.show_pdf_page(
                    dest_bottom,
                    src,
                    pno,
                    keep_proportion=False,
                    overlay=True,
                    clip=clip_bottom,
                )

        out.save(output_path)
    finally:
        src.close()
        out.close()


def combine_pages_to_single_long(
    source_pdf: str,
    output_path: str,
    *,
    axis: str = "vertical",
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Combine all pages into one long page (vertical stacking)."""
    reject_source_overwrite(output_path, source_pdf)
    if axis != "vertical":
        raise ValueError("axis must be 'vertical'")

    src = open_pdf(source_pdf, password=password)
    out = fitz.open()
    try:
        # Standardize to first page width; scale other pages proportionally.
        base_rect = _page_rect_for_source(src, 0)
        out_w = float(base_rect.width)
        scales: list[float] = []
        scaled_heights: list[float] = []
        for pno in range(len(src)):
            _check_cancel(cancel)
            rect = _page_rect_for_source(src, pno)
            scale = out_w / float(rect.width)
            scales.append(scale)
            scaled_heights.append(float(rect.height) * scale)

        out_h = float(sum(scaled_heights))
        combined = out.new_page(width=out_w, height=out_h)

        y = 0.0
        for pno, scale, sh in zip(range(len(src)), scales, scaled_heights, strict=True):
            _check_cancel(cancel)
            rect = _page_rect_for_source(src, pno)
            # Keep aspect ratio: dest rect already has the scaled height.
            dest = fitz.Rect(0, y, out_w, y + sh)
            combined.show_pdf_page(
                dest,
                src,
                pno,
                keep_proportion=True,
                overlay=True,
            )
            y += sh

        out.save(output_path)
    finally:
        src.close()
        out.close()


def attachments_list(path: str, *, password: str | None = None) -> list:
    """List embedded files in `path`."""
    # pdf_service already implements capability-safe access under FITZ_LOCK.
    # This helper is kept lightweight.
    return attachments_for_path(path, password=password)


def attachment_add(
    source_pdf: str,
    output_path: str,
    *,
    name: str,
    data: bytes,
    filename: str | None = None,
    ufilename: str | None = None,
    desc: str | None = None,
    overwrite: bool = False,
    password: str | None = None,
) -> None:
    """Add (or replace) an embedded file."""
    reject_source_overwrite(output_path, source_pdf)
    src = open_pdf(source_pdf, password=password)
    try:
        names = set(src.embfile_names())
        if name in names and not overwrite:
            raise FileExistsError(f"Attachment already exists: {name}")
        if name in names and overwrite:
            src.embfile_del(name)
        src.embfile_add(
            name,
            data,
            filename=filename,
            ufilename=ufilename,
            desc=desc,
        )
        src.save(output_path)
    finally:
        src.close()


def attachment_remove(
    source_pdf: str,
    output_path: str,
    *,
    name: str,
    missing_ok: bool = False,
    password: str | None = None,
) -> None:
    """Remove an embedded file by name."""
    reject_source_overwrite(output_path, source_pdf)
    src = open_pdf(source_pdf, password=password)
    try:
        names = set(src.embfile_names())
        if name not in names:
            if missing_ok:
                src.save(output_path)
                return
            raise FileNotFoundError(f"Attachment not found: {name}")
        src.embfile_del(name)
        src.save(output_path)
    finally:
        src.close()


def attachment_extract(
    source_pdf: str,
    name: str,
    dest_dir: str | Path,
    *,
    password: str | None = None,
) -> Path:
    """Extract embedded file bytes to `dest_dir`."""
    return extract_attachment(
        source_pdf, name, dest_dir, password=password
    )


def attachment_extract_all_zip(
    source_pdf: str,
    output_zip: str | Path,
    *,
    password: str | None = None,
) -> Path:
    """Extract every embedded file into a ZIP at `output_zip`."""
    out_zip = Path(output_zip)
    reject_source_overwrite(out_zip, source_pdf)
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    src = open_pdf(source_pdf, password=password)
    try:
        names = list(src.embfile_names())
        if not names:
            raise FileNotFoundError("No attachments in PDF")
        used: set[str] = set()
        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in names:
                data = src.embfile_get(name)
                if data is None:
                    raise FileNotFoundError(f"Attachment not found: {name}")
                arc = Path(name).name or "attachment.bin"
                if arc in used:
                    stem, suffix = Path(arc).stem, Path(arc).suffix
                    n = 1
                    while True:
                        candidate = f"{stem}_{n}{suffix}"
                        if candidate not in used:
                            arc = candidate
                            break
                        n += 1
                used.add(arc)
                zf.writestr(arc, data)
    finally:
        src.close()
    return out_zip


def metadata_get(path: str, *, password: str | None = None) -> dict[str, Any]:
    """Return PDF /Info metadata (standard fields)."""
    doc = open_pdf(path, password=password)
    try:
        # PyMuPDF typing for `metadata` is imprecise; treat as unstructured dict.
        return cast(dict[str, Any], doc.metadata or {})
    finally:
        doc.close()


def metadata_set(
    source_pdf: str,
    output_path: str,
    *,
    updates: dict[str, object],
    password: str | None = None,
) -> None:
    """Edit standard metadata fields and write a new file."""
    reject_source_overwrite(output_path, source_pdf)

    doc = open_pdf(source_pdf, password=password)
    try:
        meta = cast(dict[str, Any], doc.metadata or {})
        for key, value in updates.items():
            if key not in STANDARD_METADATA_KEYS:
                continue
            # Keep fitz happy: all standard fields are stored as strings.
            meta[key] = "" if value is None else str(value)
        doc.set_metadata(cast(dict[str, Any], meta))
        doc.save(output_path)
    finally:
        doc.close()


def metadata_strip(
    source_pdf: str,
    output_path: str,
    *,
    strip_xmp_v1: bool = True,
    password: str | None = None,
) -> None:
    """Strip standard metadata fields and (optionally) XMP.

    XMP strip-only v1: delete XML metadata at the document level, without
    trying to preserve or reserialize any subset.
    """
    reject_source_overwrite(output_path, source_pdf)

    doc = open_pdf(source_pdf, password=password)
    try:
        meta = cast(dict[str, Any], doc.metadata or {})
        for key in STANDARD_METADATA_KEYS:
            if key in meta:
                meta[key] = ""
        doc.set_metadata(cast(dict[str, Any], meta))

        if strip_xmp_v1:
            doc.del_xml_metadata()

        doc.save(output_path)
    finally:
        doc.close()


def xmp_get(path: str, *, password: str | None = None) -> str:
    """Return document-level XML metadata (XMP) as a string."""
    doc = open_pdf(path, password=password)
    try:
        return str(doc.get_xml_metadata() or "")
    finally:
        doc.close()


def page_labels_get(path: str, *, password: str | None = None) -> list[dict]:
    """Return PDF page label definitions."""
    doc = open_pdf(path, password=password)
    try:
        return list(doc.get_page_labels())
    finally:
        doc.close()


def page_labels_set(
    source_pdf: str,
    output_path: str,
    *,
    labels: list[dict],
    password: str | None = None,
) -> None:
    """Set page label definitions and write a new file."""
    reject_source_overwrite(output_path, source_pdf)
    doc = open_pdf(source_pdf, password=password)
    try:
        doc.set_page_labels(labels)
        doc.save(output_path)
    finally:
        doc.close()


def zip_pdfs(paths: Iterable[str | Path], output_zip_path: str | Path) -> Path:
    """Zip PDF files into a new archive."""
    out_zip = Path(output_zip_path)
    reject_source_overwrite(out_zip, *paths)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            pp = Path(p)
            zf.write(str(pp), arcname=pp.name)
    return out_zip


@dataclass(frozen=True)
class CompareResult:
    overall_diff_ratio: float
    page_diffs: list[float]
    heatmap_pdf: Path


CompareChangeKind = Literal["deleted", "added", "modified"]


@dataclass(frozen=True)
class CompareChange:
    kind: CompareChangeKind
    page_a: int | None
    page_b: int | None
    text: str
    rects_a: tuple[tuple[float, float, float, float], ...] = ()
    rects_b: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True)
class CompareReport:
    changes: tuple[CompareChange, ...]
    page_count_a: int
    page_count_b: int

    @property
    def deleted_count(self) -> int:
        return sum(1 for c in self.changes if c.kind == "deleted")

    @property
    def added_count(self) -> int:
        return sum(1 for c in self.changes if c.kind == "added")

    @property
    def modified_count(self) -> int:
        return sum(1 for c in self.changes if c.kind == "modified")


def _word_items(page: fitz.Page) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Return (text, rect) for each word in reading order."""
    items: list[tuple[str, tuple[float, float, float, float]]] = []
    for w in page.get_text("words"):
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
        if not text:
            continue
        items.append((str(text), (float(x0), float(y0), float(x1), float(y1))))
    return items


def _merge_word_rects(
    rects: list[tuple[float, float, float, float]],
    *,
    y_slop: float = 3.0,
) -> tuple[tuple[float, float, float, float], ...]:
    """Merge horizontally adjacent word boxes on the same baseline into spans."""
    if not rects:
        return ()
    ordered = sorted(rects, key=lambda r: (r[1], r[0]))
    spans: list[list[float]] = []
    cur = [ordered[0][0], ordered[0][1], ordered[0][2], ordered[0][3]]
    for x0, y0, x1, y1 in ordered[1:]:
        same_line = abs(y0 - cur[1]) <= y_slop and abs(y1 - cur[3]) <= y_slop
        if same_line and x0 <= cur[2] + 8.0:
            cur[2] = max(cur[2], x1)
            cur[1] = min(cur[1], y0)
            cur[3] = max(cur[3], y1)
        else:
            spans.append(cur)
            cur = [x0, y0, x1, y1]
    spans.append(cur)
    return tuple((s[0], s[1], s[2], s[3]) for s in spans)


def _page_word_diff(
    words_a: list[tuple[str, tuple[float, float, float, float]]],
    words_b: list[tuple[str, tuple[float, float, float, float]]],
    *,
    page_a: int,
    page_b: int,
) -> list[CompareChange]:
    texts_a = [w[0] for w in words_a]
    texts_b = [w[0] for w in words_b]
    matcher = difflib.SequenceMatcher(a=texts_a, b=texts_b, autojunk=False)
    changes: list[CompareChange] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            chunk = words_a[i1:i2]
            text = " ".join(w[0] for w in chunk)
            rects = _merge_word_rects([w[1] for w in chunk])
            changes.append(
                CompareChange(
                    kind="deleted",
                    page_a=page_a,
                    page_b=page_b,
                    text=text,
                    rects_a=rects,
                )
            )
        elif tag == "insert":
            chunk = words_b[j1:j2]
            text = " ".join(w[0] for w in chunk)
            rects = _merge_word_rects([w[1] for w in chunk])
            changes.append(
                CompareChange(
                    kind="added",
                    page_a=page_a,
                    page_b=page_b,
                    text=text,
                    rects_b=rects,
                )
            )
        else:  # replace
            chunk_a = words_a[i1:i2]
            chunk_b = words_b[j1:j2]
            text_a = " ".join(w[0] for w in chunk_a)
            text_b = " ".join(w[0] for w in chunk_b)
            label = f"{text_a} → {text_b}" if text_a and text_b else (text_a or text_b)
            changes.append(
                CompareChange(
                    kind="modified",
                    page_a=page_a,
                    page_b=page_b,
                    text=label,
                    rects_a=_merge_word_rects([w[1] for w in chunk_a]),
                    rects_b=_merge_word_rects([w[1] for w in chunk_b]),
                )
            )
    return changes


def compare_pdf_text_diff(
    pdf_a: str,
    pdf_b: str,
    *,
    password_a: str | None = None,
    password_b: str | None = None,
    cancel: CancelToken | None = None,
) -> CompareReport:
    """Word-level text diff with geometry for side-by-side highlight overlays.

    Page indices are aligned 0..min(n_a, n_b)-1. Extra trailing pages are reported
    as wholesale deleted (A only) or added (B only) changes.
    Holds ``FITZ_LOCK`` for open/work/close (Compare GUI text-diff path).
    """
    with FITZ_LOCK:
        a = open_pdf(pdf_a, password=password_a)
        b = open_pdf(pdf_b, password=password_b)
        try:
            changes: list[CompareChange] = []
            shared = min(len(a), len(b))
            for pno in range(shared):
                _check_cancel(cancel)
                changes.extend(
                    _page_word_diff(
                        _word_items(a[pno]),
                        _word_items(b[pno]),
                        page_a=pno,
                        page_b=pno,
                    )
                )
            for pno in range(shared, len(a)):
                _check_cancel(cancel)
                words = _word_items(a[pno])
                text = " ".join(w[0] for w in words) or f"(page {pno + 1})"
                changes.append(
                    CompareChange(
                        kind="deleted",
                        page_a=pno,
                        page_b=None,
                        text=text,
                        rects_a=_merge_word_rects([w[1] for w in words])
                        or (
                            (
                                0.0,
                                0.0,
                                float(a[pno].rect.width),
                                float(a[pno].rect.height),
                            ),
                        ),
                    )
                )
            for pno in range(shared, len(b)):
                _check_cancel(cancel)
                words = _word_items(b[pno])
                text = " ".join(w[0] for w in words) or f"(page {pno + 1})"
                changes.append(
                    CompareChange(
                        kind="added",
                        page_a=None,
                        page_b=pno,
                        text=text,
                        rects_b=_merge_word_rects([w[1] for w in words])
                        or (
                            (
                                0.0,
                                0.0,
                                float(b[pno].rect.width),
                                float(b[pno].rect.height),
                            ),
                        ),
                    )
                )
            return CompareReport(
                changes=tuple(changes),
                page_count_a=len(a),
                page_count_b=len(b),
            )
        finally:
            a.close()
            b.close()


def compare_pdfs_heatmap(
    pdf_a: str,
    pdf_b: str,
    output_heatmap_pdf: str | Path,
    *,
    dpi: int = 120,
    sample_grid: tuple[int, int] = (24, 32),
    byte_diff_threshold: int = 20,
    sample_stride_px: int = COMPARE_SAMPLE_STRIDE_PX,
    max_pages: int | None = None,
    password_a: str | None = None,
    password_b: str | None = None,
    cancel: CancelToken | None = None,
) -> CompareResult:
    """Compare two PDFs visually via sampled pixel diffs and emit a heatmap PDF.

    Output pages show PDF A with red overlays where sampled cells differ from B.
    Sampling walks the page on a pixel stride (not a few probes per cell) so thin
    deleted/inserted text lines are not skipped.
    No OpenCV; uses MuPDF pixmaps + sampled absolute byte diffs.
    """
    out_path = Path(output_heatmap_pdf)
    reject_source_overwrite(out_path, pdf_a, pdf_b)
    a = open_pdf(pdf_a, password=password_a)
    b = open_pdf(pdf_b, password=password_b)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = fitz.open()
    try:
        cols, rows = sample_grid
        if cols <= 0 or rows <= 0:
            raise ValueError("sample_grid must be positive")
        stride = max(1, int(sample_stride_px))

        page_limit = min(len(a), len(b))
        if max_pages is not None:
            page_limit = min(page_limit, max_pages)

        page_diffs: list[float] = []

        # Compare page-by-page; heatmap is one page per compared source page.
        for pno in range(page_limit):
            _check_cancel(cancel)
            a_page = a[pno]
            b_page = b[pno]
            a_rect = a_page.rect
            b_rect = b_page.rect

            # Keep dpi consistent by using a's width scaling, then sample overlap.
            scale = float(dpi) / 72.0
            a_target_w = int(round(float(a_rect.width) * scale))
            b_target_w = int(round(float(b_rect.width) * scale))
            # Safety: keep render sizes bounded.
            a_target_w = max(1, min(a_target_w, COMPARE_MAX_RENDER_WIDTH_PX))
            b_target_w = max(1, min(b_target_w, COMPARE_MAX_RENDER_WIDTH_PX))
            a_scale_eff = a_target_w / float(a_rect.width)
            b_scale_eff = b_target_w / float(b_rect.width)
            mat_a = fitz.Matrix(a_scale_eff, a_scale_eff)
            mat_b = fitz.Matrix(b_scale_eff, b_scale_eff)

            pix_a = a_page.get_pixmap(matrix=mat_a, alpha=False)
            pix_b = b_page.get_pixmap(matrix=mat_b, alpha=False)

            w_a = pix_a.width
            h_a = pix_a.height
            w_b = pix_b.width
            h_b = pix_b.height

            n_a = max(1, pix_a.n)
            n_b = max(1, pix_b.n)
            samples_a = pix_a.samples
            samples_b = pix_b.samples
            n = min(n_a, n_b)

            # Aggregate stride samples into the overlay grid (max channel delta).
            max_delta: list[list[int]] = [
                [0 for _ in range(cols)] for _ in range(rows)
            ]
            for ya in range(0, h_a, stride):
                # Map A's sample row into B's pixmap space.
                yb = min(h_b - 1, int(ya * h_b / h_a))
                row_a = ya * w_a * n_a
                row_b = yb * w_b * n_b
                overlay_r = min(rows - 1, ya * rows // h_a)
                for xa in range(0, w_a, stride):
                    xb = min(w_b - 1, int(xa * w_b / w_a))
                    idx_a = row_a + xa * n_a
                    idx_b = row_b + xb * n_b
                    cell_max = 0
                    for k in range(n):
                        abs_d = abs(int(samples_a[idx_a + k]) - int(samples_b[idx_b + k]))
                        if abs_d > cell_max:
                            cell_max = abs_d
                    if cell_max < byte_diff_threshold:
                        continue
                    overlay_c = min(cols - 1, xa * cols // w_a)
                    if cell_max > max_delta[overlay_r][overlay_c]:
                        max_delta[overlay_r][overlay_c] = cell_max

            diff_intensity: list[list[float]] = [
                [
                    min(1.0, max_delta[r][c] / 255.0) if max_delta[r][c] else 0.0
                    for c in range(cols)
                ]
                for r in range(rows)
            ]
            cell_diff_count = sum(
                1 for r in range(rows) for c in range(cols) if max_delta[r][c]
            )
            page_diffs.append(cell_diff_count / float(cols * rows))

            out_page = out.new_page(
                width=float(a_rect.width), height=float(a_rect.height)
            )
            # Show PDF A as the base so the heatmap isn't a blank white page.
            out_page.show_pdf_page(out_page.rect, a, pno)
            for r in range(rows):
                for c in range(cols):
                    intensity = diff_intensity[r][c]
                    if intensity <= 0:
                        continue
                    cell = fitz.Rect(
                        (float(a_rect.width) * c / cols),
                        (float(a_rect.height) * r / rows),
                        (float(a_rect.width) * (c + 1) / cols),
                        (float(a_rect.height) * (r + 1) / rows),
                    )
                    out_page.draw_rect(
                        cell,
                        color=(1, 0, 0),
                        fill=(1, 0, 0),
                        width=0,
                        overlay=True,
                        fill_opacity=0.30 + 0.45 * intensity,
                    )

        overall = sum(page_diffs) / float(len(page_diffs)) if page_diffs else 0.0
        out.save(str(out_path))
        return CompareResult(
            overall_diff_ratio=overall,
            page_diffs=page_diffs,
            heatmap_pdf=out_path,
        )
    finally:
        a.close()
        b.close()
        out.close()

