from __future__ import annotations

from collections.abc import Callable


class SelectionManager:
    """Tracks selected page indices and notifies listeners on change."""

    def __init__(
        self,
        page_count: int = 0,
        on_selection_changed: Callable[[set[int]], None] | None = None,
    ) -> None:
        self._page_count = page_count
        self._selected: set[int] = set()
        self._listeners: list[Callable[[set[int]], None]] = []
        if on_selection_changed is not None:
            self._listeners.append(on_selection_changed)

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def selection(self) -> set[int]:
        return set(self._selected)

    def set_page_count(self, page_count: int) -> None:
        self._page_count = page_count
        self._selected = {idx for idx in self._selected if idx < page_count}
        self._emit()

    def select_single(self, idx: int) -> None:
        self._selected = {idx}
        self._emit()

    def toggle(self, idx: int) -> None:
        if idx in self._selected:
            self._selected.remove(idx)
        else:
            self._selected.add(idx)
        self._emit()

    def select_range(self, start: int, end: int) -> None:
        low, high = sorted((start, end))
        self._selected = set(range(low, high + 1))
        self._emit()

    def select_all(self) -> None:
        self._selected = set(range(self._page_count))
        self._emit()

    def clear(self) -> None:
        if not self._selected:
            return
        self._selected.clear()
        self._emit()

    def set_selection(self, indices: set[int]) -> None:
        clamped = {idx for idx in indices if 0 <= idx < self._page_count}
        if clamped == self._selected:
            return
        self._selected = clamped
        self._emit()

    def add_listener(self, callback: Callable[[set[int]], None]) -> None:
        self._listeners.append(callback)

    def _emit(self) -> None:
        current = set(self._selected)
        for listener in self._listeners:
            listener(current)
