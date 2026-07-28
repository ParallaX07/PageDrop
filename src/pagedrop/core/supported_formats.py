from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from pagedrop.core.capabilities import OPENPYXL, probe

SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".bmp",
        ".gif",
        ".jfif",
        ".jpe",
        ".jpeg",
        ".jpg",
        ".pbm",
        ".pgm",
        ".png",
        ".pnm",
        ".ppm",
        ".tif",
        ".tiff",
        ".webp",
    }
)


@dataclass(frozen=True)
class FormatSpec:
    """One import or export format registered for native conversions."""

    id: str
    extensions: frozenset[str]
    label: str
    capability_id: str | None = None


# Non-image → PDF (Tools Convert to PDF). Create PDF stays images-only (Phase 19).
IMPORT_TO_PDF_FORMATS: tuple[FormatSpec, ...] = (
    FormatSpec("svg", frozenset({".svg"}), "SVG"),
    FormatSpec("xps", frozenset({".xps", ".oxps"}), "XPS"),
    FormatSpec("epub", frozenset({".epub"}), "EPUB"),
    FormatSpec("mobi", frozenset({".mobi"}), "MOBI"),
    FormatSpec("fb2", frozenset({".fb2"}), "FB2"),
    FormatSpec("cbz", frozenset({".cbz"}), "CBZ"),
    FormatSpec("text", frozenset({".txt"}), "Text"),
    FormatSpec("markdown", frozenset({".md", ".markdown"}), "Markdown"),
    FormatSpec("html", frozenset({".html", ".htm"}), "HTML"),
)

# PDF → other (Tools Export from PDF).
EXPORT_FROM_PDF_FORMATS: tuple[FormatSpec, ...] = (
    FormatSpec("png", frozenset({".png"}), "PNG"),
    FormatSpec("jpeg", frozenset({".jpg", ".jpeg"}), "JPEG"),
    FormatSpec("webp", frozenset({".webp"}), "WebP"),
    FormatSpec("svg", frozenset({".svg"}), "SVG"),
    FormatSpec("text", frozenset({".txt"}), "Text"),
    FormatSpec("json", frozenset({".json"}), "JSON structure"),
    FormatSpec("xml", frozenset({".xml"}), "XML structure"),
    FormatSpec("cbz", frozenset({".cbz"}), "CBZ"),
    FormatSpec("csv", frozenset({".csv"}), "Tables CSV"),
    FormatSpec("tables_json", frozenset({".json"}), "Tables JSON"),
    FormatSpec(
        "xlsx",
        frozenset({".xlsx"}),
        "Tables XLSX",
        capability_id=OPENPYXL,
    ),
)

_IMPORT_BY_EXT: dict[str, FormatSpec] = {
    ext: spec for spec in IMPORT_TO_PDF_FORMATS for ext in spec.extensions
}
_EXPORT_BY_ID: dict[str, FormatSpec] = {spec.id: spec for spec in EXPORT_FROM_PDF_FORMATS}


def is_supported_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def is_pdf_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() == ".pdf"


def import_format_for_path(path: str | Path) -> FormatSpec | None:
    return _IMPORT_BY_EXT.get(Path(path).suffix.lower())


def export_format(format_id: str) -> FormatSpec:
    try:
        return _EXPORT_BY_ID[format_id]
    except KeyError as exc:
        raise KeyError(f"unknown export format: {format_id!r}") from exc


def format_capability_available(spec: FormatSpec, *, refresh: bool = False) -> bool:
    """True when *spec* needs no codec pack, or the pack is present."""
    if spec.capability_id is None:
        return True
    return probe(spec.capability_id, refresh=refresh).available


def is_native_import_path(
    path: str | Path,
    *,
    available_only: bool = True,
) -> bool:
    """True when *path* is a registered non-image → PDF import format."""
    spec = import_format_for_path(path)
    if spec is None:
        return False
    if available_only and not format_capability_available(spec):
        return False
    return True


def import_extensions(*, available_only: bool = True) -> frozenset[str]:
    exts: set[str] = set()
    for spec in IMPORT_TO_PDF_FORMATS:
        if available_only and not format_capability_available(spec):
            continue
        exts.update(spec.extensions)
    return frozenset(exts)


def export_formats(*, available_only: bool = True) -> tuple[FormatSpec, ...]:
    if not available_only:
        return EXPORT_FROM_PDF_FORMATS
    return tuple(
        spec for spec in EXPORT_FROM_PDF_FORMATS if format_capability_available(spec)
    )


def image_dialog_filter() -> str:
    extensions = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_IMAGE_EXTENSIONS))
    return f"Images ({extensions});;All Files (*)"


def _dialog_filter_from_specs(
    specs: Iterable[FormatSpec],
    *,
    all_label: str,
) -> str:
    parts: list[str] = []
    all_exts: list[str] = []
    for spec in specs:
        exts = " ".join(f"*{ext}" for ext in sorted(spec.extensions))
        parts.append(f"{spec.label} ({exts})")
        all_exts.extend(f"*{ext}" for ext in sorted(spec.extensions))
    if all_exts:
        parts.insert(0, f"{all_label} ({' '.join(all_exts)})")
    parts.append("All Files (*)")
    return ";;".join(parts)


def import_to_pdf_dialog_filter(*, available_only: bool = True) -> str:
    specs = [
        spec
        for spec in IMPORT_TO_PDF_FORMATS
        if not available_only or format_capability_available(spec)
    ]
    return _dialog_filter_from_specs(specs, all_label="Documents")


def export_from_pdf_dialog_filter(*, available_only: bool = True) -> str:
    return _dialog_filter_from_specs(
        export_formats(available_only=available_only),
        all_label="Export formats",
    )


def local_paths_from_mime(
    mime,
    *,
    accept: Callable[[str], bool] | None = None,
    sort: bool = False,
) -> list[str]:
    """Return local file paths from a file-manager drag payload."""
    paths: list[str] = []
    if not mime.hasUrls():
        return paths
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if accept is not None and not accept(path):
            continue
        paths.append(path)
    return sorted(paths) if sort else paths


def image_paths_from_mime(mime) -> list[str]:
    """Return local supported-image paths from a file-manager drag payload."""
    return local_paths_from_mime(mime, accept=is_supported_image)


def pdf_paths_from_mime(mime) -> list[str]:
    """Return sorted local *.pdf paths from a file-manager drag payload."""
    return local_paths_from_mime(mime, accept=is_pdf_path, sort=True)


def native_import_paths_from_mime(mime, *, available_only: bool = True) -> list[str]:
    """Return local native-import paths from a file-manager drag payload."""
    return local_paths_from_mime(
        mime,
        accept=lambda p: is_native_import_path(p, available_only=available_only),
    )
