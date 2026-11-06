"""PyMuPDF / Qt concurrency policy for PageDrop.

Policy
------
PyMuPDF is **not** safe for concurrent multithreaded use. Even separate
``fitz.Document`` instances opened in different ``QThreadPool`` workers share
MuPDF global caches. Concurrent fitz from Qt threads can crash or corrupt.

Rules:

1. Every in-process PyMuPDF call holds ``FITZ_LOCK``.
2. Never pass a live ``fitz.Document`` (or ``PdfLoader.doc``) into a worker.
   Workers open by path inside ``run()`` and close before returning.
3. ``PdfTab._loader_cache`` is **main-thread only**; render and write workers
   must not touch it. ``PdfLoader`` methods take ``FITZ_LOCK`` themselves, and
   UI code reading other fitz data (metadata, bookmarks) goes through
   ``pdf_service.call``. No rule permits unlocked PyMuPDF.
4. Do not add new concurrent fitz paths on ``QThreadPool`` without a process
   boundary. Prefer ``multiprocessing`` (per-process opens) or a single
   serialized PDF service process.

Short-term allowance
--------------------
Existing UI workers keep a private ``QThreadPool`` with ``setMaxThreadCount(1)``
and open documents by path. That serializes *within* one pool; cross-window
overlap is covered by sharing ``pdf_service.FITZ_LOCK`` (or public
``pdf_service`` helpers that take it). Do not raise pool size to “fix”
thumbs — more threads worsen MuPDF races.

ponytail: ``FITZ_LOCK`` is the intentional global ceiling for in-process fitz;
upgrade path is a dedicated PDF service process (optimize O10), not more pools.

Current state
-------------
- **job runner:** ``pagedrop.core.jobs.SerializedJobRunner`` — fitz handlers
  take ``pdf_service.FITZ_LOCK`` (``holds_fitz=True``); Office / LibreOffice
  waits register ``holds_fitz=False`` and lock only around brief fitz validate.
  Long page loops (OCR, colour effects) also register ``holds_fitz=False`` and
  lock per page, calling ``yield_fitz_lock`` after each release; lossy compress
  runs in an owned child process and only its lossless path locks in-process.
  Stage/promote via ``TempManager``, paths only; never share fitz docs with
  ad-hoc UI pools.
- **viewer / UI pools:** ``pdf_service`` helpers or ``with FITZ_LOCK`` around
  open/work/close — not unlocked ``fitz.open`` from ``QThreadPool`` workers.
"""

from __future__ import annotations

import threading
import time
from typing import Any

# Process-wide gate for in-process PyMuPDF. Lives here (imports nothing from
# pdf_service / pdf_loader) so every core module can take it without a cycle;
# ``pdf_service.FITZ_LOCK`` is this same object. Must stay re-entrant.
FITZ_LOCK = threading.RLock()

# CPython's RLock is not fair: a thread that releases and straight away
# re-acquires usually wins over a sleeping waiter (such as the GUI thread).
_LOCK_YIELD_S = 0.001


def yield_fitz_lock() -> None:
    """Pause briefly after releasing ``FITZ_LOCK`` between pages of a long job.

    Call it outside the ``with FITZ_LOCK`` block so a waiting thread can take
    the lock before the job re-acquires it for the next page.
    """
    time.sleep(_LOCK_YIELD_S)

# Current QRunnable / pool sites that call fitz (audit).
# Each pool is maxThreadCount=1 and serializes via pdf_service.FITZ_LOCK
# (direct ``with FITZ_LOCK`` or public helpers that call ``pdf_service.call``).
WORKER_AUDIT: tuple[tuple[str, str], ...] = (
    (
        "EditorJobWorker",
        "ui/editor_jobs.py — pool max 1; paths/snapshots only, writer/extractor take FITZ_LOCK",
    ),
    (
        "ThumbnailWorker",
        "ui/thumbnail_grid.py — per-page via pdf_service.render_ref_png; pool max 1",
    ),
    (
        "PreviewRenderWorker",
        "ui/page_preview.py — via pdf_service.render_ref_png; pool max 1",
    ),
    (
        "ViewerRenderWorker",
        "ui/pdf_viewer.py — via pdf_service.render_ref_png under FITZ_LOCK; pool max 1",
    ),
    (
        "_ViewerSearchWorker",
        "ui/pdf_viewer.py — search_model per-page under FITZ_LOCK; search pool max 1",
    ),
    (
        "_MergeThumbnailWorker",
        "ui/merge_file_grid.py — per-page via render_stacked_page_pngs → pdf_service.render_ref_png; pool max 1",
    ),
    (
        "_ConvertThumbnailWorker",
        "ui/convert_file_grid.py — render_image_thumbnail_png under FITZ_LOCK; pool max 1",
    ),
    (
        "WatermarkPageRenderWorker",
        "ui/watermark_preview.py — via pdf_service under FITZ_LOCK; pool max 1",
    ),
    (
        "_CompareTextWorker",
        "ui/compare_window.py — compare_pdf_text_diff under FITZ_LOCK; pool max 1",
    ),
    (
        "_CompareRenderWorker",
        "ui/compare_window.py — pdf_service pane render under FITZ_LOCK; pool max 1",
    ),
    (
        "CompareWindow",
        "ui/compare_window.py — pdf_service pane render via _CompareRenderWorker; text-diff via _CompareTextWorker",
    ),
    (
        "_BlankDetectWorker",
        "ui/modify_tools_shell.py — detect_blank_pages under FITZ_LOCK; tool job pool max 1",
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
