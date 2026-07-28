"""Native non-Office import / export conversions (Phase 25).

PyMuPDF first; Pillow (WebP fallback) and openpyxl (XLSX) only for true gaps.
Soft-imports optional codecs via the capability registry — never import them
at module top level.
"""

from __future__ import annotations

import csv
import html
import json
import re
import zipfile
from pathlib import Path
from typing import Iterable, Sequence
from xml.etree import ElementTree as ET

import fitz

from pagedrop.core.capabilities import (
    OPENPYXL,
    PILLOW,
    AbsenceReason,
    probe,
    soft_import,
)
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import BackendUnavailableError
from pagedrop.core.jobs.paths import reject_source_overwrite
from pagedrop.core.pdf_loader import open_pdf
from pagedrop.core.supported_formats import (
    export_format,
    format_capability_available,
    import_format_for_path,
)


def _check_cancel(cancel: CancelToken | None) -> None:
    if cancel is not None:
        cancel.check()

# Letter-ish page for Story layouts (PDF points).
_STORY_MEDIABOX = fitz.Rect(0, 0, 612, 792)
_STORY_WHERE = fitz.Rect(36, 36, 576, 756)

# naive HTML table layout — Story struggles past ~5k×64 cells; raise
# caps or stream page-chunks if huge sheet → PDF becomes a real workload.
_SHEET_MAX_ROWS = 5000
_SHEET_MAX_COLS = 64


class NativeConvertError(Exception):
    """Raised when a native import/export conversion fails."""


def _require_capability(capability_id: str) -> None:
    status = probe(capability_id)
    if status.available:
        return
    reason = status.reason or AbsenceReason.CODEC_MISSING
    raise BackendUnavailableError(capability_id, reason, status.detail)


def _assert_outputs_not_source(source: str | Path, *outputs: str | Path) -> None:
    for output in outputs:
        reject_source_overwrite(output, source)


def _page_indices(doc: fitz.Document, pages: Sequence[int] | None) -> list[int]:
    count = doc.page_count
    if pages is None:
        return list(range(count))
    indices: list[int] = []
    for index in pages:
        if index < 0 or index >= count:
            raise NativeConvertError(
                f"Page index {index} out of range (0–{count - 1})"
            )
        indices.append(int(index))
    if not indices:
        raise NativeConvertError("No pages selected")
    return indices


# Raster / SVG exports write one file per page.
MULTI_PAGE_EXPORT_IDS: frozenset[str] = frozenset(
    {"png", "jpeg", "webp", "svg"}
)

_EXPORT_SUFFIX: dict[str, str] = {
    "png": ".png",
    "jpeg": ".jpg",
    "webp": ".webp",
    "svg": ".svg",
    "text": ".txt",
    "json": ".json",
    "xml": ".xml",
    "cbz": ".cbz",
    "csv": ".csv",
    "tables_json": ".json",
    "xlsx": ".xlsx",
}


def collision_safe_path(path: Path) -> Path:
    """Return *path*, or ``stem_2.ext`` / ``stem_3.ext`` … if it already exists."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _collision_safe_path(path: Path) -> Path:
    return collision_safe_path(path)


def predicted_export_paths(
    output_path: str | Path,
    *,
    format_id: str,
    pages: Sequence[int],
) -> list[Path]:
    """Paths a multi/single-page export would write for *pages* (0-based)."""
    output = Path(output_path)
    suffix = _EXPORT_SUFFIX[format_id]
    if format_id not in MULTI_PAGE_EXPORT_IDS:
        return [output if output.suffix else output.with_suffix(suffix)]
    out_dir, stem = _output_dir_and_stem(output, multi=True)
    return [out_dir / f"{stem}_p{index + 1:03d}{suffix}" for index in pages]


# --- Import → PDF -----------------------------------------------------------


def import_to_pdf(
    source_path: str | Path,
    output_path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Convert a registered non-image document to a new PDF path."""
    source = Path(source_path)
    output = Path(output_path)
    spec = import_format_for_path(source)
    if spec is None:
        raise NativeConvertError(f"Unsupported import format: {source.suffix}")
    if not format_capability_available(spec):
        assert spec.capability_id is not None
        _require_capability(spec.capability_id)

    _assert_outputs_not_source(source, output)
    if output.exists() and not overwrite:
        raise NativeConvertError(f"Output already exists: {output}")

    if spec.id in {"markdown", "html"}:
        _story_document_to_pdf(source, output, kind=spec.id)
    elif spec.id in {"csv", "xlsx"}:
        _spreadsheet_to_pdf(source, output, kind=spec.id)
    else:
        _fitz_document_to_pdf(source, output)
    return output


