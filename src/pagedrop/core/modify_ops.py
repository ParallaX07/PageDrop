"""Document modification helpers (Phase 28).

Crop, watermark, header/footer, page numbers, Bates, bookmarks/TOC, annotation
remove/flatten, blank-page detection, and basic color/scanner effects.

Raster color effects (invert, pixmap background rebuild) may rasterize pages —
callers must surface that vector text can be lost. Blank-page removal is
heuristic; never silent mass-delete without UI confirm.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import fitz

from pagedrop.core.jobs.cancel import CancelToken, check_cancel as _check_cancel
from pagedrop.core.jobs.paths import reject_source_overwrite
from pagedrop.core.pdf_loader import open_pdf

CropMode = Literal["cropbox", "rebuild"]
WatermarkKind = Literal["text", "image"]
MarkPosition = Literal[
    "top-left",
    "top-center",
    "top-right",
    "center-left",
    "center",
    "center-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
]
ColorEffect = Literal["greyscale", "invert", "background"]
AnnotationAction = Literal["remove", "flatten"]

# Near-white threshold for blank-page ink heuristic (0–255 greyscale).
_BLANK_WHITE = 250
_BLANK_MATRIX = fitz.Matrix(0.25, 0.25)

# Lazy helv for watermark metrics / TextWriter — one create (O17-b).
_HELV_FONT: fitz.Font | None = None


def _helv_font() -> fitz.Font:
    """Cached ``fitz.Font("helv")``; construction under ``FITZ_LOCK`` once."""
    global _HELV_FONT
    if _HELV_FONT is not None:
        return _HELV_FONT
    from pagedrop.core.pdf_service import FITZ_LOCK

    with FITZ_LOCK:
        if _HELV_FONT is None:
            _HELV_FONT = fitz.Font("helv")
    return _HELV_FONT


@dataclass(frozen=True)
class BlankPageReport:
    """Heuristic blank-page scan result (0-based page indices)."""

    blank_indices: tuple[int, ...]
    page_count: int
    ink_threshold: float

    @property
    def blank_count(self) -> int:
        return len(self.blank_indices)


@dataclass(frozen=True)
class BookmarkEntry:
    """One outline item: level ≥ 1, title, 1-based page."""

    level: int
    title: str
    page: int  # 1-based

    def to_toc_row(self) -> list:
        return [self.level, self.title, self.page]


def _save(doc: fitz.Document, output_path: str) -> None:
    doc.save(output_path, garbage=3, deflate=True, clean=True, incremental=False)


def _margins_rect(
    page: fitz.Page,
    *,
    left: float,
    right: float,
    top: float,
    bottom: float,
) -> fitz.Rect:
    r = page.rect
    rect = fitz.Rect(r.x0 + left, r.y0 + top, r.x1 - right, r.y1 - bottom)
    if rect.width <= 1 or rect.height <= 1:
        raise ValueError("Crop margins leave an empty page")
    return rect


def crop_pdf(
    source_pdf: str,
    output_path: str,
    *,
    left: float = 0.0,
    right: float = 0.0,
    top: float = 0.0,
    bottom: float = 0.0,
    mode: CropMode = "cropbox",
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Crop every page by margins (points). ``cropbox`` sets CropBox; ``rebuild`` hard-clips."""
    reject_source_overwrite(output_path, source_pdf)
    if min(left, right, top, bottom) < 0:
        raise ValueError("Crop margins must be non-negative")
    src = open_pdf(source_pdf, password=password)
    try:
        if mode == "cropbox":
            for page in src:
                _check_cancel(cancel)
                page.set_cropbox(_margins_rect(page, left=left, right=right, top=top, bottom=bottom))
            _save(src, output_path)
            return

        if mode != "rebuild":
            raise ValueError(f"Unknown crop mode: {mode!r}")

        out = fitz.open()
        try:
            for page in src:
                _check_cancel(cancel)
                clip = _margins_rect(page, left=left, right=right, top=top, bottom=bottom)
                new_page = out.new_page(width=clip.width, height=clip.height)
                new_page.show_pdf_page(new_page.rect, src, page.number, clip=clip)
            _save(out, output_path)
        finally:
            out.close()
    finally:
        src.close()


