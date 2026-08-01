"""PyMuPDF concurrency policy contract."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pagedrop.core import thread_policy
from pagedrop.core.image_to_pdf import images_to_single_pdf
from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_service import FITZ_LOCK, page_count
from pagedrop.core.pdf_writer import merge_pdf_files
from pagedrop.core.thread_policy import (
    WORKER_AUDIT,
    ensure_no_fitz_document,
    is_fitz_document,
)
from pagedrop.ui.convert_file_grid import render_image_thumbnail_png
from pagedrop.ui.page_preview import PreviewRenderWorker
from pagedrop.ui.stacked_thumbnail import render_stacked_page_pngs
from pagedrop.ui.thumbnail_grid import ThumbnailWorker


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
        "_ViewerSearchWorker",
        "_MergeThumbnailWorker",
        "_ConvertThumbnailWorker",
        "_MergeWorker",
        "_ConvertWorker",
        "WatermarkPageRenderWorker",
        "CompareWindow",
        "_BlankDetectWorker",
    }
    for _name, note in WORKER_AUDIT:
        assert "FITZ_LOCK" in note or "pdf_service" in note
        # Pool workers stay max 1; GUI-thread Compare sites are not pooled.
        if "pool" in note.lower():
            assert "max 1" in note


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


def _write_pdf(path: Path, pages: int = 1) -> None:
    doc = fitz.open()
    try:
        for _ in range(pages):
            doc.new_page(width=200, height=200)
        doc.save(str(path))
    finally:
        doc.close()


def _write_png(path: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=40, height=40)
        page.draw_rect(page.rect, color=(0.5, 0.5, 0.5), fill=(0.5, 0.5, 0.5))
        page.get_pixmap().save(str(path))
    finally:
        doc.close()


def test_ui_pool_fitz_opens_hold_fitz_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """Every UI-pool fitz.open must run while FITZ_LOCK is owned.

    Covers ThumbnailWorker, PreviewRenderWorker (via pdf_service), merge stack
    thumbs, convert image thumbs, and merge/convert write paths.
    """
    pdf = tmp_path / "doc.pdf"
    png = tmp_path / "img.png"
    out_merge = tmp_path / "merged.pdf"
    out_convert = tmp_path / "from_img.pdf"
    _write_pdf(pdf, pages=2)
    _write_png(png)

    held_at_open: list[bool] = []
    real_open = fitz.open

    def tracking_open(*args: object, **kwargs: object) -> fitz.Document:
        # CPython RLock: True iff the current thread owns FITZ_LOCK.
        held_at_open.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracking_open)

    # ThumbnailWorker — per-page via pdf_service.render_ref_png → FITZ_LOCK
    thumb = ThumbnailWorker(
        [(0, PageRef(str(pdf), 0)), (1, PageRef(str(pdf), 1))],
        generation=1,
        width_px=64,
        is_cancelled=lambda _g: False,
    )
    thumb.run()

    # PreviewRenderWorker — pdf_service.render_ref_png → call() → FITZ_LOCK
    preview = PreviewRenderWorker(
        str(pdf),
        0,
        logical_page=0,
        width_px=64,
        generation=1,
        is_cancelled=lambda _g: False,
    )
    preview.run()

    assert render_stacked_page_pngs(str(pdf), 2, width_px=40)
    assert render_image_thumbnail_png(str(png), 40)

    # Same gate the merge/convert write workers take around core helpers.
    with FITZ_LOCK:
        merge_pdf_files([str(pdf)], str(out_merge))
        images_to_single_pdf([str(png)], str(out_convert))

    assert held_at_open, "expected at least one fitz.open"
    assert all(held_at_open), (
        f"fitz.open without FITZ_LOCK (owned flags={held_at_open})"
    )
    assert out_merge.is_file() and out_convert.is_file()


def test_tool_page_count_concurrent_with_thumb_holds_fitz_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GUI tool page_count while a thumb worker runs — every open owns FITZ_LOCK."""
    import threading

    from pagedrop.core.pdf_service import invalidate_doc_cache

    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=4)
    invalidate_doc_cache()

    held_at_open: list[bool] = []
    real_open = fitz.open

    def tracking_open(*args: object, **kwargs: object) -> fitz.Document:
        held_at_open.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracking_open)

    err: list[BaseException] = []

    def run_thumbs() -> None:
        try:
            ThumbnailWorker(
                [(i, PageRef(str(pdf), i)) for i in range(4)],
                generation=1,
                width_px=48,
                is_cancelled=lambda _g: False,
            ).run()
        except BaseException as exc:  # pragma: no cover
            err.append(exc)

    t = threading.Thread(target=run_thumbs, daemon=True)
    t.start()
    assert page_count(str(pdf)) == 4
    t.join(timeout=30)
    assert not t.is_alive()
    assert not err
    assert held_at_open, "expected at least one fitz.open"
    assert all(held_at_open), (
        f"fitz.open without FITZ_LOCK (owned flags={held_at_open})"
    )


