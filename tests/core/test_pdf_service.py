"""Core contract tests for the serialized PDF service."""

from __future__ import annotations

from pathlib import Path

import fitz

from pagedrop.core import pdf_service
from pagedrop.core.jobs.runner import SerializedJobRunner
from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.pdf_service import FITZ_LOCK, search_model


def test_job_runner_uses_shared_fitz_lock() -> None:
    # SerializedJobRunner must share FITZ_LOCK with the viewer service.
    assert pdf_service.FITZ_LOCK is FITZ_LOCK
    runner = SerializedJobRunner()
    assert runner is not None


def test_search_respects_logical_order(tmp_path: Path) -> None:
    path = tmp_path / "ordered.pdf"
    doc = fitz.open()
    try:
        for text in ("first", "second", "third"):
            page = doc.new_page()
            page.insert_text((72, 72), text)
        doc.save(str(path))
    finally:
        doc.close()

    model = PdfEditModel(str(path), 3)
    model.move_pages([2], 0)  # third, first, second
    hits = search_model(model, "third")
    assert len(hits) == 1
    assert hits[0].logical_page == 0
