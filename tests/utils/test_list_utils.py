"""Self-check for shared list reorder helper."""

from __future__ import annotations

from pagedrop.utils.list_utils import move_items, to_index_for_start


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


def test_to_index_for_start_backward_and_forward():
    items = ["a", "b", "c", "d", "e"]
    # Move last item to become index 1 (page 2).
    to = to_index_for_start([4], 1)
    out, adjusted = move_items(items, [4], to)
    assert out == ["a", "e", "b", "c", "d"]
    assert adjusted == 1
    # Move first two to become index 2 (page 3).
    to = to_index_for_start([0, 1], 2)
    out, adjusted = move_items(items, [0, 1], to)
    assert out == ["c", "d", "a", "b", "e"]
    assert adjusted == 2
