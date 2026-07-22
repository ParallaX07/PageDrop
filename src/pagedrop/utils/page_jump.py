"""Parse page-number / page-range jump text (1-based UI → 0-based indices)."""

from __future__ import annotations


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