def _fitz_document_to_pdf(source: Path, output: Path) -> None:
    try:
        doc = fitz.open(source)
    except Exception as exc:
        raise NativeConvertError(f"Could not open {source.name}: {exc}") from exc
    try:
        if doc.page_count == 0:
            raise NativeConvertError(f"{source.name} has no pages")
        pdf_bytes = doc.convert_to_pdf()
    except NativeConvertError:
        raise
    except Exception as exc:
        raise NativeConvertError(f"Could not convert {source.name}: {exc}") from exc
    finally:
        doc.close()

    out = fitz.open("pdf", pdf_bytes)
    try:
        out.save(str(output))
    except Exception as exc:
        raise NativeConvertError(f"Could not write PDF: {exc}") from exc
    finally:
        out.close()


def _story_document_to_pdf(source: Path, output: Path, *, kind: str) -> None:
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise NativeConvertError(f"Could not read {source.name}: {exc}") from exc

    if kind == "markdown":
        html_doc = _markdown_to_controlled_html(text)
    else:
        html_doc = _controlled_html_document(text)

    _write_story_html_pdf(html_doc, output, label=source.name)


def _spreadsheet_to_pdf(source: Path, output: Path, *, kind: str) -> None:
    if kind == "csv":
        rows = _read_csv_rows(source)
    elif kind == "xlsx":
        rows = _read_xlsx_rows(source)
    else:
        raise NativeConvertError(f"Unsupported spreadsheet kind: {kind}")
    html_doc = _rows_to_html_table(rows, title=source.name)
    _write_story_html_pdf(html_doc, output, label=source.name)


def _write_story_html_pdf(html_doc: str, output: Path, *, label: str) -> None:
    try:
        story = fitz.Story(html=html_doc)
    except Exception as exc:
        raise NativeConvertError(f"Could not layout {label}: {exc}") from exc

    try:
        writer = fitz.DocumentWriter(str(output))
        more = True
        while more:
            device = writer.begin_page(_STORY_MEDIABOX)
            more, _ = story.place(_STORY_WHERE)
            story.draw(device)
            writer.end_page()
        writer.close()
    except Exception as exc:
        raise NativeConvertError(f"Could not write PDF: {exc}") from exc


def _read_csv_rows(source: Path) -> list[list[str]]:
    try:
        raw = source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raw = source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise NativeConvertError(f"Could not read {source.name}: {exc}") from exc

    reader = csv.reader(raw.splitlines())
    rows: list[list[str]] = []
    for row in reader:
        if len(rows) >= _SHEET_MAX_ROWS:
            raise NativeConvertError(
                f"{source.name} has more than {_SHEET_MAX_ROWS} rows "
                "(native CSV→PDF cap; use Office to PDF for large sheets)"
            )
        if len(row) > _SHEET_MAX_COLS:
            raise NativeConvertError(
                f"{source.name} has more than {_SHEET_MAX_COLS} columns "
                "(native CSV→PDF cap; use Office to PDF for wide sheets)"
            )
        rows.append([str(cell) for cell in row])
    if not rows:
        raise NativeConvertError(f"{source.name} is empty")
    return rows


