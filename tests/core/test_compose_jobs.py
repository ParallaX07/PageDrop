"""Merge and image-to-PDF jobs on the shared runner: staging, cancel, no partial output."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pagedrop.core import pdf_writer
from pagedrop.core.jobs import (
    CancelToken,
    JobCancelledError,
    JobError,
    JobSpec,
    SerializedJobRunner,
    SourceOverwriteError,
)
from pagedrop.core.organize_jobs import register_organize_handlers
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import file_sha256
from tests.core.test_image_to_pdf import _page_count, _write_test_image
from tests.core.test_jobs import _write_pdf


@pytest.fixture
def runner():
    temp = TempManager()
    runner = SerializedJobRunner(temp)
    register_organize_handlers(runner)
    try:
        yield runner
    finally:
        temp.cleanup()


def _no_staging_left(runner: SerializedJobRunner) -> bool:
    return not any(runner.temp_manager.get_dir().glob("job_*"))


def test_merge_job_writes_new_file_and_keeps_sources(tmp_path: Path, runner) -> None:
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    out = tmp_path / "merged.pdf"
    _write_pdf(first)
    _write_pdf(second, pages=2)
    hashes = [file_sha256(first), file_sha256(second)]

    result = runner.run(
        JobSpec.create("merge", inputs=[first, second], output=out)
    )

    assert result == out
    assert _page_count(out) == 3
    assert [file_sha256(first), file_sha256(second)] == hashes
    assert _no_staging_left(runner)


def test_merge_job_rejects_output_equal_to_input(tmp_path: Path, runner) -> None:
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    _write_pdf(first)
    _write_pdf(second)
    before = file_sha256(second)

    with pytest.raises(SourceOverwriteError):
        runner.run(
            JobSpec.create(
                "merge", inputs=[first, second], output=second, overwrite=True
            )
        )

    assert file_sha256(second) == before
    assert _no_staging_left(runner)


def test_merge_job_cancelled_between_inputs_leaves_no_output(
    tmp_path: Path, runner, monkeypatch
) -> None:
    sources = []
    for index in range(3):
        path = tmp_path / f"in_{index}.pdf"
        _write_pdf(path)
        sources.append(path)
    hashes = [file_sha256(path) for path in sources]
    out = tmp_path / "merged.pdf"
    token = CancelToken()
    real_cached_doc = pdf_writer._cached_doc
    opened: list[str] = []

    def cancel_after_first(path, docs, passwords):
        doc = real_cached_doc(path, docs, passwords)
        opened.append(path)
        token.cancel()
        return doc

    monkeypatch.setattr(pdf_writer, "_cached_doc", cancel_after_first)

    with pytest.raises(JobCancelledError):
        runner.run(
            JobSpec.create("merge", inputs=sources, output=out), cancel=token
        )

    assert len(opened) == 1
    assert not out.exists()
    assert [file_sha256(path) for path in sources] == hashes
    assert _no_staging_left(runner)


def _images_with_corrupt_third(tmp_path: Path) -> list[Path]:
    images = []
    for name in ("alpha", "bravo"):
        path = tmp_path / f"{name}.png"
        _write_test_image(path, 100, 100)
        images.append(path)
    corrupt = tmp_path / "charlie.png"
    corrupt.write_text("not an image", encoding="utf-8")
    images.append(corrupt)
    return images


def test_single_pdf_job_with_corrupt_third_image_keeps_existing_output(
    tmp_path: Path, runner
) -> None:
    images = _images_with_corrupt_third(tmp_path)
    hashes = [file_sha256(path) for path in images]
    out = tmp_path / "combined.pdf"
    _write_pdf(out)
    existing = file_sha256(out)

    with pytest.raises(JobError):
        runner.run(
            JobSpec.create(
                "images_to_pdf", inputs=images, output=out, overwrite=True
            )
        )

    assert file_sha256(out) == existing
    assert [file_sha256(path) for path in images] == hashes
    assert _no_staging_left(runner)


def test_single_pdf_job_cancelled_between_images_leaves_no_output(
    tmp_path: Path, runner, monkeypatch
) -> None:
    from pagedrop.core import image_to_pdf

    images = []
    for name in ("alpha", "bravo", "charlie"):
        path = tmp_path / f"{name}.png"
        _write_test_image(path, 100, 100)
        images.append(path)
    out = tmp_path / "combined.pdf"
    token = CancelToken()
    real_append = image_to_pdf._append_image_pdf

    def cancel_after_first(doc, path):
        real_append(doc, path)
        token.cancel()

    monkeypatch.setattr(image_to_pdf, "_append_image_pdf", cancel_after_first)

    with pytest.raises(JobCancelledError):
        runner.run(
            JobSpec.create("images_to_pdf", inputs=images, output=out), cancel=token
        )

    assert not out.exists()
    assert _no_staging_left(runner)


def test_individual_pdf_job_writes_every_output(tmp_path: Path, runner) -> None:
    images = []
    for name in ("alpha", "bravo"):
        path = tmp_path / f"{name}.png"
        _write_test_image(path, 100, 100)
        images.append(path)
    hashes = [file_sha256(path) for path in images]
    out_dir = tmp_path / "out"

    result = runner.run(
        JobSpec.create(
            "images_to_pdfs", inputs=images, output=out_dir / "alpha.pdf"
        )
    )

    assert result == out_dir / "alpha.pdf"
    assert _page_count(out_dir / "alpha.pdf") == 1
    assert _page_count(out_dir / "bravo.pdf") == 1
    assert [file_sha256(path) for path in images] == hashes
    assert _no_staging_left(runner)


def test_individual_pdf_job_gives_shared_stems_distinct_outputs(
    tmp_path: Path, runner
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    images = [src_dir / name for name in ("a.png", "a.jpg", "a_2.png")]
    for image in images:
        _write_test_image(image, 100, 100)
    hashes = [file_sha256(path) for path in images]
    out_dir = tmp_path / "out"

    result = runner.run(
        JobSpec.create("images_to_pdfs", inputs=images, output=out_dir / "a.pdf")
    )

    assert result == out_dir / "a.pdf"
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "a.pdf",
        "a_2.pdf",
        "a_2_2.pdf",
    ]
    assert [file_sha256(path) for path in images] == hashes
    assert _no_staging_left(runner)


def test_individual_pdf_job_treats_names_differing_by_case_as_shared(
    tmp_path: Path, runner
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    images = [src_dir / "Photo.png", src_dir / "photo.jpg"]
    for image in images:
        _write_test_image(image, 100, 100)
    out_dir = tmp_path / "out"

    runner.run(
        JobSpec.create("images_to_pdfs", inputs=images, output=out_dir / "Photo.pdf")
    )

    assert sorted(p.name for p in out_dir.iterdir()) == ["Photo.pdf", "photo_2.pdf"]


def test_individual_pdf_job_with_corrupt_third_image_publishes_nothing(
    tmp_path: Path, runner
) -> None:
    images = _images_with_corrupt_third(tmp_path)
    hashes = [file_sha256(path) for path in images]
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    existing = out_dir / "alpha.pdf"
    fitz_doc = fitz.open()
    fitz_doc.new_page(width=50, height=50)
    fitz_doc.save(str(existing))
    fitz_doc.close()
    before = file_sha256(existing)

    with pytest.raises(JobError):
        runner.run(
            JobSpec.create(
                "images_to_pdfs", inputs=images, output=existing, overwrite=True
            )
        )

    assert file_sha256(existing) == before
    assert sorted(path.name for path in out_dir.iterdir()) == ["alpha.pdf"]
    assert [file_sha256(path) for path in images] == hashes
    assert _no_staging_left(runner)
