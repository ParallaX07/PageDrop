"""Mime types and payloads for PageDrop drag-and-drop."""

from __future__ import annotations

import json

from pagedrop.core.pdf_editor import PageRef

INTERNAL_PAGE_MIME = "application/x-pagedrop-page"
PAGE_TRANSFER_MIME = "application/x-pagedrop-page-transfer"
INTERNAL_MERGE_FILE_MIME = "application/x-pagedrop-merge-file"


def encode_page_indices(indices: list[int]) -> bytes:
    return ",".join(str(i) for i in sorted(indices)).encode("ascii")


def decode_page_indices(data: bytes | bytearray | None) -> list[int]:
    if not data:
        return []
    return [int(part) for part in bytes(data).decode("ascii").split(",") if part]


def encode_page_refs(refs: list[PageRef]) -> bytes:
    payload = [
        {"source_path": ref.source_path, "source_index": ref.source_index}
        for ref in refs
    ]
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def decode_page_refs(data: bytes | bytearray | None) -> list[PageRef]:
    if not data:
        return []
    items = json.loads(bytes(data).decode("utf-8"))
    return [
        PageRef(str(item["source_path"]), int(item["source_index"]))
        for item in items
    ]