def _read_xlsx_rows(source: Path) -> list[list[str]]:
    _require_capability(OPENPYXL)
    openpyxl, err = soft_import("openpyxl")
    if openpyxl is None:
        raise BackendUnavailableError(
            OPENPYXL,
            AbsenceReason.CODEC_MISSING,
            f"openpyxl import failed: {err}",
        )
    try:
        workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    except Exception as exc:
        raise NativeConvertError(f"Could not open {source.name}: {exc}") from exc
    try:
        sheet = workbook.active
        rows: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            if len(rows) >= _SHEET_MAX_ROWS:
                raise NativeConvertError(
                    f"{source.name} has more than {_SHEET_MAX_ROWS} rows "
                    "(native XLSX→PDF cap; use Office to PDF for large sheets)"
                )
            cells = [("" if cell is None else str(cell)) for cell in row]
            if len(cells) > _SHEET_MAX_COLS:
                raise NativeConvertError(
                    f"{source.name} has more than {_SHEET_MAX_COLS} columns "
                    "(native XLSX→PDF cap; use Office to PDF for wide sheets)"
                )
            # Drop trailing all-empty rows later; keep sparse interior cells.
            rows.append(cells)
        while rows and all(not cell for cell in rows[-1]):
            rows.pop()
        if not rows:
            raise NativeConvertError(f"{source.name} has no cells")
        return rows
    finally:
        workbook.close()


def _rows_to_html_table(rows: list[list[str]], *, title: str) -> str:
    width = max((len(row) for row in rows), default=0)
    body_rows: list[str] = []
    for row in rows:
        padded = row + [""] * (width - len(row))
        cells = "".join(f"<td>{html.escape(cell)}</td>" for cell in padded)
        body_rows.append(f"<tr>{cells}</tr>")
    table = (
        f"<h1>{html.escape(title)}</h1>"
        '<table border="1" cellpadding="4" cellspacing="0">'
        f"{''.join(body_rows)}</table>"
    )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        f"<body>{table}</body></html>"
    )


def _controlled_html_document(raw: str) -> str:
    """Wrap loose fragments; pass through full HTML documents unchanged."""
    stripped = raw.strip()
    lower = stripped[:200].lower()
    if "<html" in lower or "<!doctype" in lower:
        return stripped
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        f"<body>{stripped}</body></html>"
    )


_INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_INLINE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_INLINE_CODE = re.compile(r"`([^`]+)`")


def _markdown_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = _INLINE_BOLD.sub(r"<b>\1</b>", escaped)
    escaped = _INLINE_ITALIC.sub(r"<i>\1</i>", escaped)
    escaped = _INLINE_CODE.sub(r"<code>\1</code>", escaped)
    return escaped


