"""Parse page-number / page-range jump text (1-based UI → 0-based indices)."""

from __future__ import annotations

from collections.abc import Iterable


def parse_page_jump(text: str, page_count: int) -> list[int] | None:
    """Parse ``12`` or ``1-5`` into sorted unique 0-based indices.

    Returns ``None`` when the input is empty or not a simple number/range.
    Out-of-range bounds are clamped to ``[1, page_count]``; if nothing remains
    in range, returns ``None``.
    """
    raw = text.strip().replace(" ", "")
    if not raw or page_count <= 0:
        return None

    if "-" in raw:
        left, sep, right = raw.partition("-")
        if not sep or "-" in right or not left.isdigit() or not right.isdigit():
            return None
        start, end = int(left), int(right)
        if start < 1 and end < 1:
            return None
        low, high = sorted((start, end))
        low = max(1, low)
        high = min(page_count, high)
        if low > high:
            return None
        return list(range(low - 1, high))

    if not raw.isdigit():
        return None
    page = int(raw)
    if page < 1 or page > page_count:
        return None
    return [page - 1]


def parse_page_ranges(text: str, page_count: int) -> list[tuple[int, int]] | None:
    """Parse ``1-3,5,7-9`` into inclusive 0-based ``(start, end)`` tuples.

    Returns ``None`` when the input is empty or any segment is invalid.
    """
    raw = text.strip()
    if not raw or page_count <= 0:
        return None

    ranges: list[tuple[int, int]] = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            return None
        indices = parse_page_jump(part, page_count)
        if not indices:
            return None
        ranges.append((indices[0], indices[-1]))
    return ranges


def format_indices_as_ranges(indices: Iterable[int]) -> str:
    """Format 0-based indices as 1-based UI text (``1-3,5,8-9``)."""
    ordered = sorted({int(i) for i in indices})
    if not ordered:
        return ""

    parts: list[str] = []
    start = prev = ordered[0]
    for index in ordered[1:]:
        if index == prev + 1:
            prev = index
            continue
        parts.append(
            f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}"
        )
        start = prev = index
    parts.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
    return ",".join(parts)
