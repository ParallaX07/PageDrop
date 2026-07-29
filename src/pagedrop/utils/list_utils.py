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


def to_index_for_start(indices: Sequence[int], dest: int) -> int:
    """Return a ``move_items`` *to_index* so the block starts at *dest* finally."""
    ordered = sorted(set(indices))
    return dest + sum(1 for i in ordered if i < dest)
