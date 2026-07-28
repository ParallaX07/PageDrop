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


def test_office_handlers_register_without_fitz_lock() -> None:
    """Office / PDF→DOCX must not wrap the whole handler in FITZ_LOCK."""
    from pagedrop.core.office_conversion_jobs import register_office_conversion_handlers
    from pagedrop.core.pdf_to_docx_jobs import register_pdf_to_docx_handlers

    runner = SerializedJobRunner()
    register_office_conversion_handlers(runner)
    register_pdf_to_docx_handlers(runner)
    assert runner._handlers["office_to_pdf"].holds_fitz is False
    assert runner._handlers["pdf_to_docx"].holds_fitz is False


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
