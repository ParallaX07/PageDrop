from __future__ import annotations

import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, cast

import fitz

from pagedrop.core.pdf_loader import (
    PdfCorruptError,
    PdfEmptyError,
    PdfLoadError,
    PdfNotFoundError,
    PdfPasswordError,
    PdfPasswordRequiredError,
)
from pagedrop.core.pdf_service import attachments_for_path, extract_attachment


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


def _open(path: str, password: str | None = None) -> fitz.Document:
    pdf_path = Path(path)
    try:
        if not pdf_path.is_file():
            raise PdfNotFoundError(f"PDF not found: {path}")
    except OSError as exc:
        raise PdfLoadError(f"Could not access PDF: {path}") from exc

    try:
        doc = fitz.open(path)
    except fitz.EmptyFileError as exc:
        raise PdfCorruptError(f"PDF file is empty: {path}") from exc
    except fitz.FileDataError as exc:
        raise PdfCorruptError(f"PDF file is corrupt or invalid: {path}") from exc
    except fitz.FileNotFoundError as exc:
        raise PdfNotFoundError(f"PDF not found: {path}") from exc

    try:
        if doc.needs_pass:
            if password is None:
                raise PdfPasswordRequiredError(f"PDF is password-protected: {path}")
            if doc.authenticate(password) == 0:
                raise PdfPasswordError(f"Incorrect password for PDF: {path}")

        if len(doc) == 0:
            raise PdfEmptyError(f"PDF has no pages: {path}")
        return doc
    except Exception:
        doc.close()
        raise


