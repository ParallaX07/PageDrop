"""PyMuPDF concurrency policy contract."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pagedrop.core import thread_policy
from pagedrop.core.image_to_pdf import images_to_single_pdf
from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_service import FITZ_LOCK
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
        "_MergeThumbnailWorker",
        "_ConvertThumbnailWorker",
        "_MergeWorker",
        "_ConvertWorker",
        "WatermarkPageRenderWorker",
        "CompareWindow",
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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

    # ThumbnailWorker — direct fitz.open under FITZ_LOCK
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    assert _compare_text_pool().maxThreadCount() == 1
