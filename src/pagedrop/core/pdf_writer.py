from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import EmptyFileError, PdfReadError, PyPdfError

from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_loader import (
    PdfCorruptError,
    PdfEmptyError,
    PdfNotFoundError,
)


def _cached_reader(path: str, readers: dict[str, PdfReader]) -> PdfReader:
    if path not in readers:
        readers[path] = _open_pdf_reader(path)
    return readers[path]


def _open_pdf_reader(path: str) -> PdfReader:
    if not Path(path).is_file():
        raise PdfNotFoundError(f"PDF not found: {path}")
    try:
        reader = PdfReader(path)
    except EmptyFileError as exc:
        raise PdfCorruptError(f"PDF file is empty: {path}") from exc
    except FileNotFoundError as exc:
        raise PdfNotFoundError(f"PDF not found: {path}") from exc
    except PdfReadError as exc:
        raise PdfCorruptError(f"PDF file is corrupt or invalid: {path}") from exc
    except PyPdfError as exc:
        raise PdfCorruptError(f"PDF file is corrupt or invalid: {path}") from exc
    if len(reader.pages) == 0:
        raise PdfEmptyError(f"PDF has no pages: {path}")
    return reader


def merge_pdf_files(file_paths: list[str], output_path: str) -> None:
    """Merge whole PDFs in *file_paths* order, writing to *output_path*."""
    if not file_paths:
        raise ValueError("No PDF files to merge")

    readers: dict[str, PdfReader] = {}
    writer = PdfWriter()
    for path in file_paths:
        reader = _cached_reader(path, readers)
        for page in reader.pages:
            writer.add_page(page)
    with open(output_path, "wb") as handle:
        writer.write(handle)


def write_pdf(model: PdfEditModel, output_path: str) -> None:
    """Write the logical page list to *output_path*, preserving order."""
    readers: dict[str, PdfReader] = {}
    writer = PdfWriter()
    for logical_index in range(model.logical_count()):
        ref = model.page_at(logical_index)
        if ref.source_path not in readers:
            readers[ref.source_path] = PdfReader(ref.source_path)
        reader = readers[ref.source_path]
        writer.add_page(reader.pages[ref.source_index])
    with open(output_path, "wb") as handle:
        writer.write(handle)
