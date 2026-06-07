from __future__ import annotations

from pathlib import Path

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


def is_supported_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def is_pdf_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() == ".pdf"


def image_dialog_filter() -> str:
    extensions = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_IMAGE_EXTENSIONS))
    return f"Images ({extensions});;All Files (*)"


def image_paths_from_mime(mime) -> list[str]:
    """Return local file paths from a file-manager drag payload."""
    paths: list[str] = []
    if not mime.hasUrls():
        return paths
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        paths.append(url.toLocalFile())
    return paths
