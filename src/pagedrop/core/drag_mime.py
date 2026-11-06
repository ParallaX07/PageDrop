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
        {
            "source_path": ref.source_path,
            "source_index": ref.source_index,
            "rotation": ref.rotation,
        }
        for ref in refs
    ]
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class PageTransferPayloadError(Exception):
    """The page-transfer drag payload is malformed or not from PageDrop."""


def _payload_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected an integer")
    return value


def decode_page_refs(data: bytes | bytearray | None) -> list[PageRef]:
    if not data:
        return []
    try:
        items = json.loads(bytes(data).decode("utf-8"))
        if not isinstance(items, list):
            raise TypeError("expected a list of page references")
        refs: list[PageRef] = []
        for item in items:
            source_path = item["source_path"]
            if not isinstance(source_path, str):
                raise TypeError("expected a path string")
            refs.append(
                PageRef(
                    source_path,
                    _payload_int(item["source_index"]),
                    _payload_int(item.get("rotation", 0)),
                )
            )
        return refs
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PageTransferPayloadError(
            "The dropped pages could not be read."
        ) from exc
