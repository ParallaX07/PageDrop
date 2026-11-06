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
from tests.conftest import file_sha256


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
        "WatermarkPageRenderWorker",
        "_CompareRenderWorker",
        "CompareWindow",
        "_BlankDetectWorker",
    }
    for _name, note in WORKER_AUDIT:
        assert "FITZ_LOCK" in note or "pdf_service" in note
        # Pool workers stay max 1.
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


def test_compare_report_job_is_registered_under_fitz_lock(tmp_path: Path, monkeypatch) -> None:
    from dataclasses import asdict

    from pagedrop.core import pdf_tools
    from pagedrop.core.jobs import JobSpec, SerializedJobRunner
    from pagedrop.core.organize_jobs import register_organize_handlers
    from pagedrop.utils.temp_manager import TempManager

    original = tmp_path / "original.pdf"
    revised = tmp_path / "revised.pdf"
    _write_pdf(original)
    _write_pdf(revised)
    fingerprints = {
        "source_fingerprint_a": asdict(pdf_tools.source_fingerprint(original)),
        "source_fingerprint_b": asdict(pdf_tools.source_fingerprint(revised)),
    }
    lock_owned: list[bool] = []
    real_compare = pdf_tools._compare_documents

    def tracking_compare(*args, **kwargs):
        lock_owned.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_compare(*args, **kwargs)

    monkeypatch.setattr(pdf_tools, "_compare_documents", tracking_compare)
    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_organize_handlers(runner)
        assert runner._handlers["compare_report"].holds_fitz is True
        runner.run(
            JobSpec.create(
                "compare_report",
                inputs=[original, revised],
                output=tmp_path / "report.pdf",
                options={
                    "layout": "split",
                    "include_summary": False,
                    "include_revisions": False,
                    **fingerprints,
                },
            )
        )
        assert lock_owned == [True]
    finally:
        temp.cleanup()


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
    from pagedrop.ui.compare_window import _render_page_image

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
    image, _rect, _matrix = _render_page_image(str(pdf), 0, 64)
    assert not image.isNull()

    assert held_at_open, "expected at least one fitz.open"
    assert all(held_at_open), (
        f"fitz.open without FITZ_LOCK (owned flags={held_at_open})"
    )


