"""Generate tiny PDF fixtures for tests (no checked-in binaries)."""

from __future__ import annotations

from pathlib import Path

import fitz

FIXTURE_NAMES = (
    "one_page",
    "five_page",
    "empty",
    "corrupt",
    "garbage",
    "compare_original",
    "compare_revised",
)

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


def generate_compare_pair(directory: Path) -> tuple[Path, Path]:
    """Write a reusable, fitz-only pair covering the comparison report matrix."""
    directory.mkdir(parents=True, exist_ok=True)
    original = directory / "compare_original.pdf"
    revised = directory / "compare_revised.pdf"
    _write_compare_pdf(original, revised=False)
    _write_compare_pdf(revised, revised=True)
    return original, revised


def _write_compare_pdf(path: Path, *, revised: bool) -> None:
    document = fitz.open()
    try:
        long_text = (
            "after <tag> & naïve 世界 "
            + " ".join(f"new{index}" for index in range(600))
            if revised
            else "before <tag> & café Ω "
            + " ".join(f"old{index}" for index in range(600))
        )
        if revised:
            pages = [
                ((280, 180), "Shared replace-after added-only café 世界", 90, None),
                ((360, 200), "Unchanged page", 0, (12, 10, 320, 180)),
                ((240, 180), "keep", 0, None),
                ((240, 180), "keep added-only", 0, None),
                ((220, 160), None, 0, None),
                ((180, 120), None, 0, None),
                ((300, 220), long_text, 0, None),
                ((260, 160), "extra revised page", 0, None),
            ]
        else:
            pages = [
                ((280, 180), "Shared replace-before remove-only café Ω", 90, None),
                ((360, 200), "Unchanged page", 0, (12, 10, 320, 180)),
                ((240, 180), "keep remove-only", 0, None),
                ((240, 180), "keep", 0, None),
                ((220, 160), None, 0, None),
                ((180, 120), None, 0, None),
                ((300, 220), long_text, 0, None),
            ]
        for (width, height), text, rotation, crop in pages:
            page = document.new_page(width=width, height=height)
            if text:
                if len(text) > 200:
                    words = text.split()
                    for row in range(0, len(words), 18):
                        page.insert_text(
                            (12, 18 + (row // 18) * 5),
                            " ".join(words[row : row + 18]),
                            fontsize=4,
                        )
                else:
                    page.insert_text((12, 36), text, fontsize=16)
            if text is None and page.number == 4:
                page.draw_rect(fitz.Rect(24, 24, 120, 96), fill=(0.25, 0.45, 0.8), color=None)
            if crop:
                page.set_cropbox(fitz.Rect(*crop))
            if rotation:
                page.set_rotation(rotation)
        document.save(str(path))
    finally:
        document.close()


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
        if not target.exists():
            generator(target)
    if not all(
        (directory / f"compare_{side}.pdf").exists()
        for side in ("original", "revised")
    ):
        generate_compare_pair(directory)


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
