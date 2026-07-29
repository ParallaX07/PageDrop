"""Serialized PDF read service — single process-wide fitz lock.

Viewer, UI thumbnail/preview/merge/convert pools, and the job runner share
``FITZ_LOCK`` so MuPDF work never overlaps across Qt pools. Callers pass paths
only; helpers borrow documents from a short-lived path→doc cache inside the
lock and return bytes / dataclasses only — never a live ``fitz.Document``.

ponytail: one global lock for all in-process fitz — a long fitz job stalls
unrelated thumbs/viewer until it releases. Upgrade path: dedicated PDF service
process with the same call shapes (O10).

ponytail: dual long-lived docs with tab ``PdfLoader`` are intentional — this
cache is interactive render only (short TTL); the tab loader owns edit
geometry. Do not add a third path→doc owner. Fold into one cache only when
measured (same O10 upgrade).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import fitz

from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_loader import open_pdf, render_page_png
from pagedrop.core.thread_policy import ensure_no_fitz_document


def _password_for(
    passwords: Mapping[str, str] | None, path: str
) -> str | None:
    # Inline lookup — do not import jobs here (runner imports FITZ_LOCK).
    # Same resolve rules as RuntimeCredentials.lookup.
    if not passwords:
        return None
    found = passwords.get(path)
    if found is not None:
        return found
    try:
        key = str(Path(path).resolve())
    except OSError:
        key = str(Path(path))
    return passwords.get(key)

FITZ_LOCK = threading.RLock()

T = TypeVar("T")

# Soft ceiling for interactive print; UI should warn above this.
MAX_PRINT_PAGES = 200

# ponytail: doc cache max 8 path→Document, idle TTL 60s. Raise max only if
# real multi-source sessions regularly need more open paths — do not grow
# toward the viewer pixmap LRU (48), which caches pixels, not MuPDF docs.
# Upgrade path: dedicated PDF service process with its own cache (O10).
_DOC_CACHE_MAX = 8
_DOC_CACHE_TTL_S = 60.0


@dataclass
class _DocCacheEntry:
    doc: fitz.Document
    password: str | None
    last_used: float


_doc_cache: OrderedDict[str, _DocCacheEntry] = OrderedDict()


@dataclass(frozen=True)
class OutlineItem:
    level: int
    title: str
    source_path: str
    source_index: int  # 0-based
    # MuPDF page coords (origin top-left). None → top of page.
    top_y: float | None = None
    left_x: float | None = None


@dataclass(frozen=True)
class LayerInfo:
    number: int
    name: str
    visible: bool
    source_path: str


@dataclass(frozen=True)
class AttachmentInfo:
    name: str
    size: int
    source_path: str


@dataclass(frozen=True)
class SearchHit:
    logical_page: int
    rect: tuple[float, float, float, float]  # PDF page coords (x0,y0,x1,y1)


@dataclass(frozen=True)
class LinkInfo:
    kind: str  # "goto" | "uri" | "other"
    rect: tuple[float, float, float, float]
    page: int | None = None  # 0-based source page for goto
    uri: str | None = None


@dataclass(frozen=True)
class PageGeom:
    """Unrotated page size in PDF points (before extra PageRef rotation)."""

    width: float
    height: float


@dataclass(frozen=True)
class WidgetInfo:
    """AcroForm widget geometry on a source page (PDF space)."""

    name: str
    field_type: str
    value: str
    rect: tuple[float, float, float, float]


def call(fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run *fn* under the process-wide fitz lock."""
    with FITZ_LOCK:
        return fn(*args, **kwargs)  # type: ignore[arg-type]


def invalidate_doc_cache(path: str | None = None) -> None:
    """Drop cached docs for *path*, or the whole cache when *path* is None.

    Call on tab close / source path change so the next open sees a fresh
    ``fitz.Document``. Takes ``FITZ_LOCK`` (re-entrant).
    """
    with FITZ_LOCK:
        if path is None:
            _clear_doc_cache_locked()
        else:
            _evict_doc_locked(path)


def doc_cache_size() -> int:
    """Current cache entry count (tests / diagnostics)."""
    with FITZ_LOCK:
        return len(_doc_cache)


def _evict_doc_locked(path: str) -> None:
    entry = _doc_cache.pop(path, None)
    if entry is not None:
        entry.doc.close()


def _clear_doc_cache_locked() -> None:
    for entry in _doc_cache.values():
        entry.doc.close()
    _doc_cache.clear()


def _purge_idle_locked(now: float) -> None:
    stale = [
        p
        for p, entry in _doc_cache.items()
        if now - entry.last_used > _DOC_CACHE_TTL_S
    ]
    for p in stale:
        _evict_doc_locked(p)


def _open(path: str, password: str | None = None) -> fitz.Document:
    """Open a fresh document. Caller owns close / cache insertion."""
    ensure_no_fitz_document(path, what="pdf_service path")
    return open_pdf(path, password)


