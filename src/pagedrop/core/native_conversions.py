"""Native non-Office import / export conversions (Phase 25).

PyMuPDF first; Pillow (TIFF), openpyxl (XLSX), and pi-heif (HEIC) only for
true gaps. Soft-imports optional codecs via the capability registry — never
import them at module top level.
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
    PI_HEIF,
    PILLOW,
    AbsenceReason,
    probe,
    soft_import,
)
from pagedrop.core.jobs.errors import BackendUnavailableError
from pagedrop.core.jobs.paths import reject_source_overwrite
from pagedrop.core.pdf_tools import _open as _open_pdf
from pagedrop.core.supported_formats import (
    export_format,
    format_capability_available,
    import_format_for_path,
)

# Letter-ish page for Story layouts (PDF points).
_STORY_MEDIABOX = fitz.Rect(0, 0, 612, 792)
_STORY_WHERE = fitz.Rect(36, 36, 576, 756)


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
    {"png", "jpeg", "webp", "tiff", "svg"}
)

_EXPORT_SUFFIX: dict[str, str] = {
    "png": ".png",
    "jpeg": ".jpg",
    "webp": ".webp",
    "tiff": ".tiff",
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

    if spec.id == "heic":
        _heic_to_pdf(source, output)
    elif spec.id in {"markdown", "html"}:
        _story_document_to_pdf(source, output, kind=spec.id)
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

    try:
        story = fitz.Story(html=html_doc)
    except Exception as exc:
        raise NativeConvertError(f"Could not layout {source.name}: {exc}") from exc

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


def _heic_to_pdf(source: Path, output: Path) -> None:
    """Decode HEIC via pi-heif samples → fitz Pixmap page (no Pillow required)."""
    _require_capability(PI_HEIF)
    pi_heif, err = soft_import("pi_heif")
    if pi_heif is None:
        raise BackendUnavailableError(
            PI_HEIF,
            AbsenceReason.CODEC_MISSING,
            f"pi-heif import failed: {err}",
        )

    try:
        if hasattr(pi_heif, "is_supported") and not pi_heif.is_supported(str(source)):
            raise NativeConvertError(f"Unsupported HEIC file: {source.name}")
        heif = pi_heif.open_heif(str(source))
    except NativeConvertError:
        raise
    except Exception as exc:
        raise NativeConvertError(f"Could not decode HEIC {source.name}: {exc}") from exc

    # open_heif may return a sequence; use primary / first image.
    if isinstance(heif, (list, tuple)):
        if not heif:
            raise NativeConvertError(f"HEIC has no images: {source.name}")
        heif = heif[0]

    try:
        width, height = heif.size
        mode = str(getattr(heif, "mode", "RGB"))
        data = bytes(heif.data)
    except Exception as exc:
        raise NativeConvertError(f"Could not read HEIC pixels: {exc}") from exc

    if mode in {"RGBA", "RGBa"}:
        colorspace = fitz.csRGB
        alpha = 1
    elif mode in {"RGB", "BGR"}:
        colorspace = fitz.csRGB
        alpha = 0
    elif mode in {"L", "LA"}:
        colorspace = fitz.csGRAY
        alpha = 1 if mode == "LA" else 0
    else:
        raise NativeConvertError(f"Unsupported HEIC pixel mode: {mode}")

    try:
        pix = fitz.Pixmap(colorspace, width, height, data, alpha)
        if mode == "BGR":
            pix = fitz.Pixmap(fitz.csRGB, pix)
    except Exception as exc:
        raise NativeConvertError(f"Could not build pixmap from HEIC: {exc}") from exc

    doc = fitz.open()
    try:
        page = doc.new_page(width=width, height=height)
        page.insert_image(page.rect, pixmap=pix)
        doc.save(str(output))
    except Exception as exc:
        raise NativeConvertError(f"Could not write PDF: {exc}") from exc
    finally:
        doc.close()


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
) -> list[Path]:
    """Export *source_path* to *format_id*; return written path(s).

    Multi-page image/SVG exports write into *output_path* when it is a
    directory, or beside a file path using ``stem_pNNN.ext`` naming.
    Single-file formats (text/json/xml/cbz/csv/xlsx) write exactly to
    *output_path*.
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
        "tiff": _export_tiff,
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
) -> list[Path]:
    suffix = ".png" if format_id == "png" else ".jpg"
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        out_dir, stem = _output_dir_and_stem(output, multi=True)
        written: list[Path] = []
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for index in indices:
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
) -> list[Path]:
    del jpeg_quality, format_id
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        out_dir, stem = _output_dir_and_stem(output, multi=True)
        written: list[Path] = []
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for index in indices:
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


def _export_tiff(
    source: Path,
    output: Path,
    *,
    pages: Sequence[int] | None,
    dpi: float,
    jpeg_quality: int,
    password: str | None,
    overwrite: bool,
    format_id: str,
) -> list[Path]:
    del jpeg_quality, format_id
    _require_capability(PILLOW)
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        out_dir, stem = _output_dir_and_stem(output, multi=True)
        written: list[Path] = []
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for index in indices:
            path = _page_output_path(
                out_dir, stem, index, ".tiff", overwrite=overwrite
            )
            _assert_outputs_not_source(source, path)
            pix = doc[index].get_pixmap(matrix=matrix, alpha=False)
            # Pillow via MuPDF helper — capability already probed.
            pix.pil_save(str(path))
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
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        out_dir, stem = _output_dir_and_stem(output, multi=True)
        written: list[Path] = []
        for index in indices:
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
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        chunks = [doc[index].get_text("text") for index in indices]
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
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        payload = {
            "source": source.name,
            "pages": [
                {"index": index, "structure": doc[index].get_text("dict")}
                for index in indices
            ],
        }
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
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        root = ET.Element("document", source=source.name)
        for index in indices:
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
) -> list[Path]:
    del jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
            for n, index in enumerate(indices, start=1):
                pix = doc[index].get_pixmap(matrix=matrix, alpha=False)
                zf.writestr(f"{n:03d}.png", pix.tobytes("png"))
        return [path]
    finally:
        doc.close()


def _extract_table_rows(
    doc: fitz.Document,
    indices: Iterable[int],
) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    for index in indices:
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
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        rows = _extract_table_rows(doc, indices)
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
) -> list[Path]:
    del dpi, jpeg_quality, format_id
    path = _single_file_output(source, output, overwrite=overwrite)
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        tables: list[dict[str, object]] = []
        for index in indices:
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
    doc = _open_pdf(str(source), password)
    try:
        indices = _page_indices(doc, pages)
        rows = _extract_table_rows(doc, indices)
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Tables"
        for row in rows:
            sheet.append(["" if cell is None else cell for cell in row])
        workbook.save(str(path))
        return [path]
    finally:
        doc.close()
