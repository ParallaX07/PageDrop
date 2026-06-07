"""Mime types and payloads for PageDrop drag-and-drop."""

from __future__ import annotations

INTERNAL_PAGE_MIME = "application/x-pagedrop-page"


def encode_page_indices(indices: list[int]) -> bytes:
    return ",".join(str(i) for i in sorted(indices)).encode("ascii")


def decode_page_indices(data: bytes | bytearray | None) -> list[int]:
    if not data:
        return []
    return [int(part) for part in bytes(data).decode("ascii").split(",") if part]