def _cache_get(path: str, password: str | None = None) -> fitz.Document:
    """Get-or-open under ``FITZ_LOCK``. Document must not leave the lock.

    Caller must already hold ``FITZ_LOCK`` (via ``call``).
    """
    now = time.monotonic()
    _purge_idle_locked(now)

    entry = _doc_cache.get(path)
    if entry is not None:
        if entry.password != password:
            _evict_doc_locked(path)
        else:
            entry.last_used = now
            _doc_cache.move_to_end(path)
            return entry.doc

    while len(_doc_cache) >= _DOC_CACHE_MAX:
        old_path, old_entry = _doc_cache.popitem(last=False)
        old_entry.doc.close()

    doc = _open(path, password)
    _doc_cache[path] = _DocCacheEntry(doc, password, now)
    return doc


def page_count(path: str, *, password: str | None = None) -> int:
    """Page count under ``FITZ_LOCK`` — GUI tool probes use this, not unlocked ``PdfLoader``."""

    def _body() -> int:
        return len(_cache_get(path, password))

    return call(_body)


def page_geometry(path: str, source_index: int, *, password: str | None = None) -> PageGeom:
    def _body() -> PageGeom:
        doc = _cache_get(path, password)
        rect = doc[source_index].rect
        return PageGeom(rect.width, rect.height)

    return call(_body)


def render_ref_png(
    ref: PageRef,
    width_px: int,
    *,
    passwords: Mapping[str, str] | None = None,
    ocg_on: frozenset[int] | None = None,
) -> bytes:
    """Render one ``PageRef`` to PNG under the fitz lock.

    When ``ocg_on`` is set, layer visibility is applied only for this render
    and restored afterward so the shared doc cache still matches disk.
    """

    def _body() -> bytes:
        doc = _cache_get(
            ref.source_path, _password_for(passwords, ref.source_path)
        )
        prior: list[tuple[int, bool]] | None = None
        if ocg_on is not None:
            # No native OCG save/restore in PyMuPDF 1.27 — snapshot via
            # layer_ui_configs + set_layer_ui_config (PDF_OC_ON/OFF).
            prior = _snapshot_ocg_ui(doc)
            _apply_ocg_visibility(doc, ocg_on)
        try:
            return render_page_png(
                doc,
                ref.source_index,
                width_px=width_px,
                rotation=ref.rotation,
            )
        finally:
            if prior is not None:
                _restore_ocg_ui(doc, prior)

    return call(_body)


def _snapshot_ocg_ui(doc: fitz.Document) -> list[tuple[int, bool]]:
    return [
        (int(cfg["number"]), bool(cfg.get("on", True)))
        for cfg in doc.layer_ui_configs()
        if int(cfg.get("number", -1)) >= 0
    ]


def _restore_ocg_ui(
    doc: fitz.Document, prior: list[tuple[int, bool]]
) -> None:
    for number, on in prior:
        doc.set_layer_ui_config(
            number, action=fitz.PDF_OC_ON if on else fitz.PDF_OC_OFF
        )


def _apply_ocg_visibility(doc: fitz.Document, visible_numbers: frozenset[int]) -> None:
    configs = doc.layer_ui_configs()
    for cfg in configs:
        number = int(cfg.get("number", -1))
        if number < 0:
            continue
        want_on = number in visible_numbers
        is_on = bool(cfg.get("on", True))
        if want_on != is_on:
            doc.set_layer_ui_config(
                number,
                action=fitz.PDF_OC_ON if want_on else fitz.PDF_OC_OFF,
            )