def test_merge_validate_and_preflight_concurrent_with_thumb_holds_fitz_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """O17-c: Merge page-count + job preflight + preview open own FITZ_LOCK.

    Concurrent with a thumb worker so unlocked GUI probes would race.
    """
    import threading

    from pagedrop.core.jobs.preflight import preflight_pdf_inputs
    from pagedrop.core.pdf_service import invalidate_doc_cache
    from pagedrop.ui.merge_window import MergeWindow
    from pagedrop.ui.result_actions import preview_pdf

    pdf = tmp_path / "probe.pdf"
    _write_pdf(pdf, pages=4)
    invalidate_doc_cache()

    held_at_open: list[bool] = []
    real_open = fitz.open

    def tracking_open(*args: object, **kwargs: object) -> fitz.Document:
        held_at_open.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracking_open)

    err: list[BaseException] = []

    def run_thumbs() -> None:
        try:
            ThumbnailWorker(
                [(i, PageRef(str(pdf), i)) for i in range(4)],
                generation=1,
                width_px=48,
                is_cancelled=lambda _g: False,
            ).run()
        except BaseException as exc:  # pragma: no cover
            err.append(exc)

    def prompt(_filename: str, _incorrect: bool) -> str | None:
        raise AssertionError("plain PDF must not prompt")

    t = threading.Thread(target=run_thumbs, daemon=True)
    t.start()
    assert MergeWindow._page_count(str(pdf)) == 4
    preflight_pdf_inputs([pdf], prompt=prompt)
    assert preview_pdf(pdf) is True
    t.join(timeout=30)
    assert not t.is_alive()
    assert not err
    assert held_at_open, "expected at least one fitz.open"
    assert all(held_at_open), (
        f"fitz.open without FITZ_LOCK (owned flags={held_at_open})"
    )