def test_redact_edit_model_holds_fitz_lock_verify_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O17-a: redact_edit_model MuPDF opens own FITZ_LOCK; verify wait does not."""
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

    before = file_sha256(pdf)
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
    assert file_sha256(pdf) == before
    assert out.is_file() and out.resolve() != pdf.resolve()


def test_ui_fitz_pools_max_thread_count_one(qtbot) -> None:
    """Do not raise pool size to paper over MuPDF contention."""
    from pagedrop.ui.compare_window import _compare_render_pool, _compare_text_pool
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

    assert merge._file_grid._render_pool.maxThreadCount() == 1
    assert convert._file_grid._render_pool.maxThreadCount() == 1
    assert grid._render_pool.maxThreadCount() == 1
    assert preview._render_pool.maxThreadCount() == 1
    assert viewer._pool.maxThreadCount() == 1
    assert viewer._search_pool.maxThreadCount() == 1
    assert _compare_text_pool().maxThreadCount() == 1
    assert _compare_render_pool().maxThreadCount() == 1


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


def test_thumbnail_worker_continues_after_a_failed_page(tmp_path: Path) -> None:
    """One unreadable page is reported and the rest of the batch still renders."""
    good = tmp_path / "good.pdf"
    _write_pdf(good, pages=3)
    missing = tmp_path / "missing.pdf"
    pages = [
        (0, PageRef(str(good), 0)),
        (1, PageRef(str(missing), 0)),
        (2, PageRef(str(good), 1)),
    ]
    worker = ThumbnailWorker(
        pages, generation=1, width_px=64, is_cancelled=lambda _g: False
    )
    ready: list[int] = []
    failed: list[int] = []
    finished: list[int] = []
    worker.signals.page_ready.connect(lambda _g, index, _png: ready.append(index))
    worker.signals.error.connect(lambda _g, index, _msg: failed.append(index))
    worker.signals.finished.connect(finished.append)

    worker.run()

    assert ready == [0, 2]
    assert failed == [1]
    assert finished == [1]


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


def test_extract_page_refs_releases_lock_between_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O17-g: per-page extract lock so render can interleave mid multi-page save.

    Whole-loop ``with FITZ_LOCK`` made mid-extract waits track remaining pages;
    per-page hold keeps wait near one page save. Also asserts Document.save
    runs under lock more than once (not one long hold).
    """
    import threading
    import time

    from pagedrop.core.page_extractor import extract_page_refs_to_files
    from pagedrop.core.pdf_service import render_ref_png

    pdf = tmp_path / "extract.pdf"
    _write_pdf(pdf, pages=12)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    page_n = {"n": 0}
    mid = threading.Event()
    real_save = fitz.Document.save
    extract_tid = {"id": None}
    saves_owned: list[bool] = []

    def slow_save(self: fitz.Document, *args: object, **kwargs: object) -> None:
        page_n["n"] += 1
        saves_owned.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        if page_n["n"] == 3:
            mid.set()
        if threading.get_ident() == extract_tid["id"]:
            time.sleep(0.025)
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "save", slow_save)

    waits: list[float] = []

    def viewer() -> None:
        assert mid.wait(timeout=10), "extract never reached mid page"
        t0 = time.perf_counter()
        assert render_ref_png(PageRef(str(pdf), 0), 64)
        waits.append(time.perf_counter() - t0)

    refs = [PageRef(str(pdf), i) for i in range(12)]
    extract_tid["id"] = threading.get_ident()
    vt = threading.Thread(target=viewer)
    vt.start()
    paths = extract_page_refs_to_files(refs, out_dir, "doc")
    vt.join(timeout=30)

    assert len(paths) == 12
    assert len(saves_owned) >= 12
    assert all(saves_owned), f"save without FITZ_LOCK (owned={saves_owned})"
    assert waits, "viewer thread did not complete"
    # Remaining whole-loop would be ~9×25ms ≈ 225ms; per-page stays ~one page.
    assert waits[0] < 0.12, (
        f"viewer blocked {waits[0]:.3f}s behind extract "
        "(expected per-page interleave)"
    )


def test_pdf_loader_methods_hold_fitz_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every PdfLoader entry point touches MuPDF only while owning FITZ_LOCK."""
    from pagedrop.core import pdf_loader as loader_module
    from pagedrop.core.pdf_loader import PdfLoader

    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, pages=2)

    owned: dict[str, list[bool]] = {}

    def spy(name: str, real):
        def wrapper(*args: object, **kwargs: object):
            owned.setdefault(name, []).append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
            return real(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(fitz, "open", spy("open", fitz.open))
    monkeypatch.setattr(fitz.Document, "__len__", spy("len", fitz.Document.__len__))
    monkeypatch.setattr(fitz.Document, "close", spy("close", fitz.Document.close))
    for attr in ("unrotated_page_geom", "page_size_mm", "render_page_png"):
        monkeypatch.setattr(loader_module, attr, spy(attr, getattr(loader_module, attr)))

    before = file_sha256(pdf)
    loader = PdfLoader(str(pdf))
    assert loader.page_count == 2
    assert loader.page_size_pt(0) == (200.0, 200.0)
    assert loader.page_rotation(1) == 0
    assert loader.page_size_mm(0) == (71, 71)
    assert loader.render_page(0, 40)
    loader.close()

    assert set(owned) == {
        "open",
        "len",
        "close",
        "unrotated_page_geom",
        "page_size_mm",
        "render_page_png",
    }
    for name, flags in owned.items():
        assert all(flags), f"{name} ran without FITZ_LOCK (owned flags={flags})"
    assert file_sha256(pdf) == before


def test_editor_save_verification_open_holds_fitz_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handler is registered holds_fitz=False; its own verify open must lock."""
    from pagedrop.core.editor_jobs import register_editor_handlers
    from pagedrop.core.jobs import JobSpec, SerializedJobRunner
    from pagedrop.core.pdf_editor import PdfEditModel
    from pagedrop.utils.temp_manager import TempManager

    pdf = tmp_path / "src.pdf"
    out = tmp_path / "saved.pdf"
    _write_pdf(pdf, pages=2)
    before = file_sha256(pdf)

    held_at_open: list[bool] = []
    real_open = fitz.open

    def tracking_open(*args: object, **kwargs: object) -> fitz.Document:
        held_at_open.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracking_open)
    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_editor_handlers(runner)
        assert runner._handlers["editor_save"].holds_fitz is False
        runner.run(
            JobSpec.create(
                "editor_save",
                inputs=[pdf],
                output=out,
                options={"model": PdfEditModel(str(pdf), 2).snapshot_for_write()},
            )
        )
    finally:
        temp.cleanup()

    # Writer opens the source, then the handler opens the staged output.
    assert len(held_at_open) >= 2
    assert all(held_at_open), (
        f"fitz.open without FITZ_LOCK (owned flags={held_at_open})"
    )
    assert out.is_file() and out.resolve() != pdf.resolve()
    assert file_sha256(pdf) == before


