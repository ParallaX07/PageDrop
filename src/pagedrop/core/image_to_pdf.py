from __future__ import annotations

from collections import Counter
from pathlib import Path

import fitz

from pagedrop.core.supported_formats import is_supported_image
from pagedrop.utils.list_utils import move_items

MAX_IMAGE_DIMENSION_PX = 16384


class ImageConvertError(Exception):
    """Raised when an image cannot be converted to PDF."""


class ConvertModel:
    """Ordered list of image files to convert."""

    def __init__(self) -> None:
        self._paths: list[str] = []

    def add_files(self, paths: list[str]) -> list[str]:
        accepted: list[str] = []
        for path in paths:
            resolved = str(Path(path).resolve())
            if not is_supported_image(resolved):
                continue
            self._paths.append(resolved)
            accepted.append(resolved)
        return accepted

    def remove_at(self, index: int) -> None:
        del self._paths[index]

    def remove_indices(self, indices: list[int]) -> None:
        if not indices:
            return
        remove = set(indices)
        self._paths = [path for i, path in enumerate(self._paths) if i not in remove]

    def move_up(self, indices: list[int]) -> None:
        if not indices:
            return
        ordered = sorted(set(indices))
        if ordered[0] == 0:
            return
        self._paths, _ = move_items(self._paths, ordered, ordered[0] - 1)

    def move_down(self, indices: list[int]) -> None:
        if not indices:
            return
        ordered = sorted(set(indices))
        if ordered[-1] >= len(self._paths) - 1:
            return
        self._paths, _ = move_items(self._paths, ordered, ordered[-1] + 2)

    def reorder(self, from_index: int, to_index: int) -> None:
        if from_index == to_index:
            return
        item = self._paths.pop(from_index)
        self._paths.insert(to_index, item)

    def file_count(self) -> int:
        return len(self._paths)

    def path_at(self, index: int) -> str:
        return self._paths[index]

    def display_name(self, index: int) -> str:
        return Path(self._paths[index]).name

    def all_paths(self) -> list[str]:
        return list(self._paths)


def inspect_image(path: str) -> tuple[int, int]:
    """Open *path* and return ``(width_px, height_px)``."""
    filename = Path(path).name
    try:
        with fitz.open(path) as doc:
            if doc.page_count == 0:
                raise ImageConvertError(f"Image has no content: {filename}")
            rect = doc[0].rect
            width = int(round(rect.width))
            height = int(round(rect.height))
    except ImageConvertError:
        raise
    except Exception as exc:
        raise ImageConvertError(f"Could not read image {filename}: {exc}") from exc

    if width <= 0 or height <= 0:
        raise ImageConvertError(f"Invalid image dimensions: {filename}")
    if max(width, height) > MAX_IMAGE_DIMENSION_PX:
        raise ImageConvertError(
            f"{filename} is too large ({width}×{height} px). "
            f"Maximum dimension is {MAX_IMAGE_DIMENSION_PX} px."
        )
    return width, height


def validate_images(paths: list[str]) -> None:
    if not paths:
        raise ImageConvertError("No images to convert.")
    for path in paths:
        inspect_image(path)


def images_to_single_pdf(paths: list[str], output_path: str) -> None:
    validate_images(paths)
    doc = fitz.open()
    try:
        for path in paths:
            _append_image_pdf(doc, path)
        doc.save(output_path)
    except ImageConvertError:
        raise
    except OSError:
        raise
    except Exception as exc:
        raise ImageConvertError(f"Could not write PDF: {exc}") from exc
    finally:
        doc.close()


def images_to_individual_pdfs(
    paths: list[str],
    output_dir: str,
    *,
    overwrite: bool = False,
) -> list[str]:
    validate_images(paths)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem_counts: Counter[str] = Counter()
    written: list[str] = []

    for path in paths:
        stem = Path(path).stem
        stem_counts[stem] += 1
        occurrence = stem_counts[stem]
        out_path = _individual_output_path(out_dir, stem, occurrence)
        if out_path.exists() and not overwrite:
            out_path = _next_available_path(out_dir, stem)

        doc = fitz.open()
        try:
            _append_image_pdf(doc, path)
            doc.save(str(out_path))
        except ImageConvertError:
            raise
        except Exception as exc:
            raise ImageConvertError(
                f"Could not write {out_path.name}: {exc}"
            ) from exc
        finally:
            doc.close()
        written.append(str(out_path))

    return written


def planned_individual_outputs(paths: list[str], output_dir: str) -> list[Path]:
    """Return output paths that would be written for *paths* (first occurrence only)."""
    out_dir = Path(output_dir)
    stem_counts: Counter[str] = Counter()
    planned: list[Path] = []
    for path in paths:
        stem = Path(path).stem
        stem_counts[stem] += 1
        planned.append(_individual_output_path(out_dir, stem, stem_counts[stem]))
    return planned


def _append_image_pdf(doc: fitz.Document, path: str) -> None:
    filename = Path(path).name
    imgdoc = fitz.open(path)
    try:
        if imgdoc.page_count == 0:
            raise ImageConvertError(f"Image has no content: {filename}")
        pdf_bytes = imgdoc.convert_to_pdf()
    except ImageConvertError:
        raise
    except Exception as exc:
        raise ImageConvertError(f"Could not read image {filename}: {exc}") from exc
    finally:
        imgdoc.close()

    imgpdf = fitz.open("pdf", pdf_bytes)
    try:
        doc.insert_pdf(imgpdf)
    finally:
        imgpdf.close()


def _individual_output_path(output_dir: Path, stem: str, occurrence: int) -> Path:
    if occurrence == 1:
        return output_dir / f"{stem}.pdf"
    return output_dir / f"{stem}_{occurrence}.pdf"


def _next_available_path(output_dir: Path, stem: str) -> Path:
    candidate = output_dir / f"{stem}.pdf"
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = output_dir / f"{stem}_{index}.pdf"
        if not candidate.exists():
            return candidate
        index += 1
