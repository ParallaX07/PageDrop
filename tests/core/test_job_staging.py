"""JobStaging: promote cache invalidation and cleanup resilience."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pagedrop.core import pdf_service
from pagedrop.core.jobs import staging as staging_module
from pagedrop.core.jobs.staging import JobStaging
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import file_sha256


def _pdf(path: Path, pages: int) -> Path:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def test_promote_evicts_cached_destination_before_replacing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _pdf(tmp_path / "source.pdf", 1)
    dest = _pdf(tmp_path / "result.pdf", 2)
    source_hash = file_sha256(source)
    assert pdf_service.page_count(str(dest)) == 2  # previewed: dest now cached
    key = pdf_service._cache_key(str(dest))
    assert key in pdf_service._doc_cache

    temp = TempManager()
    seen_cached: list[bool] = []
    real_replace = staging_module.os.replace

    def spy_replace(src, dst):
        seen_cached.append(key in pdf_service._doc_cache)
        return real_replace(src, dst)

    monkeypatch.setattr(staging_module.os, "replace", spy_replace)
    try:
        staging = JobStaging(temp)
        staged = staging.stage_file()
        _pdf(staged, 3)
        assert dest != source

        staging.promote(staged, dest)

        assert seen_cached == [False]
        assert pdf_service.page_count(str(dest)) == 3
        assert file_sha256(source) == source_hash
    finally:
        pdf_service.invalidate_doc_cache(str(dest))
        temp.cleanup()


def test_cleanup_unpins_job_dir_even_when_unlink_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp = TempManager(max_bytes=100)
    try:
        staging = JobStaging(temp)
        staged = staging.stage_file()
        staged.write_bytes(b"x" * 200)

        # Pinned while the job is live: a later dir creation must not evict it.
        temp.create_drag_dir()
        assert staging.job_dir.exists()

        def deny(self, *args, **kwargs):
            raise PermissionError("in use")

        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", deny)
            staging.cleanup()  # must not raise
        assert staged.exists()

        temp.create_drag_dir()  # unpinned now: quota eviction can take it
        assert not staging.job_dir.exists()
    finally:
        temp.cleanup()