def _text_box_for_position(
    page: fitz.Page,
    position: MarkPosition,
    *,
    width: float = 200.0,
    height: float = 40.0,
    inset: float = 24.0,
) -> fitz.Rect:
    r = page.rect
    cx = (r.x0 + r.x1) / 2
    if position == "top-left":
        return fitz.Rect(r.x0 + inset, r.y0 + inset, r.x0 + inset + width, r.y0 + inset + height)
    if position == "top-center":
        return fitz.Rect(cx - width / 2, r.y0 + inset, cx + width / 2, r.y0 + inset + height)
    if position == "top-right":
        return fitz.Rect(r.x1 - inset - width, r.y0 + inset, r.x1 - inset, r.y0 + inset + height)
    if position == "center-left":
        cy = (r.y0 + r.y1) / 2
        return fitz.Rect(r.x0 + inset, cy - height / 2, r.x0 + inset + width, cy + height / 2)
    if position == "center-right":
        cy = (r.y0 + r.y1) / 2
        return fitz.Rect(r.x1 - inset - width, cy - height / 2, r.x1 - inset, cy + height / 2)
    if position == "bottom-left":
        return fitz.Rect(r.x0 + inset, r.y1 - inset - height, r.x0 + inset + width, r.y1 - inset)
    if position == "bottom-center":
        return fitz.Rect(cx - width / 2, r.y1 - inset - height, cx + width / 2, r.y1 - inset)
    if position == "bottom-right":
        return fitz.Rect(r.x1 - inset - width, r.y1 - inset - height, r.x1 - inset, r.y1 - inset)
    # center
    return fitz.Rect(cx - width / 2, (r.y0 + r.y1) / 2 - height / 2, cx + width / 2, (r.y0 + r.y1) / 2 + height / 2)


def _page_diagonal(rect: fitz.Rect) -> float:
    return float((rect.width**2 + rect.height**2) ** 0.5)


def _position_anchor(rect: fitz.Rect, position: MarkPosition, *, inset: float = 48.0) -> fitz.Point:
    cx = (rect.x0 + rect.x1) / 2
    cy = (rect.y0 + rect.y1) / 2
    mapping = {
        "top-left": (rect.x0 + inset, rect.y0 + inset),
        "top-center": (cx, rect.y0 + inset),
        "top-right": (rect.x1 - inset, rect.y0 + inset),
        "center-left": (rect.x0 + inset, cy),
        "center": (cx, cy),
        "center-right": (rect.x1 - inset, cy),
        "bottom-left": (rect.x0 + inset, rect.y1 - inset),
        "bottom-center": (cx, rect.y1 - inset),
        "bottom-right": (rect.x1 - inset, rect.y1 - inset),
    }
    if position not in mapping:
        raise ValueError(f"Unknown watermark position: {position!r}")
    x, y = mapping[position]
    return fitz.Point(x, y)


def position_center_fractions(
    page_width: float,
    page_height: float,
    position: MarkPosition,
    *,
    inset: float = 48.0,
) -> tuple[float, float]:
    """Page-relative (0–1) center for a 3×3 snap preset. Used by preview + apply."""
    rect = fitz.Rect(0, 0, page_width, page_height)
    anchor = _position_anchor(rect, position, inset=inset)
    w = max(page_width, 1e-6)
    h = max(page_height, 1e-6)
    return (anchor.x - rect.x0) / w, (anchor.y - rect.y0) / h


def _resolve_anchor(
    rect: fitz.Rect,
    position: MarkPosition,
    *,
    center_x: float | None = None,
    center_y: float | None = None,
) -> fitz.Point:
    """Prefer free placement (*center_x*/*center_y* in 0–1 page fractions); else 9-grid."""
    if center_x is not None and center_y is not None:
        cx = max(0.0, min(1.0, float(center_x)))
        cy = max(0.0, min(1.0, float(center_y)))
        return fitz.Point(rect.x0 + rect.width * cx, rect.y0 + rect.height * cy)
    return _position_anchor(rect, position)