def test_metadata_and_bookmark_probes_hold_fitz_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qtbot, isolated_settings
) -> None:
    """GUI-thread metadata / bookmark reads in the tool shells must own FITZ_LOCK."""
    from PyQt6.QtWidgets import QComboBox, QMessageBox

    from pagedrop.ui.modify_tools_shell import open_modify_shell
    from pagedrop.ui.organize_shell import open_organize_shell
    from pagedrop.ui.tools_window import ToolsWindow

    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf)
    before = file_sha256(pdf)

    held_at_open: list[bool] = []
    real_open = fitz.open

    def tracking_open(*args: object, **kwargs: object) -> fitz.Document:
        held_at_open.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracking_open)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    tools = ToolsWindow()
    qtbot.addWidget(tools)

    meta_shell = open_organize_shell(tools, "metadata")
    assert meta_shell is not None
    qtbot.addWidget(meta_shell)
    meta_shell.drop_zone.set_paths([str(pdf)])  # load_meta
    assert len(held_at_open) >= 1
    seen = len(held_at_open)

    marks_shell = open_modify_shell(tools, "bookmarks")
    assert marks_shell is not None
    qtbot.addWidget(marks_shell)
    marks_shell.drop_zone.set_paths([str(pdf)])  # refresh_status
    assert len(held_at_open) > seen
    seen = len(held_at_open)

    action = marks_shell._options_host.findChildren(QComboBox)[0]
    action.setCurrentIndex(action.findData("toc_page"))
    marks_shell._run_btn.click()  # on_run: bookmark probe before the TOC job
    assert len(held_at_open) > seen

    assert all(held_at_open), (
        f"fitz.open without FITZ_LOCK (owned flags={held_at_open})"
    )
    assert file_sha256(pdf) == before
    meta_shell.close()
    marks_shell.close()
    tools.close()


def test_pdf_loader_cached_geometry_does_not_wait_for_fitz_lock(
    tmp_path: Path,
) -> None:
    """A warmed geometry read is a plain dict hit and must not stall behind a job."""
    import threading

    from pagedrop.core.pdf_loader import PdfLoader

    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf)
    loader = PdfLoader(str(pdf))
    expected = (
        loader.page_size_pt(0),
        loader.page_rotation(0),
        loader.page_size_mm(0),
    )

    held = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with FITZ_LOCK:
            held.set()
            release.wait(timeout=30)

    holder = threading.Thread(target=hold_lock, daemon=True)
    holder.start()
    results: list[tuple] = []
    try:
        assert held.wait(timeout=10)

        def read_cached() -> None:
            results.append(
                (loader.page_size_pt(0), loader.page_rotation(0), loader.page_size_mm(0))
            )

        reader = threading.Thread(target=read_cached, daemon=True)
        reader.start()
        reader.join(timeout=5)
        assert not reader.is_alive(), "cached geometry read blocked on FITZ_LOCK"
        assert results == [expected]
    finally:
        release.set()
        holder.join(timeout=10)
        loader.close()


# --- Long jobs lock per page, not for the whole run ---------------------------