def test_unlocked_fitz_open_fails_lock_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity: an unlocked open is detectable by the same probe."""
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf)

    held_at_open: list[bool] = []
    real_open = fitz.open

    def tracking_open(*args: object, **kwargs: object) -> fitz.Document:
        held_at_open.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracking_open)
    doc = fitz.open(str(pdf))
    doc.close()
    assert held_at_open == [False]


def test_save_as_extract_compare_inspect_hold_fitz_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """GUI-thread write/extract/compare text-diff/inspect must own FITZ_LOCK."""
    from pagedrop.core.image_to_pdf import inspect_image
    from pagedrop.core.page_extractor import extract_page_refs_to_files
    from pagedrop.core.pdf_editor import PdfEditModel
    from pagedrop.core.pdf_tools import compare_pdf_text_diff
    from pagedrop.core.pdf_writer import write_pdf
    from pagedrop.ui.compare_window import _render_page_pixmap

    pdf = tmp_path / "doc.pdf"
    png = tmp_path / "img.png"
    out = tmp_path / "out.pdf"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    _write_pdf(pdf, pages=2)
    _write_png(png)

    held_at_open: list[bool] = []
    real_open = fitz.open

    def tracking_open(*args: object, **kwargs: object) -> fitz.Document:
        held_at_open.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracking_open)

    write_pdf(PdfEditModel(str(pdf), 2), str(out))
    extract_page_refs_to_files(
        [PageRef(str(pdf), 0)],
        extract_dir,
        "page",
    )
    compare_pdf_text_diff(str(pdf), str(pdf))
    inspect_image(str(png))
    pix, _rect = _render_page_pixmap(str(pdf), 0, 64)
    assert not pix.isNull()

    assert held_at_open, "expected at least one fitz.open"
    assert all(held_at_open), (
        f"fitz.open without FITZ_LOCK (owned flags={held_at_open})"
    )


def test_redact_edit_model_holds_fitz_lock_verify_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O17-a: redact_edit_model MuPDF opens own FITZ_LOCK; verify wait does not."""
    import hashlib

    from pagedrop.core import redact as redact_module
    from pagedrop.core.pdf_editor import PdfEditModel
    from pagedrop.core.redact import RedactionRegion, redact_edit_model

    secret = "TOPSECRET_ZZ9"
    pdf = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        page.insert_text((40, 80), f"Hello {secret} world", fontsize=14)
        doc.save(str(pdf))
    finally:
        doc.close()

    before = hashlib.sha256(pdf.read_bytes()).hexdigest()
    rect_doc = fitz.open(str(pdf))
    try:
        hit = rect_doc[0].search_for(secret)[0]
        rect = (float(hit.x0), float(hit.y0), float(hit.x1), float(hit.y1))
    finally:
        rect_doc.close()

    held_at_open: list[bool] = []
    verify_owned: list[bool] = []
    real_open = fitz.open
    real_verify = redact_module.verify_redacted_pdf_fresh_process

    def tracking_open(*args: object, **kwargs: object) -> fitz.Document:
        held_at_open.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_open(*args, **kwargs)

    def tracking_verify(*args: object, **kwargs: object):
        verify_owned.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_verify(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracking_open)
    monkeypatch.setattr(
        redact_module, "verify_redacted_pdf_fresh_process", tracking_verify
    )

    out = tmp_path / "redacted.pdf"
    redact_edit_model(
        PdfEditModel(str(pdf), 1),
        out,
        [RedactionRegion(0, rect)],
        verify=True,
    )

    assert held_at_open, "expected at least one fitz.open during redact"
    assert all(held_at_open), (
        f"fitz.open without FITZ_LOCK (owned flags={held_at_open})"
    )
    assert verify_owned == [False], (
        f"verify must run outside FITZ_LOCK (owned flags={verify_owned})"
    )
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == before
    assert out.is_file() and out.resolve() != pdf.resolve()


def test_ui_fitz_pools_max_thread_count_one(qtbot) -> None:
    """Do not raise pool size to paper over MuPDF contention."""
    from pagedrop.ui.compare_window import _compare_text_pool
    from pagedrop.ui.convert_window import ConvertWindow
    from pagedrop.ui.merge_window import MergeWindow
    from pagedrop.ui.page_preview import PagePreviewWidget
    from pagedrop.ui.pdf_viewer import PdfViewerWidget
    from pagedrop.ui.thumbnail_grid import ThumbnailGrid

    merge = MergeWindow()
    convert = ConvertWindow()
    qtbot.addWidget(merge)
    qtbot.addWidget(convert)

    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    preview = PagePreviewWidget()
    qtbot.addWidget(preview)
    viewer = PdfViewerWidget()
    qtbot.addWidget(viewer)

    assert merge._merge_pool.maxThreadCount() == 1
    assert convert._convert_pool.maxThreadCount() == 1
    assert merge._file_grid._render_pool.maxThreadCount() == 1
    assert convert._file_grid._render_pool.maxThreadCount() == 1
    assert grid._render_pool.maxThreadCount() == 1
    assert preview._render_pool.maxThreadCount() == 1
    assert viewer._pool.maxThreadCount() == 1
    assert viewer._search_pool.maxThreadCount() == 1
    assert _compare_text_pool().maxThreadCount() == 1


