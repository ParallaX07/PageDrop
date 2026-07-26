"""PyMuPDF concurrency policy contract."""

from __future__ import annotations

import fitz
import pytest

from pagedrop.core import thread_policy
from pagedrop.core.thread_policy import (
    WORKER_AUDIT,
    ensure_no_fitz_document,
    is_fitz_document,
)


def test_policy_documents_no_concurrent_fitz_and_migration() -> None:
    doc = thread_policy.__doc__ or ""
    assert "not" in doc.lower() and "concurrent" in doc.lower()
    assert "multiprocessing" in doc
    assert "FITZ_LOCK" in doc
    assert "main-thread" in doc.lower() or "main thread" in doc.lower()
    assert "pdf_service" in doc


def test_worker_audit_covers_known_fitz_pools() -> None:
    names = {name for name, _note in WORKER_AUDIT}
    assert names >= {
        "ThumbnailWorker",
        "PreviewRenderWorker",
        "ViewerRenderWorker",
        "_MergeThumbnailWorker",
        "_ConvertThumbnailWorker",
        "_MergeWorker",
        "_ConvertWorker",
    }


def test_ensure_no_fitz_document_rejects_document() -> None:
    doc = fitz.open()
    try:
        assert is_fitz_document(doc)
        with pytest.raises(TypeError, match="must not be shared"):
            ensure_no_fitz_document(doc, what="test")
    finally:
        doc.close()


def test_ensure_no_fitz_document_allows_paths_and_scalars() -> None:
    ensure_no_fitz_document("/tmp/x.pdf", 0, None, ("a", 1), what="test")
    assert not is_fitz_document("/tmp/x.pdf")
