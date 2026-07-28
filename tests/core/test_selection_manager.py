"""Phase 5 unit tests — SelectionManager."""

from __future__ import annotations

from pagedrop.core.selection_manager import SelectionManager


def test_select_single_clears_others():
    manager = SelectionManager(page_count=5)
    manager.select_single(1)
    manager.select_single(3)
    assert manager.selection == {3}


def test_toggle_adds_and_removes():
    manager = SelectionManager(page_count=5)
    manager.toggle(2)
    assert manager.selection == {2}
    manager.toggle(2)
    assert manager.selection == set()
    manager.toggle(0)
    manager.toggle(4)
    assert manager.selection == {0, 4}


def test_select_range_inclusive():
    manager = SelectionManager(page_count=10)
    manager.select_range(2, 6)
    assert manager.selection == {2, 3, 4, 5, 6}
    manager.select_range(6, 2)
    assert manager.selection == {2, 3, 4, 5, 6}


def test_select_all_and_clear():
    manager = SelectionManager(page_count=4)
    manager.select_all()
    assert manager.selection == {0, 1, 2, 3}
    manager.clear()
    assert manager.selection == set()


def test_selection_changed_signal():
    emissions: list[set[int]] = []
    manager = SelectionManager(page_count=5, on_selection_changed=emissions.append)

    manager.select_single(1)
    assert emissions[-1] == {1}

    manager.toggle(3)
    assert emissions[-1] == {1, 3}

    manager.select_range(0, 2)
    assert emissions[-1] == {0, 1, 2}

    manager.select_all()
    assert emissions[-1] == {0, 1, 2, 3, 4}

    manager.clear()
    assert emissions[-1] == set()


def test_select_range_noop_skips_emit():
    emissions: list[set[int]] = []
    manager = SelectionManager(page_count=10, on_selection_changed=emissions.append)
    manager.select_range(2, 6)
    assert len(emissions) == 1
    manager.select_range(6, 2)
    assert len(emissions) == 1


def test_select_single_noop_skips_emit():
    emissions: list[set[int]] = []
    manager = SelectionManager(page_count=5, on_selection_changed=emissions.append)
    manager.select_single(1)
    manager.select_single(1)
    assert len(emissions) == 1
