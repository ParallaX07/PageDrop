"""Core contract tests for the serialized PDF service."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pagedrop.core import pdf_service
from pagedrop.core.jobs.runner import SerializedJobRunner
from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_service import (
    FITZ_LOCK,
    PageGeom,
    doc_cache_size,
    invalidate_doc_cache,
    page_geometry,
    page_links,
    page_text_dict,
    render_ref_png,
    search_model,
)
from pagedrop.core.thread_policy import is_fitz_document


@pytest.fixture(autouse=True)
def _clear_doc_cache() -> None:
    invalidate_doc_cache()
    yield
    invalidate_doc_cache()


def _text_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    try:
        for text in lines:
            page = doc.new_page()
            page.insert_text((72, 72), text)
        doc.save(str(path))
    finally:
        doc.close()


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
    _text_pdf(path, ["first", "second", "third"])

    model = PdfEditModel(str(path), 3)
    model.move_pages([2], 0)  # third, first, second
    hits = search_model(model, "third")
    assert len(hits) == 1
    assert hits[0].logical_page == 0


def test_doc_cache_reuses_open_across_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "reuse.pdf"
    _text_pdf(path, ["Alpha", "Beta"])
    ref = PageRef(str(path), 0)

    open_calls = {"n": 0}
    real_open = fitz.open

    def counting_open(*args: object, **kwargs: object) -> fitz.Document:
        open_calls["n"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", counting_open)

    png = render_ref_png(ref, 64)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert open_calls["n"] == 1
    assert doc_cache_size() == 1

    geom = page_geometry(str(path), 0)
    assert isinstance(geom, PageGeom)
    assert geom.width > 0
    text = page_text_dict(ref)
    assert isinstance(text, dict)
    links = page_links(ref)
    assert isinstance(links, list)
    hits = search_model(PdfEditModel(str(path), 2), "Alpha")
    assert len(hits) == 1

    # One shared owner — helpers must not reopen or keep a parallel map.
    assert open_calls["n"] == 1
    assert doc_cache_size() == 1
    assert not is_fitz_document(png)
    assert not is_fitz_document(geom)
    assert not is_fitz_document(text)
    assert not is_fitz_document(links)
    assert not is_fitz_document(hits)


def test_doc_cache_lru_max_eight(tmp_path: Path) -> None:
    paths = []
    for i in range(pdf_service._DOC_CACHE_MAX + 1):
        path = tmp_path / f"p{i}.pdf"
        _text_pdf(path, [f"page-{i}"])
        paths.append(path)
        page_geometry(str(path), 0)

    assert doc_cache_size() == pdf_service._DOC_CACHE_MAX
    # Oldest path evicted; touching it again re-opens and bumps size back to max.
    page_geometry(str(paths[0]), 0)
    assert doc_cache_size() == pdf_service._DOC_CACHE_MAX


def test_doc_cache_idle_ttl_evicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ttl.pdf"
    _text_pdf(path, ["ttl"])

    clock = {"t": 100.0}
    monkeypatch.setattr(pdf_service.time, "monotonic", lambda: clock["t"])

    open_calls = {"n": 0}
    real_open = fitz.open

    def counting_open(*args: object, **kwargs: object) -> fitz.Document:
        open_calls["n"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", counting_open)

    page_geometry(str(path), 0)
    assert open_calls["n"] == 1
    assert doc_cache_size() == 1

    clock["t"] = 100.0 + pdf_service._DOC_CACHE_TTL_S + 1.0
    page_geometry(str(path), 0)  # idle purge then reopen
    assert open_calls["n"] == 2
    assert doc_cache_size() == 1


def test_invalidate_doc_cache_forces_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "inv.pdf"
    _text_pdf(path, ["inv"])
    ref = PageRef(str(path), 0)

    open_calls = {"n": 0}
    real_open = fitz.open

    def counting_open(*args: object, **kwargs: object) -> fitz.Document:
        open_calls["n"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", counting_open)

    render_ref_png(ref, 32)
    assert open_calls["n"] == 1
    invalidate_doc_cache(str(path))
    assert doc_cache_size() == 0
    render_ref_png(ref, 32)
    assert open_calls["n"] == 2


def _ocg_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page()
        a = doc.add_ocg("Layer A", on=True)
        b = doc.add_ocg("Layer B", on=True)
        page.insert_text((72, 72), "AAAA", oc=a)
        page.insert_text((72, 120), "BBBB", oc=b)
        doc.save(str(path))
    finally:
        doc.close()


def test_ocg_render_does_not_poison_doc_cache(tmp_path: Path) -> None:
    from pagedrop.core.pdf_service import layers_for_path

    path = tmp_path / "layers.pdf"
    _ocg_pdf(path)
    ref = PageRef(str(path), 0)

    before = [(layer.number, layer.visible) for layer in layers_for_path(str(path))]
    assert before == [(0, True), (1, True)]

    # Hide Layer A for one render — must not stick on the shared cached doc.
    png_hidden = render_ref_png(ref, 128, ocg_on=frozenset({1}))
    assert png_hidden[:8] == b"\x89PNG\r\n\x1a\n"

    after = [(layer.number, layer.visible) for layer in layers_for_path(str(path))]
    assert after == before

    png_default = render_ref_png(ref, 128)
    assert png_default != png_hidden
    assert render_ref_png(ref, 128, ocg_on=frozenset({1})) == png_hidden


def test_render_and_search_encrypted_with_passwords(tmp_path: Path) -> None:
    from pagedrop.core.pdf_loader import PdfPasswordRequiredError
    from tests.core.test_jobs import _encrypted_pdf

    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    ref = PageRef(str(enc), 0)
    model = PdfEditModel(str(enc), 1)
    passwords = {str(enc): "secret"}

    with pytest.raises(PdfPasswordRequiredError):
        render_ref_png(ref, 64)
    png = render_ref_png(ref, 64, passwords=passwords)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"

    with pytest.raises(PdfPasswordRequiredError):
        search_model(model, "Secret")
    # Encrypted fixture text may be empty; search must open successfully.
    hits = search_model(model, "no-such-token", passwords=passwords)
    assert hits == []