def watermark_text_box(
    text: str,
    *,
    page_width: float,
    page_height: float,
    diagonal_percent: float | None = None,
    fontsize: float | None = None,
) -> tuple[float, float, float]:
    """Unrotated visual (width, height, fontsize) for helv text watermark.

    Shared by apply and live preview so placement/size stay aligned.
    """
    font = _helv_font()
    unit_w = max(font.text_length(text or " ", fontsize=1), 1e-6)
    if diagonal_percent is not None:
        target_w = _page_diagonal(fitz.Rect(0, 0, page_width, page_height)) * (
            diagonal_percent / 100.0
        )
        fs = target_w / unit_w
    else:
        if fontsize is None or fontsize <= 0:
            raise ValueError("fontsize must be positive when diagonal_percent is unset")
        fs = float(fontsize)
    width = font.text_length(text or " ", fontsize=fs)
    height = (font.ascender - font.descender) * fs
    return width, height, fs


def _normalize_page_indices(
    page_count: int,
    pages: Sequence[int] | None,
) -> list[int]:
    if pages is None:
        return list(range(page_count))
    indices = sorted({int(i) for i in pages})
    for i in indices:
        if i < 0 or i >= page_count:
            raise ValueError(f"Page index {i} out of range for {page_count} pages")
    if not indices:
        raise ValueError("No pages selected for watermark")
    return indices


def _flatten_pages(
    doc: fitz.Document,
    page_indices: Sequence[int],
    *,
    dpi: int = 150,
    cancel: CancelToken | None = None,
) -> None:
    """Rasterize selected pages so watermark (and page) text is no longer selectable."""
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    for i in page_indices:
        _check_cancel(cancel)
        page = doc[i]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # Full-page redaction clears content streams; then draw the pixmap back.
        page.add_redact_annot(page.rect)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        page.insert_image(page.rect, pixmap=pix)