def _markdown_to_controlled_html(md: str) -> str:
    """Minimal Markdown → HTML for Story (headers, lists, paragraphs)."""
    parts: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            parts.append(f"<p>{_markdown_inline(' '.join(paragraph))}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            items = "".join(f"<li>{_markdown_inline(item)}</li>" for item in list_items)
            parts.append(f"<ul>{items}</ul>")
            list_items = []

    for line in md.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h3>{_markdown_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h2>{_markdown_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h1>{_markdown_inline(stripped[2:])}</h1>")
        elif stripped.startswith(("- ", "* ")):
            flush_paragraph()
            list_items.append(stripped[2:])
        else:
            flush_list()
            paragraph.append(stripped)
    flush_paragraph()
    flush_list()
    body = "".join(parts) or "<p></p>"
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        f"<body>{body}</body></html>"
    )


# --- Export from PDF --------------------------------------------------------


def export_pdf(
    source_path: str | Path,
    output_path: str | Path,
    *,
    format_id: str,
    pages: Sequence[int] | None = None,
    dpi: float = 144,
    jpeg_quality: int = 90,
    password: str | None = None,
    overwrite: bool = False,
    cancel: CancelToken | None = None,
) -> list[Path]:
    """Export *source_path* to *format_id*; return written path(s).

    Multi-page image/SVG exports write into *output_path* when it is a
    directory, or beside a file path using ``stem_pNNN.ext`` naming.
    Single-file formats (text/json/xml/cbz/csv/xlsx) write exactly to
    *output_path*. Cooperative *cancel* is checked between pages; partial
    staged files are the caller's responsibility.
    """
    source = Path(source_path)
    output = Path(output_path)
    spec = export_format(format_id)
    if not format_capability_available(spec):
        assert spec.capability_id is not None
        _require_capability(spec.capability_id)

    writers = {
        "png": _export_raster,
        "jpeg": _export_raster,
        "webp": _export_webp,
        "svg": _export_svg,
        "text": _export_text,
        "json": _export_json,
        "xml": _export_xml,
        "cbz": _export_cbz,
        "csv": _export_tables_csv,
        "tables_json": _export_tables_json,
        "xlsx": _export_tables_xlsx,
    }
    writer = writers[spec.id]
    return writer(
        source,
        output,
        pages=pages,
        dpi=dpi,
        jpeg_quality=jpeg_quality,
        password=password,
        overwrite=overwrite,
        format_id=spec.id,
        cancel=cancel,
    )


def _output_dir_and_stem(output: Path, *, multi: bool) -> tuple[Path, str]:
    if multi and (output.suffix == "" or output.is_dir()):
        out_dir = output
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir, "page"
    out_dir = output.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir, output.stem


def _page_output_path(
    out_dir: Path,
    stem: str,
    page_index: int,
    suffix: str,
    *,
    overwrite: bool,
) -> Path:
    path = out_dir / f"{stem}_p{page_index + 1:03d}{suffix}"
    if path.exists() and not overwrite:
        path = _collision_safe_path(path)
    return path


def _export_raster(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
    cancel: CancelToken | None = None,
) -> list[Path]:
    suffix = ".png" if format_id == "png" else ".jpg"
    doc = open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        out_dir, stem = _output_dir_and_stem(output, multi=True)
        written: list[Path] = []
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for index in indices:
            _check_cancel(cancel)
            path = _page_output_path(
                out_dir, stem, index, suffix, overwrite=overwrite
            )
            _assert_outputs_not_source(source, path)
            pix = doc[index].get_pixmap(matrix=matrix, alpha=False)
            if format_id == "png":
                pix.save(str(path))
            else:
                pix.save(str(path), jpg_quality=jpeg_quality)
            written.append(path)
        return written
    finally:
        doc.close()


def _write_webp_bytes(png_bytes: bytes, path: Path) -> None:
    """Prefer Qt QImageWriter; fall back to Pillow when Qt cannot write WebP."""
    qtgui, _ = soft_import("PyQt6.QtGui")
    if qtgui is not None:
        image = qtgui.QImage.fromData(png_bytes)
        if not image.isNull():
            writer = qtgui.QImageWriter(str(path), b"webp")
            if writer.canWrite() and writer.write(image):
                return

    _require_capability(PILLOW)
    pil, err = soft_import("PIL.Image")
    if pil is None:
        raise BackendUnavailableError(
            PILLOW,
            AbsenceReason.CODEC_MISSING,
            f"Pillow import failed: {err}",
        )
    from io import BytesIO

    image = pil.Image.open(BytesIO(png_bytes))
    image.save(str(path), format="WEBP")


def _export_webp(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
    cancel: CancelToken | None = None,
) -> list[Path]:
    del jpeg_quality, format_id
    doc = open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        out_dir, stem = _output_dir_and_stem(output, multi=True)
        written: list[Path] = []
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for index in indices:
            _check_cancel(cancel)
            path = _page_output_path(
                out_dir, stem, index, ".webp", overwrite=overwrite
            )
            _assert_outputs_not_source(source, path)
            pix = doc[index].get_pixmap(matrix=matrix, alpha=False)
            _write_webp_bytes(pix.tobytes("png"), path)
            written.append(path)
        return written
    finally:
        doc.close()


def _export_svg(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
    cancel: CancelToken | None = None,
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    doc = open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        out_dir, stem = _output_dir_and_stem(output, multi=True)
        written: list[Path] = []
        for index in indices:
            _check_cancel(cancel)
            path = _page_output_path(
                out_dir, stem, index, ".svg", overwrite=overwrite
            )
            _assert_outputs_not_source(source, path)
            path.write_text(doc[index].get_svg_image(), encoding="utf-8")
            written.append(path)
        return written
    finally:
        doc.close()


def _single_file_output(source: Path, output: Path, *, overwrite: bool) -> Path:
    _assert_outputs_not_source(source, output)
    if output.exists() and not overwrite:
        return _collision_safe_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _export_text(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
    cancel: CancelToken | None = None,
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        chunks: list[str] = []
        for index in indices:
            _check_cancel(cancel)
            chunks.append(doc[index].get_text("text"))
        path.write_text("\n".join(chunks), encoding="utf-8")
        return [path]
    finally:
        doc.close()


def _export_json(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
    cancel: CancelToken | None = None,
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        pages_payload: list[dict[str, object]] = []
        for index in indices:
            _check_cancel(cancel)
            pages_payload.append(
                {"index": index, "structure": doc[index].get_text("dict")}
            )
        payload = {"source": source.name, "pages": pages_payload}
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return [path]
    finally:
        doc.close()


def _export_xml(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
    cancel: CancelToken | None = None,
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        root = ET.Element("document", source=source.name)
        for index in indices:
            _check_cancel(cancel)
            page_el = ET.SubElement(root, "page", index=str(index))
            # MuPDF XML is a fragment; wrap as text to keep structure extractable.
            page_el.text = doc[index].get_text("xml")
        tree = ET.ElementTree(root)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        return [path]
    finally:
        doc.close()


def _export_cbz(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
    cancel: CancelToken | None = None,
) -> list[Path]:
    del jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
            for n, index in enumerate(indices, start=1):
                _check_cancel(cancel)
                pix = doc[index].get_pixmap(matrix=matrix, alpha=False)
                zf.writestr(f"{n:03d}.png", pix.tobytes("png"))
        return [path]
    finally:
        doc.close()


def _extract_table_rows(
    doc: fitz.Document,
    indices: Iterable[int],
    cancel: CancelToken | None = None,
) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    for index in indices:
        _check_cancel(cancel)
        finder = doc[index].find_tables()
        for table in finder.tables:
            for row in table.extract():
                rows.append(list(row))
    return rows


def _export_tables_csv(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
    cancel: CancelToken | None = None,
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        rows = _extract_table_rows(doc, indices, cancel=cancel)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            for row in rows:
                writer.writerow(["" if cell is None else cell for cell in row])
        return [path]
    finally:
        doc.close()


def _export_tables_json(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
    cancel: CancelToken | None = None,
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        tables: list[dict[str, object]] = []
        for index in indices:
            _check_cancel(cancel)
            finder = doc[index].find_tables()
            for t_index, table in enumerate(finder.tables):
                rows = [list(row) for row in table.extract()]
                tables.append(
                    {
                        "page": index,
                        "table": t_index,
                        "rows": [
                            ["" if cell is None else cell for cell in row]
                            for row in rows
                        ],
                    }
                )
        payload = {"source": source.name, "tables": tables}
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return [path]
    finally:
        doc.close()


def _export_tables_xlsx(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
    cancel: CancelToken | None = None,
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    _require_capability(OPENPYXL)
    openpyxl, err = soft_import("openpyxl")
    if openpyxl is None:
        raise BackendUnavailableError(
            OPENPYXL,
            AbsenceReason.CODEC_MISSING,
            f"openpyxl import failed: {err}",
        )

    path = _single_file_output(source, output, overwrite=overwrite)
    doc = open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        rows = _extract_table_rows(doc, indices, cancel=cancel)
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Tables"
        for row in rows:
            sheet.append(["" if cell is None else cell for cell in row])
        workbook.save(str(path))
        return [path]
    finally:
        doc.close()
