"""Phase 24 smoke — split then merge pieces; reverse round-trip."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from pagedrop.core import pdf_tools
from pagedrop.core.pdf_writer import merge_pdf_files


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_text_pdf(path: Path, labels: list[str]) -> Path:
    doc = fitz.open()
    try:
        for label in labels:
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), label, fontsize=18)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def _page_labels(path: Path) -> list[str]:
    doc = fitz.open(str(path))
    try:
        return [doc[i].get_text().strip() for i in range(doc.page_count)]
    finally:
        doc.close()


def test_smoke_split_then_merge_pieces(tmp_path: Path) -> None:
    src = tmp_path / "source.pdf"
    labels = [f"P{i}" for i in range(5)]
    _make_text_pdf(src, labels)
    source_hash = _file_hash(src)

    out_dir = tmp_path / "parts"
    out_dir.mkdir()
    parts = pdf_tools.extract_ranges_to_folder(
        str(src),
        [(0, 1), (2, 4)],
        out_dir,
        base_name="piece",
    )
    assert len(parts) == 2
    assert _file_hash(src) == source_hash

    merged = tmp_path / "rejoined.pdf"
    merge_pdf_files([str(p) for p in parts], str(merged))
    assert _page_labels(merged) == labels
    assert _file_hash(src) == source_hash


def test_smoke_reverse_round_trip(tmp_path: Path) -> None:
    src = tmp_path / "source.pdf"
    labels = ["A", "B", "C", "D"]
    _make_text_pdf(src, labels)
    source_hash = _file_hash(src)

    reversed_path = tmp_path / "reversed.pdf"
    pdf_tools.reverse_pdf_pages(str(src), str(reversed_path))
    assert _page_labels(reversed_path) == list(reversed(labels))
    assert _file_hash(src) == source_hash

    restored = tmp_path / "restored.pdf"
    pdf_tools.reverse_pdf_pages(str(reversed_path), str(restored))
    assert _page_labels(restored) == labels
    assert _file_hash(src) == source_hash