def search_model(
    model: PdfEditModel,
    query: str,
    *,
    passwords: Mapping[str, str] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[SearchHit]:
    """Document-wide search over logical page order."""
    if not query:
        return []

    def _body() -> list[SearchHit]:
        hits: list[SearchHit] = []
        for logical, ref in enumerate(model.iter_pages()):
            if is_cancelled is not None and is_cancelled():
                return hits
            doc = _cache_get(
                ref.source_path, _password_for(passwords, ref.source_path)
            )
            page = doc[ref.source_index]
            for rect in page.search_for(query):
                hits.append(
                    SearchHit(
                        logical,
                        (rect.x0, rect.y0, rect.x1, rect.y1),
                    )
                )
        return hits

    return call(_body)


def page_text_dict(
    ref: PageRef,
    *,
    password: str | None = None,
) -> dict:
    """Text geometry for selection (PyMuPDF ``get_text('rawdict')`` — includes chars)."""

    def _body() -> dict:
        doc = _cache_get(ref.source_path, password)
        return doc[ref.source_index].get_text("rawdict")

    return call(_body)


def page_links(
    ref: PageRef,
    *,
    password: str | None = None,
) -> list[LinkInfo]:
    def _body() -> list[LinkInfo]:
        doc = _cache_get(ref.source_path, password)
        out: list[LinkInfo] = []
        for link in doc[ref.source_index].get_links():
            r = link.get("from")
            if r is None:
                continue
            rect = (r.x0, r.y0, r.x1, r.y1)
            kind = link.get("kind")
            if kind == fitz.LINK_GOTO:
                out.append(
                    LinkInfo(
                        "goto",
                        rect,
                        page=int(link.get("page", 0)),
                    )
                )
            elif kind == fitz.LINK_URI:
                out.append(
                    LinkInfo("uri", rect, uri=str(link.get("uri", "")))
                )
            else:
                out.append(LinkInfo("other", rect))
        return out

    return call(_body)


def outline_for_paths(
    paths: Sequence[str],
    *,
    passwords: Mapping[str, str] | None = None,
    password: str | None = None,
) -> list[OutlineItem]:
    def _body() -> list[OutlineItem]:
        items: list[OutlineItem] = []
        for path in paths:
            pw = _password_for(passwords, path) if passwords is not None else password
            doc = _cache_get(path, pw)
            for entry in doc.get_toc(simple=False):
                level = int(entry[0])
                title = str(entry[1])
                page1 = int(entry[2])
                source_index = max(0, page1 - 1) if page1 > 0 else 0
                top_y: float | None = None
                left_x: float | None = None
                if len(entry) > 3 and isinstance(entry[3], dict):
                    dest = entry[3]
                    dest_page = dest.get("page")
                    if isinstance(dest_page, int) and dest_page >= 0:
                        source_index = dest_page
                    to = dest.get("to")
                    if to is not None:
                        try:
                            left_x = float(to.x)
                            top_y = float(to.y)
                        except AttributeError:
                            left_x = float(to[0])
                            top_y = float(to[1])
                items.append(
                    OutlineItem(
                        level, title, path, source_index, top_y, left_x
                    )
                )
        return items

    return call(_body)


def layers_for_path(
    path: str,
    *,
    password: str | None = None,
) -> list[LayerInfo]:
    def _body() -> list[LayerInfo]:
        doc = _cache_get(path, password)
        out: list[LayerInfo] = []
        for cfg in doc.layer_ui_configs():
            out.append(
                LayerInfo(
                    number=int(cfg.get("number", 0)),
                    name=str(cfg.get("text") or cfg.get("name") or "Layer"),
                    visible=bool(cfg.get("on", True)),
                    source_path=path,
                )
            )
        return out

    return call(_body)


def attachments_for_path(
    path: str,
    *,
    password: str | None = None,
) -> list[AttachmentInfo]:
    def _body() -> list[AttachmentInfo]:
        doc = _cache_get(path, password)
        names = list(doc.embfile_names())
        out: list[AttachmentInfo] = []
        for name in names:
            info = doc.embfile_info(name) or {}
            size = int(info.get("size") or info.get("length") or 0)
            out.append(AttachmentInfo(name=name, size=size, source_path=path))
        return out

    return call(_body)


def extract_attachment(
    path: str,
    name: str,
    dest_dir: str | Path,
    *,
    password: str | None = None,
) -> Path:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    def _body() -> Path:
        doc = _cache_get(path, password)
        data = doc.embfile_get(name)
        if data is None:
            raise FileNotFoundError(f"Attachment not found: {name}")
        safe = Path(name).name or "attachment.bin"
        out_path = dest / safe
        # Collision: append counter rather than overwrite silently.
        if out_path.exists():
            stem, suffix = out_path.stem, out_path.suffix
            n = 1
            while True:
                candidate = dest / f"{stem}_{n}{suffix}"
                if not candidate.exists():
                    out_path = candidate
                    break
                n += 1
        out_path.write_bytes(data)
        return out_path

    return call(_body)


def logical_index_for_source(
    model: PdfEditModel,
    source_path: str,
    source_index: int,
) -> int | None:
    """First logical page matching *source_path* / *source_index*."""
    for i, ref in enumerate(model.iter_pages()):
        if ref.source_path == source_path and ref.source_index == source_index:
            return i
    return None


def page_widgets(
    path: str,
    source_index: int,
    *,
    password: str | None = None,
) -> list[WidgetInfo]:
    """AcroForm widgets on one source page (empty when XFA / none)."""
    from pagedrop.core.forms import document_has_xfa

    def _body() -> list[WidgetInfo]:
        doc = _cache_get(path, password)
        if document_has_xfa(doc):
            return []
        if source_index < 0 or source_index >= doc.page_count:
            return []
        out: list[WidgetInfo] = []
        for widget in doc[source_index].widgets() or []:
            rect = widget.rect
            out.append(
                WidgetInfo(
                    name=str(widget.field_name or ""),
                    field_type=str(widget.field_type_string or "unknown"),
                    value=str(widget.field_value or ""),
                    rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                )
            )
        return out

    return call(_body)
