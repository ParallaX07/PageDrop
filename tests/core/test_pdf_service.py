"""Core contract tests for the serialized PDF service."""

from __future__ import annotations

import inspect
import os
import sys
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
    encryption_state,
    invalidate_doc_cache,
    page_count,
    page_geometry,
    page_links,
    page_text_dict,
    render_ref_png,
    search_model,
)
from pagedrop.core.thread_policy import is_fitz_document

_needs_unlocked_open_files = pytest.mark.skipif(
    sys.platform == "win32",
    reason="an open document locks its file on Windows, so it cannot be replaced or deleted",
)


def test_public_api_annotations_exclude_fitz_document() -> None:
    """O3 residual: public helpers must not advertise a live Document return."""
    for name, obj in inspect.getmembers(pdf_service, inspect.isfunction):
        if name.startswith("_") or obj.__module__ != pdf_service.__name__:
            continue
        hints = getattr(obj, "__annotations__", {})
        ret = hints.get("return")
        if ret is None:
            continue
        text = ret if isinstance(ret, str) else getattr(ret, "__name__", str(ret))
        assert "Document" not in text, f"{name} return annotation leaks Document: {text}"


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


def test_page_count_under_fitz_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "pages.pdf"
    _text_pdf(path, ["a", "b", "c"])

    held: list[bool] = []
    real_open = fitz.open

    def tracking_open(*args: object, **kwargs: object) -> fitz.Document:
        held.append(FITZ_LOCK._is_owned())  # type: ignore[attr-defined]
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracking_open)
    assert page_count(str(path)) == 3
    assert held and all(held)


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


def test_search_model_cancel_stops_mid_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """is_cancelled checked between pages; partial hits returned."""
    path = tmp_path / "cancel.pdf"
    _text_pdf(path, ["a", "b", "c", "d"])
    model = PdfEditModel(str(path), 4)
    seen = {"n": 0}
    real_search = fitz.Page.search_for

    def counting_search(self: fitz.Page, *args: object, **kwargs: object) -> list:
        seen["n"] += 1
        return real_search(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "search_for", counting_search)
    hits = search_model(
        model, "a", is_cancelled=lambda: seen["n"] >= 2
    )

    # Pages 0–1 run; cancel before page 2. "a" only on page 0.
    assert seen["n"] == 2
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


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_page_geometry_is_unrotated_with_own_rotation(
    tmp_path: Path, rotation: int
) -> None:
    path = tmp_path / "rot.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=400)
        page.insert_link(
            {
                "kind": fitz.LINK_URI,
                "from": fitz.Rect(10, 30, 100, 60),
                "uri": "https://example.com",
            }
        )
        page.set_rotation(rotation)
        doc.save(str(path))
    finally:
        doc.close()

    geom = page_geometry(str(path), 0)
    assert (geom.width, geom.height, geom.rotation) == (200, 400, rotation)
    assert geom.visual_size == ((400, 200) if rotation % 180 else (200, 400))
    doc = fitz.open(str(path))
    try:
        expected = doc[0].rotation_matrix
    finally:
        doc.close()
    assert tuple(geom.rotation_matrix) == pytest.approx(tuple(expected))

    # Link rects are mapped back to the unrotated space of the geometry.
    link = page_links(PageRef(str(path), 0))[0]
    assert link.rect == pytest.approx((10, 30, 100, 60))


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

    # The unlocked entry is reused without a password; a fresh open still needs one.
    assert search_model(model, "no-such-token") == []
    invalidate_doc_cache()
    with pytest.raises(PdfPasswordRequiredError):
        search_model(model, "Secret")
    # Encrypted fixture text may be empty; search must open successfully.
    hits = search_model(model, "no-such-token", passwords=passwords)
    assert hits == []