def _assert_not_overwrite(source_path: str, output_path: str) -> None:
    if Path(output_path).resolve() == Path(source_path).resolve():
        raise ValueError("Output path must not equal source path")


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
) -> list[Path]:
    """Extract each inclusive (start,end) page range into a separate PDF.

    `start` / `end` are 0-based page indices.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    src = _open(source_pdf, password=password)
    out_paths: list[Path] = []
    try:
        for start, end in ranges:
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
                if Path(out_path).resolve() == Path(source_pdf).resolve():
                    raise ValueError("Output path must not equal source path")
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
) -> None:
    """Create a new PDF by alternating pages from `pdf_a` and `pdf_b`.

    Extra pages from the longer input are appended after the shorter ends.
    """
    if Path(output_path).resolve() in {Path(pdf_a).resolve(), Path(pdf_b).resolve()}:
        raise ValueError("Output path must not match any input path")

    a = _open(pdf_a, password=password_a)
    b = _open(pdf_b, password=password_b)
    out = fitz.open()
    try:
        i = 0
        j = 0
        a_turn = start_with_a
        while i < len(a) or j < len(b):
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
    finally:
        a.close()
        b.close()
        out.save(output_path)
        out.close()


def reverse_pdf_pages(
    source_pdf: str,
    output_path: str,
    *,
    add_blank_page: bool = False,
    blank_size_from: str = "last",
    password: str | None = None,
) -> None:
    """Reverse page order and optionally append a blank page.

    `blank_size_from` is 'last' or 'first' (in source order).
    """
    _assert_not_overwrite(source_pdf, output_path)

    src = _open(source_pdf, password=password)
    out = fitz.open()
    try:
        for pno in reversed(range(len(src))):
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
) -> None:
    """Normalize every page to an explicit target size.

    `strategy`:
    - 'fit': preserve aspect ratio (may leave empty space)
    - 'fill': stretch to fill (may distort)

    `margins_pt` is either a single float (uniform) or (x_margin, y_margin).
    """
    _assert_not_overwrite(source_pdf, output_path)

    if target_width_pt <= 0 or target_height_pt <= 0:
        raise ValueError("target_* must be positive")

    src = _open(source_pdf, password=password)
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
) -> None:
    """Pack multiple pages onto a grid (row-major order)."""
    _assert_not_overwrite(source_pdf, output_path)
    if rows <= 0 or cols <= 0:
        raise ValueError("rows/cols must be positive")

    src = _open(source_pdf, password=password)
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
) -> None:
    """Simple 2-up "booklet-like" imposition.

    This is a pragmatic arrangement (left/right spread from ends).
    Full duplex fold imposition rules can be added later if needed.
    """
    _assert_not_overwrite(source_pdf, output_path)
    src = _open(source_pdf, password=password)
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
) -> None:
    """Split each page into a grid of cropped tiles (each tile becomes a page)."""
    _assert_not_overwrite(source_pdf, output_path)
    if rows <= 0 or cols <= 0:
        raise ValueError("rows/cols must be positive")

    src = _open(source_pdf, password=password)
    out = fitz.open()
    try:
        first_rect = _page_rect_for_source(src, 0)
        w = float(first_rect.width)
        h = float(first_rect.height)

        tile_w = w / cols
        tile_h = h / rows

        dest = fitz.Rect(0, 0, w, h)
        for pno in range(len(src)):
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
) -> None:
    """Divide each page into 2 tiles and return a 2x page-count output.

    `direction`:
    - 'vertical': split into left/right
    - 'horizontal': split into top/bottom
    """
    _assert_not_overwrite(source_pdf, output_path)
    if direction not in {"vertical", "horizontal"}:
        raise ValueError("direction must be 'vertical' or 'horizontal'")

    src = _open(source_pdf, password=password)
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
) -> None:
    """Combine all pages into one long page (vertical stacking)."""
    _assert_not_overwrite(source_pdf, output_path)
    if axis != "vertical":
        raise ValueError("axis must be 'vertical'")

    src = _open(source_pdf, password=password)
    out = fitz.open()
    try:
        # Standardize to first page width; scale other pages proportionally.
        base_rect = _page_rect_for_source(src, 0)
        out_w = float(base_rect.width)
        scales: list[float] = []
        scaled_heights: list[float] = []
        for pno in range(len(src)):
            rect = _page_rect_for_source(src, pno)
            scale = out_w / float(rect.width)
            scales.append(scale)
            scaled_heights.append(float(rect.height) * scale)

        out_h = float(sum(scaled_heights))
        combined = out.new_page(width=out_w, height=out_h)

        y = 0.0
        for pno, scale, sh in zip(range(len(src)), scales, scaled_heights, strict=True):
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
) -> None:
    """Add (or replace) an embedded file."""
    _assert_not_overwrite(source_pdf, output_path)
    src = _open(source_pdf)
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
) -> None:
    """Remove an embedded file by name."""
    _assert_not_overwrite(source_pdf, output_path)
    src = _open(source_pdf)
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


def metadata_get(path: str, *, password: str | None = None) -> dict[str, Any]:
    """Return PDF /Info metadata (standard fields)."""
    doc = _open(path, password=password)
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
    _assert_not_overwrite(source_pdf, output_path)

    doc = _open(source_pdf, password=password)
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
    _assert_not_overwrite(source_pdf, output_path)

    doc = _open(source_pdf, password=password)
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
    doc = _open(path, password=password)
    try:
        return str(doc.get_xml_metadata() or "")
    finally:
        doc.close()


def page_labels_get(path: str, *, password: str | None = None) -> list[dict]:
    """Return PDF page label definitions."""
    doc = _open(path, password=password)
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
    _assert_not_overwrite(source_pdf, output_path)
    doc = _open(source_pdf, password=password)
    try:
        doc.set_page_labels(labels)
        doc.save(output_path)
    finally:
        doc.close()


def zip_pdfs(paths: Iterable[str | Path], output_zip_path: str | Path) -> Path:
    """Zip PDF files into a new archive."""
    out_zip = Path(output_zip_path)
    sources = [Path(p).resolve() for p in paths]
    if out_zip.resolve() in sources:
        raise ValueError("Output path must not equal any source path")
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


def compare_pdfs_heatmap(
    pdf_a: str,
    pdf_b: str,
    output_heatmap_pdf: str | Path,
    *,
    dpi: int = 120,
    sample_grid: tuple[int, int] = (12, 12),
    byte_diff_threshold: int = 20,
    max_pages: int | None = None,
    password_a: str | None = None,
    password_b: str | None = None,
) -> CompareResult:
    """Compare two PDFs visually via sampled pixel diffs and emit a heatmap PDF.

    No OpenCV; uses MuPDF pixmaps + sampled absolute byte diffs.
    """
    out_path = Path(output_heatmap_pdf)
    if out_path.resolve() in {Path(pdf_a).resolve(), Path(pdf_b).resolve()}:
        raise ValueError("Output path must not match any input path")
    a = _open(pdf_a, password=password_a)
    b = _open(pdf_b, password=password_b)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = fitz.open()
    try:
        cols, rows = sample_grid
        if cols <= 0 or rows <= 0:
            raise ValueError("sample_grid must be positive")

        page_limit = min(len(a), len(b))
        if max_pages is not None:
            page_limit = min(page_limit, max_pages)

        page_diffs: list[float] = []

        # Compare page-by-page; heatmap is one page per compared source page.
        for pno in range(page_limit):
            a_page = a[pno]
            b_page = b[pno]
            a_rect = a_page.rect
            b_rect = b_page.rect

            # Keep dpi consistent by using a's width scaling, then sample overlap.
            scale = float(dpi) / 72.0
            a_target_w = int(round(float(a_rect.width) * scale))
            b_target_w = int(round(float(b_rect.width) * scale))
            # Safety: keep render sizes bounded.
            a_target_w = max(1, min(a_target_w, 2048))
            b_target_w = max(1, min(b_target_w, 2048))
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

            # Sampling point coordinates per grid cell (in each pixmap space).
            xs_a = [int((c + 0.5) * w_a / cols) for c in range(cols)]
            ys_a = [int((r + 0.5) * h_a / rows) for r in range(rows)]
            xs_b = [int((c + 0.5) * w_b / cols) for c in range(cols)]
            ys_b = [int((r + 0.5) * h_b / rows) for r in range(rows)]

            n_a = max(1, pix_a.n)
            n_b = max(1, pix_b.n)
            samples_a = pix_a.samples
            samples_b = pix_b.samples

            diff_intensity: list[list[float]] = [
                [0.0 for _ in range(cols)] for _ in range(rows)
            ]
            cell_diff_count = 0
            total_cells = cols * rows
            for r in range(rows):
                for c in range(cols):
                    # Sample a few points inside the heatmap cell so small glyphs
                    # don't get missed when the cell center hits background only.
                    cell_x0_a = (c * w_a) / cols
                    cell_x1_a = ((c + 1) * w_a) / cols
                    cell_y0_a = (r * h_a) / rows
                    cell_y1_a = ((r + 1) * h_a) / rows
                    cell_x0_b = (c * w_b) / cols
                    cell_x1_b = ((c + 1) * w_b) / cols
                    cell_y0_b = (r * h_b) / rows
                    cell_y1_b = ((r + 1) * h_b) / rows

                    ratios = (0.25, 0.5, 0.75)
                    n = min(n_a, n_b)
                    max_abs = 0
                    for rx in ratios:
                        xa2 = min(w_a - 1, max(0, int(round(cell_x0_a + rx * (cell_x1_a - cell_x0_a)))))
                        xb2 = min(w_b - 1, max(0, int(round(cell_x0_b + rx * (cell_x1_b - cell_x0_b)))))
                        for ry in ratios:
                            ya2 = min(h_a - 1, max(0, int(round(cell_y0_a + ry * (cell_y1_a - cell_y0_a)))))
                            yb2 = min(h_b - 1, max(0, int(round(cell_y0_b + ry * (cell_y1_b - cell_y0_b)))))
                            idx_a2 = (ya2 * w_a + xa2) * n_a
                            idx_b2 = (yb2 * w_b + xb2) * n_b
                            for k in range(n):
                                da = samples_a[idx_a2 + k]
                                db = samples_b[idx_b2 + k]
                                abs_d = abs(int(da) - int(db))
                                if abs_d > max_abs:
                                    max_abs = abs_d

                    is_diff = max_abs >= byte_diff_threshold
                    if is_diff:
                        cell_diff_count += 1

            diff_ratio = cell_diff_count / float(total_cells) if total_cells else 0.0
            page_diffs.append(diff_ratio)

            # Store intensity for diff cells during sampling.
            for r in range(rows):
                for c in range(cols):
                    n = min(n_a, n_b)
                    max_abs = 0
                    cell_x0_a = (c * w_a) / cols
                    cell_x1_a = ((c + 1) * w_a) / cols
                    cell_y0_a = (r * h_a) / rows
                    cell_y1_a = ((r + 1) * h_a) / rows
                    cell_x0_b = (c * w_b) / cols
                    cell_x1_b = ((c + 1) * w_b) / cols
                    cell_y0_b = (r * h_b) / rows
                    cell_y1_b = ((r + 1) * h_b) / rows

                    ratios = (0.25, 0.5, 0.75)
                    for rx in ratios:
                        xa2 = min(w_a - 1, max(0, int(round(cell_x0_a + rx * (cell_x1_a - cell_x0_a)))))
                        xb2 = min(w_b - 1, max(0, int(round(cell_x0_b + rx * (cell_x1_b - cell_x0_b)))))
                        for ry in ratios:
                            ya2 = min(h_a - 1, max(0, int(round(cell_y0_a + ry * (cell_y1_a - cell_y0_a)))))
                            yb2 = min(h_b - 1, max(0, int(round(cell_y0_b + ry * (cell_y1_b - cell_y0_b)))))
                            idx_a2 = (ya2 * w_a + xa2) * n_a
                            idx_b2 = (yb2 * w_b + xb2) * n_b
                            for k in range(n):
                                da = samples_a[idx_a2 + k]
                                db = samples_b[idx_b2 + k]
                                abs_d = abs(int(da) - int(db))
                                if abs_d > max_abs:
                                    max_abs = abs_d
                    if max_abs >= byte_diff_threshold:
                        diff_intensity[r][c] = min(1.0, max_abs / 255.0)

            out_page = out.new_page(
                width=float(a_rect.width), height=float(a_rect.height)
            )
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
                        fill_opacity=0.15 + 0.35 * intensity,
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

