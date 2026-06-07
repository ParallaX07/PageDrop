from __future__ import annotations

from pypdf import PdfReader, PdfWriter

from pagedrop.core.pdf_editor import PdfEditModel


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
