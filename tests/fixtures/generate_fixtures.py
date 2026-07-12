"""Generate tiny PDF fixtures for tests (no checked-in binaries)."""

from __future__ import annotations

from pathlib import Path

import fitz

FIXTURE_NAMES = ("one_page", "five_page", "empty", "corrupt", "garbage")

# fitz refuses to save zero-page docs; a minimal catalog is enough for PdfEmptyError.
_EMPTY_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
    b"2 0 obj<< /Type /Pages /Kids [] /Count 0 >>endobj\n"
    b"xref\n0 3\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"trailer<< /Size 3 /Root 1 0 R >>\n"
    b"startxref\n109\n%%EOF\n"
)


def _write_blank_pages(path: Path, page_count: int, *, width: float = 200) -> None:
    doc = fitz.open()
    try:
        for _ in range(page_count):
            doc.new_page(width=width, height=200)
        doc.save(str(path))
    finally:
        doc.close()


def generate_one_page(path: Path) -> None:
    _write_blank_pages(path, 1)


def generate_five_page(path: Path) -> None:
    _write_blank_pages(path, 5)


def generate_empty(path: Path) -> None:
    """Valid PDF structure with zero pages."""
    path.write_bytes(_EMPTY_PDF)


def generate_corrupt(path: Path) -> None:
    """Plain text saved with a .pdf extension."""
    path.write_text("This is not a PDF file — just text renamed to .pdf\n", encoding="utf-8")


def generate_garbage(path: Path) -> None:
    """Random binary bytes with a .pdf extension."""
    path.write_bytes(bytes(range(256)) * 4)


def generate_n_page(path: Path, page_count: int) -> None:
    _write_blank_pages(path, page_count)


def ensure_fixtures(directory: Path) -> None:
    """Create all standard fixtures if missing."""
    directory.mkdir(parents=True, exist_ok=True)
    generators = {
        "one_page": generate_one_page,
        "five_page": generate_five_page,
        "empty": generate_empty,
        "corrupt": generate_corrupt,
        "garbage": generate_garbage,
    }
    for name, generator in generators.items():
        target = directory / f"{name}.pdf"
        if name in ("empty", "corrupt", "garbage") or not target.exists():
            generator(target)


def fixture_path(directory: Path, name: str) -> Path:
    if name not in FIXTURE_NAMES:
        raise ValueError(f"Unknown fixture: {name}")
    path = directory / f"{name}.pdf"
    if not path.exists():
        ensure_fixtures(directory)
    return path


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "generated"
    ensure_fixtures(out)
    print(f"Generated fixtures in {out}")
