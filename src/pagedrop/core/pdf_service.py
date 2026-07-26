"""Serialized PDF read service — single process-wide fitz lock.

Viewer and the job runner share ``FITZ_LOCK`` so MuPDF work
never overlaps across Qt pools. Callers pass paths only; helpers open and
close documents inside the lock. Upgrade path: dedicated PDF service
process with the same call shapes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import fitz

from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_loader import render_page_png
from pagedrop.core.thread_policy import ensure_no_fitz_document

FITZ_LOCK = threading.RLock()

T = TypeVar("T")

# Soft ceiling for interactive print; UI should warn above this.
MAX_PRINT_PAGES = 200


@dataclass(frozen=True)
class OutlineItem:
    level: int
    title: str
    source_path: str
    source_index: int  # 0-based


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


def call(fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run *fn* under the process-wide fitz lock."""
    with FITZ_LOCK:
        return fn(*args, **kwargs)  # type: ignore[arg-type]


def _open(path: str, password: str | None = None) -> fitz.Document:
    ensure_no_fitz_document(path, what="pdf_service path")
    doc = fitz.open(path)
    if doc.needs_pass:
        if password is None or doc.authenticate(password) == 0:
            doc.close()
            raise PermissionError(f"Password required or incorrect: {path}")
    return doc


def page_geometry(path: str, source_index: int, *, password: str | None = None) -> PageGeom:
    def _body() -> PageGeom:
        doc = _open(path, password)
        try:
            rect = doc[source_index].rect
            return PageGeom(rect.width, rect.height)
        finally:
            doc.close()

    return call(_body)


def render_ref_png(
    ref: PageRef,
    width_px: int,
    *,
    password: str | None = None,
    ocg_on: frozenset[int] | None = None,
) -> bytes:
    """Render one ``PageRef`` to PNG under the fitz lock."""

    def _body() -> bytes:
        doc = _open(ref.source_path, password)
        try:
            if ocg_on is not None:
                _apply_ocg_visibility(doc, ocg_on)
            return render_page_png(
                doc,
                ref.source_index,
                width_px=width_px,
                rotation=ref.rotation,
            )
        finally:
            doc.close()

    return call(_body)


def _apply_ocg_visibility(doc: fitz.Document, visible_numbers: frozenset[int]) -> None:
    configs = doc.layer_ui_configs()
    for cfg in configs:
        number = int(cfg.get("number", -1))
        if number < 0:
            continue
        want_on = number in visible_numbers
        is_on = bool(cfg.get("on", True))
        if want_on != is_on:
            # 1 = ON, 0 = OFF
            doc.set_layer_ui_config(number, action=1 if want_on else 0)


def search_model(
    model: PdfEditModel,
    query: str,
    *,
    password: str | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[SearchHit]:
    """Document-wide search over logical page order."""
    if not query:
        return []

    def _body() -> list[SearchHit]:
        hits: list[SearchHit] = []
        open_docs: dict[str, fitz.Document] = {}
        try:
            for logical, ref in enumerate(model.iter_pages()):
                if is_cancelled is not None and is_cancelled():
                    return hits
                doc = open_docs.get(ref.source_path)
                if doc is None:
                    doc = _open(ref.source_path, password)
                    open_docs[ref.source_path] = doc
                page = doc[ref.source_index]
                for rect in page.search_for(query):
                    hits.append(
                        SearchHit(
                            logical,
                            (rect.x0, rect.y0, rect.x1, rect.y1),
                        )
                    )
            return hits
        finally:
            for doc in open_docs.values():
                doc.close()

    return call(_body)


def page_text_dict(
    ref: PageRef,
    *,
    password: str | None = None,
) -> dict:
    """Raw text dict for selection geometry (PyMuPDF ``get_text('dict')``)."""

    def _body() -> dict:
        doc = _open(ref.source_path, password)
        try:
            return doc[ref.source_index].get_text("dict")
        finally:
            doc.close()

    return call(_body)


def page_links(
    ref: PageRef,
    *,
    password: str | None = None,
) -> list[LinkInfo]:
    def _body() -> list[LinkInfo]:
        doc = _open(ref.source_path, password)
        try:
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
        finally:
            doc.close()

    return call(_body)


def outline_for_paths(
    paths: Sequence[str],
    *,
    password: str | None = None,
) -> list[OutlineItem]:
    def _body() -> list[OutlineItem]:
        items: list[OutlineItem] = []
        for path in paths:
            doc = _open(path, password)
            try:
                for level, title, page1 in doc.get_toc():
                    source_index = max(0, int(page1) - 1)
                    items.append(
                        OutlineItem(int(level), str(title), path, source_index)
                    )
            finally:
                doc.close()
        return items

    return call(_body)


def layers_for_path(
    path: str,
    *,
    password: str | None = None,
) -> list[LayerInfo]:
    def _body() -> list[LayerInfo]:
        doc = _open(path, password)
        try:
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
        finally:
            doc.close()

    return call(_body)


def attachments_for_path(
    path: str,
    *,
    password: str | None = None,
) -> list[AttachmentInfo]:
    def _body() -> list[AttachmentInfo]:
        doc = _open(path, password)
        try:
            names = list(doc.embfile_names())
            out: list[AttachmentInfo] = []
            for name in names:
                info = doc.embfile_info(name) or {}
                size = int(info.get("size") or info.get("length") or 0)
                out.append(AttachmentInfo(name=name, size=size, source_path=path))
            return out
        finally:
            doc.close()

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
        doc = _open(path, password)
        try:
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
        finally:
            doc.close()

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