def _track_fitz_lock(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[bool]]:
    """Record whether FITZ_LOCK is owned at every open / save / close."""
    owned: dict[str, list[bool]] = {"open": [], "save": [], "close": []}

    def spy(name: str, real):
        def wrapper(*args: object, **kwargs: object):
            owned[name].append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
            return real(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(fitz, "open", spy("open", fitz.open))
    monkeypatch.setattr(fitz.Document, "save", spy("save", fitz.Document.save))
    monkeypatch.setattr(fitz.Document, "close", spy("close", fitz.Document.close))
    return owned


def _run_with_lock_waiter(mid, run_job) -> float:
    """Run *run_job*; a thread takes FITZ_LOCK once *mid* is set. Returns its wait."""
    import threading
    import time

    waits: list[float] = []

    def waiter() -> None:
        assert mid.wait(timeout=10), "job never reached a middle page"
        t0 = time.perf_counter()
        with FITZ_LOCK:
            pass
        waits.append(time.perf_counter() - t0)

    thread = threading.Thread(target=waiter)
    thread.start()
    try:
        run_job()
    finally:
        thread.join(timeout=30)
    assert waits, "waiter thread did not acquire FITZ_LOCK"
    return waits[0]


def _assert_all_owned(owned: dict[str, list[bool]]) -> None:
    for name, flags in owned.items():
        assert flags, f"no fitz {name} observed"
        assert all(flags), f"fitz {name} ran without FITZ_LOCK (owned={flags})"


def test_ocr_job_locks_per_page_and_waiter_waits_one_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    from pagedrop.core.capabilities import clear_cache
    from pagedrop.core.jobs import JobSpec, SerializedJobRunner
    from pagedrop.core.ocr_jobs import register_ocr_handlers
    from pagedrop.utils.temp_manager import TempManager

    pdf = tmp_path / "scan.pdf"
    _write_pdf(pdf, pages=12)
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "eng.traineddata").write_bytes(b"x")
    out = tmp_path / "ocr.pdf"
    before = file_sha256(pdf)

    tiny = fitz.open()
    tiny.new_page(width=72, height=72)
    tiny_bytes = tiny.tobytes()
    tiny.close()

    page_n = {"n": 0}
    mid = threading.Event()
    ocr_owned: list[bool] = []

    def slow_ocr(self: fitz.Pixmap, *args: object, **kwargs: object) -> bytes:
        page_n["n"] += 1
        ocr_owned.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        if page_n["n"] == 3:
            mid.set()
        time.sleep(0.025)
        return tiny_bytes

    monkeypatch.setattr(fitz.Pixmap, "pdfocr_tobytes", slow_ocr)
    owned = _track_fitz_lock(monkeypatch)

    progress_owned: list[bool] = []
    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_ocr_handlers(runner)
        assert runner._handlers["ocr_pdf"].holds_fitz is False
        assert runner._handlers["extract_tables"].holds_fitz is True

        def run_job() -> None:
            runner.run(
                JobSpec.create(
                    "ocr_pdf",
                    inputs=[pdf],
                    output=out,
                    options={"tessdata": str(tessdata), "dpi": 72},
                ),
                progress=lambda *_a: progress_owned.append(
                    FITZ_LOCK._is_owned()  # type: ignore[attr-defined]
                ),
            )

        wait = _run_with_lock_waiter(mid, run_job)
    finally:
        temp.cleanup()
        clear_cache()
        monkeypatch.undo()  # the checks below open files outside the job

    assert out.is_file() and out.resolve() != pdf.resolve()
    assert file_sha256(pdf) == before
    with fitz.open(str(out)) as result:
        assert result.page_count == 12
    assert len(ocr_owned) == 12 and all(ocr_owned)
    _assert_all_owned(owned)
    assert progress_owned and not any(progress_owned), "runner held FITZ_LOCK"
    # A whole-job hold would leave ~9 pages x 25 ms; per-page stays near one page.
    assert wait < 0.12, f"waiter blocked {wait:.3f}s behind OCR job"