def test_thumbnail_worker_releases_lock_between_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O15: per-page lock so a viewer render can interleave mid thumb batch.

    Whole-batch hold made mid-window viewer waits track remaining pages; with
    per-page ``render_ref_png``, wait stays near one page render.
    """
    import threading
    import time

    from pagedrop.core import pdf_service
    from pagedrop.core.pdf_service import render_ref_png

    pdf = tmp_path / "batch.pdf"
    _write_pdf(pdf, pages=12)

    page_n = {"n": 0}
    mid = threading.Event()
    real_png = pdf_service.render_page_png
    thumb_tid = {"id": None}

    def slow_png(*args: object, **kwargs: object) -> bytes:
        page_n["n"] += 1
        if page_n["n"] == 3:
            mid.set()
        # Only stall the thumb batch — viewer path must stay fast so waits
        # measure lock contention, not the injected sleep itself.
        if threading.get_ident() == thumb_tid["id"]:
            time.sleep(0.025)
        return real_png(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pdf_service, "render_page_png", slow_png)

    waits: list[float] = []

    def viewer() -> None:
        assert mid.wait(timeout=10), "thumb batch never reached mid page"
        t0 = time.perf_counter()
        assert render_ref_png(PageRef(str(pdf), 0), 64)
        waits.append(time.perf_counter() - t0)

    pages = [(i, PageRef(str(pdf), i)) for i in range(12)]
    worker = ThumbnailWorker(
        pages,
        generation=1,
        width_px=64,
        is_cancelled=lambda _g: False,
    )
    thumb_tid["id"] = threading.get_ident()  # worker.run() on this thread
    vt = threading.Thread(target=viewer)
    vt.start()
    worker.run()
    vt.join(timeout=30)

    assert waits, "viewer thread did not complete"
    # Remaining whole-batch would be ~9×25ms ≈ 225ms; per-page stays ~one page.
    assert waits[0] < 0.12, (
        f"viewer blocked {waits[0]:.3f}s behind thumb batch "
        "(expected per-page interleave)"
    )


def test_search_model_releases_lock_between_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O17-d: per-page search lock so render_ref_png can interleave mid Find.

    Whole-doc ``call(_body)`` made mid-search waits track remaining pages;
    per-page ``call`` keeps wait near one page. Also asserts ``call`` acquire
    count > 1 on a multi-page search (not one long hold).
    """
    import threading
    import time

    from pagedrop.core.pdf_editor import PdfEditModel
    from pagedrop.core.pdf_service import render_ref_png, search_model

    pdf = tmp_path / "search.pdf"
    doc = fitz.open()
    try:
        for i in range(12):
            page = doc.new_page(width=200, height=200)
            page.insert_text((72, 72), f"token-{i}")
        doc.save(str(pdf))
    finally:
        doc.close()

    model = PdfEditModel(str(pdf), 12)
    page_n = {"n": 0}
    mid = threading.Event()
    real_search = fitz.Page.search_for
    search_tid = {"id": None}

    def slow_search(self: fitz.Page, *args: object, **kwargs: object) -> list:
        page_n["n"] += 1
        if page_n["n"] == 3:
            mid.set()
        if threading.get_ident() == search_tid["id"]:
            time.sleep(0.025)
        return real_search(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "search_for", slow_search)

    from pagedrop.core import pdf_service as svc

    acquires = {"n": 0}
    real_call = svc.call

    def counting_call(fn: object, *args: object, **kwargs: object) -> object:
        acquires["n"] += 1
        return real_call(fn, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(svc, "call", counting_call)

    waits: list[float] = []

    def viewer() -> None:
        assert mid.wait(timeout=10), "search never reached mid page"
        t0 = time.perf_counter()
        assert render_ref_png(PageRef(str(pdf), 0), 64)
        waits.append(time.perf_counter() - t0)

    search_tid["id"] = threading.get_ident()
    vt = threading.Thread(target=viewer)
    vt.start()
    hits = search_model(model, "token")
    vt.join(timeout=30)

    assert len(hits) == 12
    # 12 page bodies + 1 render_ref_png (and possibly cache opens already done).
    assert acquires["n"] > 1, (
        f"expected per-page call() acquires, got {acquires['n']}"
    )
    assert waits, "viewer thread did not complete"
    # Remaining whole-doc would be ~9×25ms ≈ 225ms; per-page stays ~one page.
    assert waits[0] < 0.12, (
        f"viewer blocked {waits[0]:.3f}s behind search "
        "(expected per-page interleave)"
    )
