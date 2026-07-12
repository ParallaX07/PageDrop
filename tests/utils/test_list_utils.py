"""Self-check for shared list reorder helper."""

from __future__ import annotations

from pagedrop.utils.list_utils import move_items


def test_move_items_basic():
    items, adjusted = move_items(["a", "b", "c", "d"], [1, 2], 0)
    assert items == ["b", "c", "a", "d"]
    assert adjusted == 0


def test_move_items_forward_adjusts_index():
    items, adjusted = move_items(["a", "b", "c", "d"], [0, 1], 4)
    assert items == ["c", "d", "a", "b"]
    assert adjusted == 2


def test_move_items_noop_same_span():
    items, adjusted = move_items(["a", "b", "c"], [1], 1)
    assert items == ["a", "b", "c"]
    assert adjusted == 1


def test_move_items_dedupes_indices():
    items, adjusted = move_items(["a", "b", "c"], [2, 2, 0], 2)
    assert items == ["b", "a", "c"]
    assert adjusted == 1