@pytest.mark.parametrize(
    ("effect", "slow_attr"),
    [("greyscale", "recolor"), ("invert", "get_pixmap"), ("background", "new_shape")],
)
def test_color_effects_job_locks_per_page_and_waiter_waits_one_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, effect: str, slow_attr: str
) -> None:
    import threading
    import time

    from pagedrop.core.jobs import JobSpec, SerializedJobRunner
    from pagedrop.core.modify_jobs import register_modify_handlers
    from pagedrop.utils.temp_manager import TempManager

    pdf = tmp_path / "pages.pdf"
    _write_pdf(pdf, pages=12)
    out = tmp_path / "effect.pdf"
    before = file_sha256(pdf)

    page_n = {"n": 0}
    mid = threading.Event()
    page_owned: list[bool] = []
    real = getattr(fitz.Page, slow_attr)

    def slow_page_op(self: fitz.Page, *args: object, **kwargs: object):
        page_n["n"] += 1
        page_owned.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        if page_n["n"] == 3:
            mid.set()
        time.sleep(0.025)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, slow_attr, slow_page_op)
    owned = _track_fitz_lock(monkeypatch)

    progress_owned: list[bool] = []
    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_modify_handlers(runner)
        assert runner._handlers["color_effects"].holds_fitz is False
        assert runner._handlers["crop"].holds_fitz is True

        def run_job() -> None:
            runner.run(
                JobSpec.create(
                    "color_effects",
                    inputs=[pdf],
                    output=out,
                    options={"effect": effect, "dpi": 36},
                ),
                progress=lambda *_a: progress_owned.append(
                    FITZ_LOCK._is_owned()  # type: ignore[attr-defined]
                ),
            )

        wait = _run_with_lock_waiter(mid, run_job)
    finally:
        temp.cleanup()
        monkeypatch.undo()  # the checks below open files outside the job

    assert out.is_file() and out.resolve() != pdf.resolve()
    assert file_sha256(pdf) == before
    with fitz.open(str(out)) as result:
        assert result.page_count == 12
    assert len(page_owned) == 12 and all(page_owned)
    _assert_all_owned(owned)
    assert progress_owned and not any(progress_owned), "runner held FITZ_LOCK"
    assert wait < 0.12, f"waiter blocked {wait:.3f}s behind {effect} job"


@pytest.mark.parametrize("job", ["ocr_pdf", "color_effects"])
def test_long_job_cancel_releases_documents_under_fitz_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, job: str
) -> None:
    """Cancel mid-run still closes the job's documents while owning FITZ_LOCK."""
    from pagedrop.core.capabilities import clear_cache
    from pagedrop.core.jobs import CancelToken, JobCancelledError, JobSpec, SerializedJobRunner
    from pagedrop.core.modify_jobs import register_modify_handlers
    from pagedrop.core.ocr_jobs import register_ocr_handlers
    from pagedrop.utils.temp_manager import TempManager

    pdf = tmp_path / "pages.pdf"
    _write_pdf(pdf, pages=6)
    out = tmp_path / "out.pdf"
    before = file_sha256(pdf)
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "eng.traineddata").write_bytes(b"x")
    token = CancelToken()
    calls = {"n": 0}

    tiny = fitz.open()
    tiny.new_page(width=72, height=72)
    tiny_bytes = tiny.tobytes()
    tiny.close()

    def cancelling_ocr(self: fitz.Pixmap, *args: object, **kwargs: object) -> bytes:
        calls["n"] += 1
        if calls["n"] == 2:
            token.cancel()
        return tiny_bytes

    real_get_pixmap = fitz.Page.get_pixmap

    def cancelling_pixmap(self: fitz.Page, *args: object, **kwargs: object):
        calls["n"] += 1
        if calls["n"] == 2:
            token.cancel()
        return real_get_pixmap(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Pixmap, "pdfocr_tobytes", cancelling_ocr)
    monkeypatch.setattr(fitz.Page, "get_pixmap", cancelling_pixmap)
    owned = _track_fitz_lock(monkeypatch)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_ocr_handlers(runner)
        register_modify_handlers(runner)
        options = (
            {"tessdata": str(tessdata), "dpi": 72}
            if job == "ocr_pdf"
            else {"effect": "invert", "dpi": 36}
        )
        with pytest.raises(JobCancelledError):
            runner.run(
                JobSpec.create(job, inputs=[pdf], output=out, options=options),
                cancel=token,
            )
        assert not any(temp.get_dir().glob("job_*"))
    finally:
        temp.cleanup()
        clear_cache()
        monkeypatch.undo()

    assert not out.exists()
    assert file_sha256(pdf) == before
    assert owned["save"] == []
    assert owned["open"] and owned["close"]
    assert all(owned["open"]) and all(owned["close"])
