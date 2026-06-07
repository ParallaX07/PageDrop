"""Generate tiny PDF fixtures for tests (no checked-in binaries)."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter

FIXTURE_NAMES = ("one_page", "five_page", "empty")


def generate_one_page(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


def generate_five_page(path: Path) -> None:
    writer = PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


def generate_empty(path: Path) -> None:
    path.write_bytes(b"")


def generate_n_page(path: Path, page_count: int) -> None:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


def ensure_fixtures(directory: Path) -> None:
    """Create all standard fixtures if missing."""
    directory.mkdir(parents=True, exist_ok=True)
    generators = {
        "one_page": generate_one_page,
        "five_page": generate_five_page,
        "empty": generate_empty,
    }
    for name, generator in generators.items():
        target = directory / f"{name}.pdf"
        if not target.exists():
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
