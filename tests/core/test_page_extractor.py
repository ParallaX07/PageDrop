"""Phase 6 unit tests — page extractor."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core.page_extractor import (
    extract_page_refs_to_folder,
    extract_page_refs_to_files,
    extract_page_refs_to_pdf,
    extract_pages_to_files,
    plan_folder_export_paths,
)
from pagedrop.core.jobs import CancelToken, JobCancelledError, OutputExistsError
from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_loader import PdfPasswordError, PdfPasswordRequiredError
from pagedrop.core.jobs.staging import JobStaging
from pagedrop.utils.temp_manager import TempManager
from tests.core.test_jobs import _encrypted_pdf


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _page_size(path: Path | str, page_index: int = 0) -> tuple[float, float]:
    doc = fitz.open(str(path))
    try:
        rect = doc[page_index].rect
        return (float(rect.width), float(rect.height))
    finally:
        doc.close()


def test_extract_single_page(one_page_pdf, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    paths = extract_pages_to_files(
        str(one_page_pdf),
        [0],
        output_dir,
        "report",
    )

    assert len(paths) == 1
    assert paths[0].name == "report_page_0001.pdf"
    doc = fitz.open(str(paths[0]))
    try:
        assert doc.page_count == 1
    finally:
        doc.close()


def test_extract_multiple_non_contiguous(pdf_fixtures_dir, tmp_path):
    source = pdf_fixtures_dir / "ten_page.pdf"
    if not source.exists():
        from tests.fixtures.generate_fixtures import generate_n_page

        generate_n_page(source, 10)

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    indices = [0, 3, 6]
    paths = extract_pages_to_files(str(source), indices, output_dir, "doc")

    assert len(paths) == 3
    assert [path.name for path in paths] == [
        "doc_page_0001.pdf",
        "doc_page_0004.pdf",
        "doc_page_0007.pdf",
    ]

    for path, index in zip(paths, sorted(indices), strict=True):
        extracted = fitz.open(str(path))
        try:
            assert extracted.page_count == 1
            assert _page_size(path) == _page_size(source, index)
        finally:
            extracted.close()


def test_filename_zero_padding(pdf_fixtures_dir, tmp_path):
    source = pdf_fixtures_dir / "ten_page.pdf"
    if not source.exists():
        from tests.fixtures.generate_fixtures import generate_n_page

        generate_n_page(source, 10)

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    paths = extract_pages_to_files(
        str(source),
        [2, 9],
        output_dir,
        "report",
    )

    names = [path.name for path in paths]
    assert names == ["report_page_0003.pdf", "report_page_0010.pdf"]
    assert names == sorted(names)


def test_extracted_content_matches_source(five_page_pdf, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    indices = [1, 4]
    paths = extract_pages_to_files(
        str(five_page_pdf),
        indices,
        output_dir,
        "report",
    )

    for path, index in zip(paths, sorted(indices), strict=True):
        extracted = fitz.open(str(path))
        try:
            assert extracted.page_count == 1
            assert _page_size(path) == _page_size(five_page_pdf, index)
        finally:
            extracted.close()


def test_extract_encrypted_with_password_leaves_source_unchanged(tmp_path):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = _file_hash(enc)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    paths = extract_pages_to_files(
        str(enc), [0], output_dir, "locked", password="secret"
    )

    assert len(paths) == 1
    assert _file_hash(enc) == source_hash
    out = fitz.open(str(paths[0]))
    try:
        assert out.page_count == 1
        assert not out.needs_pass
    finally:
        out.close()


def test_extract_encrypted_without_password_fails_clearly(tmp_path):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = _file_hash(enc)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(PdfPasswordRequiredError, match="password-protected"):
        extract_pages_to_files(str(enc), [0], output_dir, "locked")

    assert _file_hash(enc) == source_hash
    assert list(output_dir.iterdir()) == []


def test_extract_page_refs_encrypted_rotation_multi_source(tmp_path):
    enc_a = tmp_path / "a.pdf"
    enc_b = tmp_path / "b.pdf"
    _encrypted_pdf(enc_a, password="alpha")
    _encrypted_pdf(enc_b, password="beta")
    hash_a = _file_hash(enc_a)
    hash_b = _file_hash(enc_b)

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    refs = [
        PageRef(str(enc_a), 0, rotation=90),
        PageRef(str(enc_b), 0, rotation=180),
    ]
    passwords = {str(enc_a): "alpha", str(enc_b): "beta"}

    paths = extract_page_refs_to_files(
        refs, output_dir, "mix", passwords=passwords
    )

    assert [p.name for p in paths] == [
        "mix_page_0001.pdf",
        "mix_page_0002.pdf",
    ]
    assert _file_hash(enc_a) == hash_a
    assert _file_hash(enc_b) == hash_b

    for path, expected_rot in zip(paths, (90, 180), strict=True):
        doc = fitz.open(str(path))
        try:
            assert doc.page_count == 1
            assert not doc.needs_pass
            assert doc[0].rotation == expected_rot
        finally:
            doc.close()


def test_extract_page_refs_wrong_password_fails_clearly(tmp_path):
    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = _file_hash(enc)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(PdfPasswordError, match="Incorrect password"):
        extract_page_refs_to_files(
            [PageRef(str(enc), 0)],
            output_dir,
            "locked",
            passwords={str(enc): "wrong"},
        )

    assert _file_hash(enc) == source_hash
    assert list(output_dir.iterdir()) == []


def test_plan_folder_export_paths_reserves_stable_names(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "report_page_0001.pdf").write_bytes(b"existing")
    (output_dir / "report_page_0001_2.pdf").write_bytes(b"existing too")
    (output_dir / "report_page_0002.pdf").write_bytes(b"existing")

    paths = plan_folder_export_paths(output_dir, "report", [1, 1, 2])

    assert [path.name for path in paths] == [
        "report_page_0001_3.pdf",
        "report_page_0001_4.pdf",
        "report_page_0002_2.pdf",
    ]
    assert not any(path.exists() for path in paths)


def test_folder_export_renames_collisions_without_changing_existing(
    five_page_pdf: Path, tmp_path: Path
) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    existing = output_dir / "report_page_0001.pdf"
    existing.write_bytes(b"unrelated bytes")
    existing_hash = _file_hash(existing)

    paths = extract_page_refs_to_folder(
        [PageRef(str(five_page_pdf), 0), PageRef(str(five_page_pdf), 2)],
        output_dir,
        "report",
    )

    assert [path.name for path in paths] == [
        "report_page_0001_2.pdf",
        "report_page_0002.pdf",
    ]
    assert _file_hash(existing) == existing_hash
    for path in paths:
        document = fitz.open(str(path))
        try:
            assert document.page_count == 1
        finally:
            document.close()


def test_folder_export_preserves_file_created_after_planning(
    five_page_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    concurrent = output_dir / "report_page_0001.pdf"
    real_promote = JobStaging.promote_no_clobber
    calls = 0

    def create_concurrent(self: JobStaging, staged: Path, destination: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            concurrent.write_bytes(b"concurrent bytes")
        return real_promote(self, staged, destination)

    monkeypatch.setattr(JobStaging, "promote_no_clobber", create_concurrent)
    with pytest.raises(OutputExistsError):
        extract_page_refs_to_folder(
            [PageRef(str(five_page_pdf), 0), PageRef(str(five_page_pdf), 1)],
            output_dir,
            "report",
        )

    assert concurrent.read_bytes() == b"concurrent bytes"
    assert list(output_dir.iterdir()) == [concurrent]


def test_folder_export_rolls_back_owned_files_on_promotion_failure(
    five_page_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    existing = output_dir / "keep.pdf"
    existing.write_bytes(b"keep")
    temp = TempManager()
    real_promote = JobStaging.promote_no_clobber
    calls = 0

    def fail_second(self: JobStaging, staged: Path, destination: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            replacement = output_dir / "concurrent.pdf"
            replacement.write_bytes(b"concurrent")
            replacement.replace(output_dir / "report_page_0001.pdf")
            raise OSError("promotion failed")
        return real_promote(self, staged, destination)

    monkeypatch.setattr(JobStaging, "promote_no_clobber", fail_second)
    try:
        with pytest.raises(OSError, match="promotion failed"):
            extract_page_refs_to_folder(
                [PageRef(str(five_page_pdf), 0), PageRef(str(five_page_pdf), 1)],
                output_dir,
                "report",
                temp_manager=temp,
        )
        assert existing.read_bytes() == b"keep"
        concurrent = output_dir / "report_page_0001.pdf"
        assert concurrent.read_bytes() == b"concurrent"
        assert sorted(output_dir.iterdir()) == sorted([concurrent, existing])
        assert not any(temp.get_dir().glob("job_*"))
    finally:
        temp.cleanup()


def test_folder_export_cancellation_leaves_no_outputs(
    five_page_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    token = CancelToken()
    real_save = fitz.Document.save

    def cancel_after_first_save(self: fitz.Document, *args: object, **kwargs: object) -> None:
        real_save(self, *args, **kwargs)
        token.cancel()

    monkeypatch.setattr(fitz.Document, "save", cancel_after_first_save)
    with pytest.raises(JobCancelledError):
        extract_page_refs_to_folder(
            [PageRef(str(five_page_pdf), 0), PageRef(str(five_page_pdf), 1)],
            output_dir,
            "report",
            cancel=token,
        )

    assert list(output_dir.iterdir()) == []


def test_extract_page_refs_to_files_ponytail_marker() -> None:
    """O17-g: sync drag-out extract freeze ceiling is named in source."""
    import pagedrop.core.page_extractor as mod

    text = Path(mod.__file__).read_text(encoding="utf-8")
    idx = text.index("def extract_page_refs_to_files")
    chunk = text[idx : idx + 1600]
    assert "ponytail:" in chunk
    assert "QDrag" in chunk or "file://" in chunk
    assert "FITZ_LOCK" in chunk


def _write_distinct_pdf(path: Path, widths: list[int]) -> None:
    doc = fitz.open()
    try:
        for width in widths:
            doc.new_page(width=width, height=200)
        doc.save(str(path))
    finally:
        doc.close()


def test_extract_page_refs_to_pdf_batches_contiguous(tmp_path, monkeypatch):
    source = tmp_path / "src.pdf"
    _write_distinct_pdf(source, [100, 200, 300, 400, 500])
    refs = [PageRef(str(source), i) for i in range(5)]
    output = tmp_path / "combined.pdf"

    insert_calls: list[tuple[int | None, int | None]] = []
    real_insert = fitz.Document.insert_pdf

    def _spy(self, docsrc, *args, **kwargs):
        insert_calls.append((kwargs.get("from_page"), kwargs.get("to_page")))
        return real_insert(self, docsrc, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "insert_pdf", _spy)

    path = extract_page_refs_to_pdf(refs, output)
    assert path == output
    assert insert_calls == [(0, 4)]

    doc = fitz.open(str(output))
    try:
        assert doc.page_count == 5
        assert [float(doc[i].rect.width) for i in range(5)] == [
            100.0,
            200.0,
            300.0,
            400.0,
            500.0,
        ]
    finally:
        doc.close()


def test_extract_page_refs_to_pdf_preserves_rotation_and_multi_source(
    tmp_path, monkeypatch
):
    doc_a = tmp_path / "a.pdf"
    doc_b = tmp_path / "b.pdf"
    _write_distinct_pdf(doc_a, [111, 222])
    _write_distinct_pdf(doc_b, [333])
    refs = [
        PageRef(str(doc_a), 0, rotation=90),
        PageRef(str(doc_a), 1, rotation=180),
        PageRef(str(doc_b), 0, rotation=270),
    ]

    insert_calls: list[tuple[int | None, int | None]] = []
    real_insert = fitz.Document.insert_pdf

    def _spy(self, docsrc, *args, **kwargs):
        insert_calls.append((kwargs.get("from_page"), kwargs.get("to_page")))
        return real_insert(self, docsrc, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "insert_pdf", _spy)

    output = tmp_path / "mix.pdf"
    extract_page_refs_to_pdf(refs, output)

    assert insert_calls == [(0, 1), (0, 0)]
    doc = fitz.open(str(output))
    try:
        assert doc.page_count == 3
        assert doc[0].rotation == 90
        assert doc[1].rotation == 180
        assert doc[2].rotation == 270
        assert [float(doc[i].mediabox.width) for i in range(3)] == [
            111.0,
            222.0,
            333.0,
        ]
    finally:
        doc.close()
