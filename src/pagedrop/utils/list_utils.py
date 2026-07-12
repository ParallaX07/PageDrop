from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def move_items(
    items: Sequence[T],
    indices: Sequence[int],
    to_index: int,
) -> tuple[list[T], int]:
    """Move items at *indices* so the block starts at *to_index* in *items*.

    Returns ``(new_list, adjusted_index)`` where *adjusted_index* is where the
    moved block lands after removing earlier indices from the insertion point.
    """
    ordered = sorted(set(indices))
    moving = [items[i] for i in ordered]
    remaining = [item for i, item in enumerate(items) if i not in set(ordered)]

    adjusted = to_index
    for i in ordered:
        if i < to_index:
            adjusted -= 1
    adjusted = max(0, min(adjusted, len(remaining)))

    remaining[adjusted:adjusted] = moving
    return remaining, adjusted