def _count_opens(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"n": 0}
    real_open = fitz.open

    def counting_open(*args: object, **kwargs: object) -> fitz.Document:
        calls["n"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", counting_open)
    return calls


def test_doc_cache_shares_entry_across_path_spellings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _text_pdf(tmp_path / "same.pdf", ["x"])
    monkeypatch.chdir(tmp_path)
    calls = _count_opens(monkeypatch)

    page_geometry("same.pdf", 0)
    page_geometry(str(tmp_path / "same.pdf"), 0)
    assert calls["n"] == 1
    assert doc_cache_size() == 1

    invalidate_doc_cache("same.pdf")
    assert doc_cache_size() == 0
    page_geometry(str(tmp_path / "same.pdf"), 0)
    invalidate_doc_cache(str(tmp_path / "./same.pdf"))
    assert doc_cache_size() == 0


def test_no_password_reuses_unlocked_entry_but_page_count_still_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pagedrop.core.pdf_loader import PdfPasswordRequiredError
    from tests.core.test_jobs import _encrypted_pdf

    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    path = str(enc)
    calls = _count_opens(monkeypatch)

    assert page_count(path, password="secret") == 1
    assert calls["n"] == 1

    assert page_geometry(path, 0).width == 200
    assert calls["n"] == 1
    assert doc_cache_size() == 1

    # The probe must keep asking for a password, without dropping the entry.
    with pytest.raises(PdfPasswordRequiredError):
        page_count(path)
    assert doc_cache_size() == 1
    page_geometry(path, 0)
    assert calls["n"] == 1


def test_wrong_password_on_cached_unlocked_entry_raises(tmp_path: Path) -> None:
    from pagedrop.core.pdf_loader import PdfPasswordError
    from tests.core.test_jobs import _encrypted_pdf

    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    page_count(str(enc), password="secret")
    with pytest.raises(PdfPasswordError):
        page_count(str(enc), password="wrong")


def test_encryption_state_classifies_inputs(tmp_path: Path) -> None:
    from tests.core.test_jobs import _encrypted_pdf

    plain = tmp_path / "plain.pdf"
    _text_pdf(plain, ["x"])
    locked = tmp_path / "locked.pdf"
    _encrypted_pdf(locked, password="secret")
    owner_only = tmp_path / "owner.pdf"
    doc = fitz.open()
    try:
        doc.new_page()
        doc.save(
            str(owner_only),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            permissions=int(fitz.PDF_PERM_PRINT),
        )
    finally:
        doc.close()

    assert encryption_state(str(plain)) == "none"
    assert encryption_state(str(locked)) == "password"
    assert encryption_state(str(owner_only)) == "restricted"

    # Still "password" once an unlocked entry is cached.
    page_count(str(locked), password="secret")
    assert encryption_state(str(locked)) == "password"


def _replace_file(target: Path, source: Path) -> None:
    """Swap *source* over *target* and make sure the file signature differs."""
    before = target.stat()
    source.replace(target)
    stat = target.stat()
    if (stat.st_mtime_ns, stat.st_size) == (before.st_mtime_ns, before.st_size):
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 10**9))
    after = target.stat()
    assert (after.st_mtime_ns, after.st_size) != (before.st_mtime_ns, before.st_size)


@_needs_unlocked_open_files
def test_replaced_encrypted_file_asks_for_the_new_password(tmp_path: Path) -> None:
    from pagedrop.core.pdf_loader import PdfPasswordError
    from tests.core.test_jobs import _encrypted_pdf

    target = tmp_path / "x.pdf"
    _encrypted_pdf(target, password="one")
    assert page_count(str(target), password="one") == 1

    other = tmp_path / "other.pdf"
    _encrypted_pdf(other, password="two")
    _replace_file(target, other)

    with pytest.raises(PdfPasswordError):
        page_count(str(target), password="one")
    assert page_count(str(target), password="two") == 1


@_needs_unlocked_open_files
def test_locked_file_replaced_by_plain_file_is_not_a_password_probe(
    tmp_path: Path,
) -> None:
    from tests.core.test_jobs import _encrypted_pdf

    target = tmp_path / "x.pdf"
    _encrypted_pdf(target, password="secret")
    page_count(str(target), password="secret")

    plain = tmp_path / "plain.pdf"
    _text_pdf(plain, ["a", "b"])
    _replace_file(target, plain)

    assert page_count(str(target)) == 2
    assert encryption_state(str(target)) == "none"


@_needs_unlocked_open_files
def test_plain_file_replaced_by_locked_file_needs_a_password(tmp_path: Path) -> None:
    from pagedrop.core.pdf_loader import PdfPasswordRequiredError
    from tests.core.test_jobs import _encrypted_pdf

    target = tmp_path / "x.pdf"
    _text_pdf(target, ["a"])
    assert page_count(str(target)) == 1
    assert encryption_state(str(target)) == "none"

    locked = tmp_path / "locked.pdf"
    _encrypted_pdf(locked, password="secret")
    _replace_file(target, locked)

    with pytest.raises(PdfPasswordRequiredError):
        page_count(str(target))
    assert encryption_state(str(target)) == "password"


@_needs_unlocked_open_files
def test_deleted_file_evicts_cache_entry_and_raises_typed_error(
    tmp_path: Path,
) -> None:
    from pagedrop.core.pdf_loader import PdfLoadError

    target = tmp_path / "gone.pdf"
    _text_pdf(target, ["a"])
    assert page_count(str(target)) == 1
    target.unlink()

    with pytest.raises(PdfLoadError):
        page_count(str(target))
    assert doc_cache_size() == 0