def add_text_watermark(
    source_pdf: str,
    output_path: str,
    *,
    text: str,
    opacity: float = 0.35,
    fontsize: float | None = 48.0,
    rotate: float = 45.0,
    color: tuple[float, float, float] = (0.55, 0.55, 0.55),
    position: MarkPosition = "center",
    center_x: float | None = None,
    center_y: float | None = None,
    diagonal_percent: float | None = None,
    pages: Sequence[int] | None = None,
    flatten: bool = False,
    flatten_dpi: int = 150,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Overlay *text* on selected pages.

    Size: if *diagonal_percent* is set (1–100), text width targets that fraction of
    the page diagonal; otherwise *fontsize* is used directly.

    Placement: *center_x*/*center_y* (0–1 page fractions) override *position* when both
    are set. *position* remains the 3×3 snap preset source for those fractions.
    """
    reject_source_overwrite(output_path, source_pdf)
    if not text.strip():
        raise ValueError("Watermark text must be non-empty")
    opacity = max(0.0, min(1.0, opacity))
    if diagonal_percent is not None and not 1.0 <= diagonal_percent <= 100.0:
        raise ValueError("diagonal_percent must be between 1 and 100")
    if diagonal_percent is None and (fontsize is None or fontsize <= 0):
        raise ValueError("fontsize must be positive when diagonal_percent is unset")

    font = _helv_font()
    doc = open_pdf(source_pdf, password=password)
    try:
        targets = _normalize_page_indices(doc.page_count, pages)
        for i in targets:
            _check_cancel(cancel)
            page = doc[i]
            r = page.rect
            text_w, _text_h, fs = watermark_text_box(
                text,
                page_width=r.width,
                page_height=r.height,
                diagonal_percent=diagonal_percent,
                fontsize=fontsize,
            )
            anchor = _resolve_anchor(r, position, center_x=center_x, center_y=center_y)
            # Baseline so glyph visual center sits on *anchor* (matches preview box center).
            baseline_y = anchor.y + (font.ascender + font.descender) / 2 * fs
            pos = fitz.Point(anchor.x - text_w / 2, baseline_y)
            morph = (anchor, fitz.Matrix(1, 1).prerotate(rotate))
            tw = fitz.TextWriter(page.rect, color=color, opacity=opacity)
            tw.append(pos, text, fontsize=fs, font=font)
            tw.write_text(page, morph=morph, overlay=True)
        if flatten:
            _flatten_pages(doc, targets, dpi=flatten_dpi, cancel=cancel)
        _save(doc, output_path)
    finally:
        doc.close()


def _pixmap_with_opacity(image_path: str, opacity: float) -> fitz.Pixmap:
    """Load *image_path* as RGBA pixmap with uniform alpha scaled by *opacity*."""
    pix = fitz.Pixmap(image_path)
    if pix.alpha == 0:
        pix = fitz.Pixmap(pix, 1)
    if pix.n - pix.alpha != 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
        if pix.alpha == 0:
            pix = fitz.Pixmap(pix, 1)
    alpha = int(max(0, min(255, round(255 * opacity))))
    pix.set_alpha(bytearray([alpha] * (pix.width * pix.height)))
    return pix


def add_image_watermark(
    source_pdf: str,
    output_path: str,
    *,
    image_path: str,
    opacity: float = 0.35,
    scale: float | None = 0.5,
    diagonal_percent: float | None = None,
    rotate: float = 0.0,
    position: MarkPosition = "center",
    center_x: float | None = None,
    center_y: float | None = None,
    pages: Sequence[int] | None = None,
    flatten: bool = False,
    flatten_dpi: int = 150,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Place *image_path* on selected pages.

    Size: *diagonal_percent* (preferred) sets image width to that fraction of the
    page diagonal; otherwise *scale* is a fraction of page width/height.

    Placement: *center_x*/*center_y* (0–1) override *position* when both are set.
    """
    reject_source_overwrite(output_path, source_pdf)
    img = Path(image_path)
    if not img.is_file():
        raise FileNotFoundError(f"Watermark image not found: {image_path}")
    opacity = max(0.0, min(1.0, opacity))
    if diagonal_percent is not None and not 1.0 <= diagonal_percent <= 100.0:
        raise ValueError("diagonal_percent must be between 1 and 100")
    if diagonal_percent is None:
        if scale is None:
            raise ValueError("scale or diagonal_percent is required")
        scale = max(0.05, min(1.0, scale))
    wm = _pixmap_with_opacity(str(img), opacity)
    aspect = wm.height / max(wm.width, 1)
    doc = open_pdf(source_pdf, password=password)
    try:
        targets = _normalize_page_indices(doc.page_count, pages)
        for i in targets:
            _check_cancel(cancel)
            page = doc[i]
            r = page.rect
            if diagonal_percent is not None:
                w = _page_diagonal(r) * (diagonal_percent / 100.0)
                h = w * aspect
            else:
                w, h = r.width * float(scale), r.height * float(scale)
            anchor = _resolve_anchor(r, position, center_x=center_x, center_y=center_y)
            box = fitz.Rect(
                anchor.x - w / 2,
                anchor.y - h / 2,
                anchor.x + w / 2,
                anchor.y + h / 2,
            )
            page.insert_image(
                box,
                pixmap=wm,
                keep_proportion=True,
                rotate=int(round(rotate)) % 360,
            )
        if flatten:
            _flatten_pages(doc, targets, dpi=flatten_dpi, cancel=cancel)
        _save(doc, output_path)
    finally:
        doc.close()


def _format_page_token(template: str, page_1based: int, page_count: int) -> str:
    return (
        template.replace("{page}", str(page_1based))
        .replace("{total}", str(page_count))
        .replace("{n}", str(page_1based))
    )


def add_header_footer(
    source_pdf: str,
    output_path: str,
    *,
    header: str = "",
    footer: str = "",
    fontsize: float = 10.0,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Add header and/or footer text. Tokens: ``{page}``, ``{total}``, ``{n}``."""
    reject_source_overwrite(output_path, source_pdf)
    if not header and not footer:
        raise ValueError("Provide header and/or footer text")
    doc = open_pdf(source_pdf, password=password)
    try:
        n = doc.page_count
        for i, page in enumerate(doc):
            _check_cancel(cancel)
            page_no = i + 1
            if header:
                box = _text_box_for_position(page, "top-center", width=page.rect.width - 48, height=28)
                page.insert_textbox(
                    box,
                    _format_page_token(header, page_no, n),
                    fontsize=fontsize,
                    align=fitz.TEXT_ALIGN_CENTER,
                    overlay=True,
                )
            if footer:
                box = _text_box_for_position(page, "bottom-center", width=page.rect.width - 48, height=28)
                page.insert_textbox(
                    box,
                    _format_page_token(footer, page_no, n),
                    fontsize=fontsize,
                    align=fitz.TEXT_ALIGN_CENTER,
                    overlay=True,
                )
        _save(doc, output_path)
    finally:
        doc.close()


def add_page_numbers(
    source_pdf: str,
    output_path: str,
    *,
    template: str = "{page}",
    position: MarkPosition = "bottom-center",
    start: int = 1,
    fontsize: float = 10.0,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Stamp page numbers. *start* is the number shown on the first page."""
    reject_source_overwrite(output_path, source_pdf)
    if start < 0:
        raise ValueError("start must be >= 0")
    doc = open_pdf(source_pdf, password=password)
    try:
        n = doc.page_count
        for i, page in enumerate(doc):
            _check_cancel(cancel)
            shown = start + i
            text = _format_page_token(template, shown, n)
            box = _text_box_for_position(page, position, width=160, height=24)
            align = fitz.TEXT_ALIGN_CENTER
            if position.endswith("left"):
                align = fitz.TEXT_ALIGN_LEFT
            elif position.endswith("right"):
                align = fitz.TEXT_ALIGN_RIGHT
            page.insert_textbox(box, text, fontsize=fontsize, align=align, overlay=True)
        _save(doc, output_path)
    finally:
        doc.close()


def format_bates(prefix: str, number: int, digits: int) -> str:
    return f"{prefix}{number:0{digits}d}"


def add_bates_numbers(
    source_pdf: str,
    output_path: str,
    *,
    prefix: str = "",
    start: int = 1,
    digits: int = 6,
    position: MarkPosition = "bottom-right",
    fontsize: float = 9.0,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> int:
    """Stamp Bates numbers; return the next number after the last page."""
    reject_source_overwrite(output_path, source_pdf)
    if digits < 1 or digits > 12:
        raise ValueError("digits must be between 1 and 12")
    if start < 0:
        raise ValueError("start must be >= 0")
    doc = open_pdf(source_pdf, password=password)
    try:
        n = start
        for page in doc:
            _check_cancel(cancel)
            text = format_bates(prefix, n, digits)
            box = _text_box_for_position(page, position, width=180, height=22)
            align = fitz.TEXT_ALIGN_RIGHT if position.endswith("right") else fitz.TEXT_ALIGN_LEFT
            if "center" in position:
                align = fitz.TEXT_ALIGN_CENTER
            page.insert_textbox(box, text, fontsize=fontsize, align=align, overlay=True)
            n += 1
        _save(doc, output_path)
        return n
    finally:
        doc.close()


def add_bates_across_files(
    sources: Sequence[str],
    output_dir: str | Path,
    *,
    prefix: str = "",
    start: int = 1,
    digits: int = 6,
    position: MarkPosition = "bottom-right",
    fontsize: float = 9.0,
    suffix: str = "_bates",
    passwords: dict[str, str] | None = None,
    cancel: CancelToken | None = None,
) -> list[Path]:
    """Bates-stamp each PDF in order; numbering continues across files."""
    if not sources:
        raise ValueError("At least one source PDF is required")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    passwords = passwords or {}
    next_num = start
    written: list[Path] = []
    for source in sources:
        _check_cancel(cancel)
        src_path = Path(source)
        dest = out_dir / f"{src_path.stem}{suffix}{src_path.suffix}"
        reject_source_overwrite(dest, source)
        next_num = add_bates_numbers(
            source,
            str(dest),
            prefix=prefix,
            start=next_num,
            digits=digits,
            position=position,
            fontsize=fontsize,
            password=passwords.get(source),
            cancel=cancel,
        )
        written.append(dest)
    return written


def get_bookmarks(source_pdf: str, *, password: str | None = None) -> list[BookmarkEntry]:
    doc = open_pdf(source_pdf, password=password)
    try:
        toc = doc.get_toc(simple=True) or []
        return [BookmarkEntry(level=int(row[0]), title=str(row[1]), page=int(row[2])) for row in toc]
    finally:
        doc.close()


def set_bookmarks(
    source_pdf: str,
    output_path: str,
    bookmarks: Sequence[BookmarkEntry | Sequence],
    *,
    password: str | None = None,
) -> None:
    """Replace document outline. Each entry is BookmarkEntry or [level, title, page]."""
    reject_source_overwrite(output_path, source_pdf)
    toc: list[list] = []
    for item in bookmarks:
        if isinstance(item, BookmarkEntry):
            toc.append(item.to_toc_row())
        else:
            level, title, page = item[0], item[1], item[2]
            toc.append([int(level), str(title), int(page)])
    doc = open_pdf(source_pdf, password=password)
    try:
        doc.set_toc(toc)
        _save(doc, output_path)
    finally:
        doc.close()


def bookmarks_one_per_page(
    source_pdf: str,
    output_path: str,
    *,
    title_template: str = "Page {page}",
    password: str | None = None,
) -> None:
    """Replace outline with one level-1 bookmark per page."""
    doc = open_pdf(source_pdf, password=password)
    try:
        entries = [
            BookmarkEntry(1, title_template.replace("{page}", str(i + 1)), i + 1)
            for i in range(doc.page_count)
        ]
    finally:
        doc.close()
    set_bookmarks(source_pdf, output_path, entries, password=password)

def generate_toc_page(
    source_pdf: str,
    output_path: str,
    *,
    title: str = "Table of contents",
    password: str | None = None,
) -> None:
    """Insert a TOC page at the front with internal links to existing bookmarks.

    Bookmark page numbers are shifted by +1 after insertion so links stay valid.
    """
    reject_source_overwrite(output_path, source_pdf)
    doc = open_pdf(source_pdf, password=password)
    try:
        toc = doc.get_toc(simple=True) or []
        if not toc:
            raise ValueError("Document has no bookmarks to build a TOC from")

        # Insert blank first page sized like page 0.
        first = doc[0]
        doc.new_page(pno=0, width=first.rect.width, height=first.rect.height)
        toc_page = doc[0]
        y = 72.0
        toc_page.insert_text((72, y), title, fontsize=18)
        y += 36.0
        # Shift existing outline pages (+1) and rewrite after drawing.
        new_toc: list[list] = [[1, title, 1]]
        for level, label, page in toc:
            page_i = int(page)  # still pre-shift in source coords
            link_page = page_i + 1  # after insert
            text = f"{'  ' * (int(level) - 1)}{label} ………… {page_i}"
            toc_page.insert_text((72, y), text, fontsize=11)
            rect = fitz.Rect(72, y - 12, toc_page.rect.x1 - 72, y + 4)
            toc_page.insert_link(
                {
                    "kind": fitz.LINK_GOTO,
                    "from": rect,
                    "page": link_page - 1,  # 0-based for link
                    "to": fitz.Point(0, 0),
                }
            )
            new_toc.append([int(level), str(label), link_page])
            y += 18.0
            if y > toc_page.rect.y1 - 72:
                break  # single TOC page; overflow truncated

        doc.set_toc(new_toc)
        _save(doc, output_path)
    finally:
        doc.close()


def remove_or_flatten_annotations(
    source_pdf: str,
    output_path: str,
    *,
    action: AnnotationAction = "remove",
    include_widgets: bool = True,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Remove annotations, or bake (flatten) annots / form appearances into content."""
    reject_source_overwrite(output_path, source_pdf)
    doc = open_pdf(source_pdf, password=password)
    try:
        if action == "flatten":
            _check_cancel(cancel)
            doc.bake(annots=True, widgets=include_widgets)
        elif action == "remove":
            for page in doc:
                _check_cancel(cancel)
                for annot in list(page.annots() or []):
                    page.delete_annot(annot)
                if include_widgets:
                    for widget in list(page.widgets() or []):
                        page.delete_widget(widget)
        else:
            raise ValueError(f"Unknown annotation action: {action!r}")
        _save(doc, output_path)
    finally:
        doc.close()


def page_ink_coverage(page: fitz.Page) -> float:
    """Fraction of non-near-white greyscale pixels (0 = blank, 1 = fully inked)."""
    pix = page.get_pixmap(matrix=_BLANK_MATRIX, colorspace=fitz.csGRAY, alpha=False)
    samples = pix.samples
    if not samples:
        return 0.0
    inked = sum(1 for b in samples if b < _BLANK_WHITE)
    return inked / len(samples)


def page_looks_blank(page: fitz.Page, *, ink_threshold: float = 0.01) -> bool:
    """Heuristic: no extractable text/images and ink coverage below *ink_threshold*."""
    if page.get_text("text").strip():
        return False
    if page.get_images():
        return False
    return page_ink_coverage(page) < ink_threshold


def detect_blank_pages(
    source_pdf: str,
    *,
    ink_threshold: float = 0.01,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> BlankPageReport:
    """Return pages that look blank (no text/images + low ink coverage)."""
    if not 0.0 <= ink_threshold <= 1.0:
        raise ValueError("ink_threshold must be between 0 and 1")
    doc = open_pdf(source_pdf, password=password)
    try:
        blanks: list[int] = []
        for i, page in enumerate(doc):
            _check_cancel(cancel)
            if page_looks_blank(page, ink_threshold=ink_threshold):
                blanks.append(i)
        return BlankPageReport(
            blank_indices=tuple(blanks),
            page_count=doc.page_count,
            ink_threshold=ink_threshold,
        )
    finally:
        doc.close()


def remove_blank_pages(
    source_pdf: str,
    output_path: str,
    *,
    ink_threshold: float = 0.01,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> BlankPageReport:
    """Write a copy with heuristically blank pages removed.

    Callers must confirm with the user before invoking — this never prompts.
    """
    reject_source_overwrite(output_path, source_pdf)
    report = detect_blank_pages(
        source_pdf,
        ink_threshold=ink_threshold,
        password=password,
        cancel=cancel,
    )
    if report.blank_count == 0:
        # Still rewrite so callers get a distinct output path.
        doc = open_pdf(source_pdf, password=password)
        try:
            _save(doc, output_path)
        finally:
            doc.close()
        return report
    if report.blank_count >= report.page_count:
        raise ValueError("All pages look blank; refusing to write an empty PDF")

    doc = open_pdf(source_pdf, password=password)
    try:
        # Delete from the end so indices stay valid.
        for idx in sorted(report.blank_indices, reverse=True):
            _check_cancel(cancel)
            doc.delete_page(idx)
        _save(doc, output_path)
        return report
    finally:
        doc.close()


def apply_color_effect(
    source_pdf: str,
    output_path: str,
    *,
    effect: ColorEffect,
    background_rgb: tuple[float, float, float] = (0.95, 0.95, 0.9),
    dpi: int = 150,
    password: str | None = None,
    cancel: CancelToken | None = None,
) -> None:
    """Apply greyscale (vector-safe), invert (rasterizes), or background tint.

    ``greyscale`` uses ``Page.recolor(1)`` and keeps vectors.
    ``invert`` rebuilds each page from an inverted pixmap (vector text lost).
    ``background`` draws a filled rect under content (vector-safe).
    """
    reject_source_overwrite(output_path, source_pdf)
    if dpi < 36 or dpi > 600:
        raise ValueError("dpi must be between 36 and 600")
    doc = open_pdf(source_pdf, password=password)
    try:
        if effect == "greyscale":
            for page in doc:
                _check_cancel(cancel)
                page.recolor(1)
            _save(doc, output_path)
            return

        if effect == "background":
            r, g, b = background_rgb
            for page in doc:
                _check_cancel(cancel)
                shape = page.new_shape()
                shape.draw_rect(page.rect)
                shape.finish(color=None, fill=(r, g, b), fill_opacity=1.0)
                shape.commit(overlay=False)
            _save(doc, output_path)
            return

        if effect != "invert":
            raise ValueError(f"Unknown color effect: {effect!r}")

        # Raster invert: rebuild each page from pixmap (documented vector loss).
        out = fitz.open()
        try:
            mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            for page in doc:
                _check_cancel(cancel)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                pix.invert_irect(pix.irect)
                new_page = out.new_page(width=page.rect.width, height=page.rect.height)
                new_page.insert_image(new_page.rect, pixmap=pix)
            _save(out, output_path)
        finally:
            out.close()
    finally:
        doc.close()


# Documented warning for UI copy when raster effects are selected.
RASTER_EFFECT_WARNING = (
    "This effect rasterizes pages. Vector text and sharp lines may be lost."
)
BLANK_PAGE_HEURISTIC_HINT = (
    "Blank detection skips pages with extractable text or images, then checks "
    "near-white coverage. Review the count before removing pages."
)
