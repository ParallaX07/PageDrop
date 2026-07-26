"""PyMuPDF / Qt concurrency policy for PageDrop.

Policy
------
PyMuPDF is **not** safe for concurrent multithreaded use. Even separate
``fitz.Document`` instances opened in different ``QThreadPool`` workers share
MuPDF global caches. Concurrent fitz from Qt threads can crash or corrupt.

Rules:

1. Never pass a live ``fitz.Document`` (or ``PdfLoader.doc``) into a worker.
   Workers open by path inside ``run()`` and close before returning.
2. ``PdfTab._loader_cache`` is **main-thread only**. UI code may use it for
   page counts / sizes; render and write workers must not.
3. Do not add new concurrent fitz paths on ``QThreadPool`` without a process
   boundary. Prefer ``multiprocessing`` (per-process opens) or a single
   serialized PDF service process.

Short-term allowance
--------------------
Existing UI workers keep a private ``QThreadPool`` with ``setMaxThreadCount(1)``
and open documents by path. That serializes *within* one pool but **does not**
serialize across windows (editor thumbnails + preview + merge + convert can
still overlap). Job runner and viewer already share ``pdf_service.FITZ_LOCK``;
other UI pools remain a known cross-window risk.

Migration
---------
- **job runner:** ``pagedrop.core.jobs.SerializedJobRunner`` — uses
  ``pdf_service.FITZ_LOCK``, stage/promote via ``TempManager``, paths only;
  never share fitz docs with ad-hoc UI pools. Upgrade path: dedicated PDF
  service process for fitz-heavy handlers (same stage/promote/cancel API).
- **viewer:** ``ui/pdf_viewer.py`` via ``pagedrop.core.pdf_service`` under
  ``FITZ_LOCK`` — not additional concurrent ``QThreadPool`` fitz callers
  outside that lock.
"""

from __future__ import annotations

from typing import Any

# Current QRunnable / pool sites that call fitz (audit).
# Each pool is maxThreadCount=1 and opens by path — still unsafe vs *other* pools
# unless they take ``pdf_service.FITZ_LOCK`` (viewer + job runner do).
WORKER_AUDIT: tuple[tuple[str, str], ...] = (
    (
        "ThumbnailWorker",
        "ui/thumbnail_grid.py — editor page thumbs; own opens; pool max 1",
    ),
    (
        "PreviewRenderWorker",
        "ui/page_preview.py — single-page preview; own open; pool max 1",
    ),
    (
        "ViewerRenderWorker",
        "ui/pdf_viewer.py — via pdf_service.render_ref_png under FITZ_LOCK; pool max 1",
    ),
    (
        "_MergeThumbnailWorker",
        "ui/merge_file_grid.py — via render_stacked_page_pngs; BaseFileGrid pool max 1",
    ),
    (
        "_ConvertThumbnailWorker",
        "ui/convert_file_grid.py — image thumbs via fitz.open; BaseFileGrid pool max 1",
    ),
    (
        "_MergeWorker",
        "ui/merge_window.py — merge_pdf_files in pool max 1; overlaps other windows",
    ),
    (
        "_ConvertWorker",
        "ui/convert_window.py — image_to_pdf in pool max 1; overlaps other windows",
    ),
)


def is_fitz_document(obj: object) -> bool:
    """True if *obj* is a live PyMuPDF Document (must not cross threads)."""
    cls = type(obj)
    if cls.__name__ != "Document":
        return False
    mod = cls.__module__
    return mod in {"fitz", "pymupdf"} or mod.startswith(("fitz.", "pymupdf."))


def ensure_no_fitz_document(*values: Any, what: str = "worker args") -> None:
    """Raise ``TypeError`` if any value is a ``fitz.Document``.

    Call at worker construction or ``run()`` entry when accepting opaque args,
    so cached loader docs cannot silently leak into background threads.
    """
    for value in values:
        if is_fitz_document(value):
            raise TypeError(
                f"{what}: fitz.Document must not be shared across threads; "
                "open by path inside the worker (see pagedrop.core.thread_policy)"
            )
