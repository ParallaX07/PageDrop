from __future__ import annotations

from dataclasses import dataclass

from pagedrop.utils.list_utils import move_items


@dataclass(frozen=True)
class PageRef:
    source_path: str
    source_index: int  # 0-based in that file


class PdfEditModel:
    """Logical page list decoupled from source PDF order."""

    def __init__(self, source_path: str, page_count: int) -> None:
        self._original_path = source_path
        self._save_path: str | None = None
        self._pages: list[PageRef] = [
            PageRef(source_path, index) for index in range(page_count)
        ]
        self._dirty = False
        # ponytail: unbounded snapshot stack; cap/coalesce if memory becomes an issue
        self._undo_stack: list[tuple[tuple[PageRef, ...], bool]] = []
        self._redo_stack: list[tuple[tuple[PageRef, ...], bool]] = []

    @classmethod
    def with_pages(cls, primary_path: str, pages: list[PageRef]) -> PdfEditModel:
        """Create a model whose logical list is exactly *pages* (e.g. blank-tab init)."""
        model = cls.__new__(cls)
        model._original_path = primary_path
        model._save_path = None
        model._pages = list(pages)
        model._dirty = True
        model._undo_stack = []
        model._redo_stack = []
        return model

    @property
    def original_path(self) -> str:
        return self._original_path

    @property
    def save_path(self) -> str | None:
        return self._save_path

    def logical_count(self) -> int:
        return len(self._pages)

    def page_at(self, logical_index: int) -> PageRef:
        return self._pages[logical_index]

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo_depth(self) -> int:
        return len(self._undo_stack)

    def insert_pages(
        self, index: int, refs: list[PageRef], *, record_undo: bool = True
    ) -> None:
        if not refs:
            return
        if record_undo:
            self._push_undo()
        clamped = max(0, min(index, len(self._pages)))
        self._pages[clamped:clamped] = list(refs)
        self._dirty = True

    def remove_pages(
        self, logical_indices: list[int], *, record_undo: bool = True
    ) -> None:
        if not logical_indices:
            return
        if record_undo:
            self._push_undo()
        remove = set(logical_indices)
        self._pages = [page for i, page in enumerate(self._pages) if i not in remove]
        self._dirty = True

    def move_pages(
        self, indices: list[int], to_index: int, *, record_undo: bool = True
    ) -> None:
        if not indices:
            return
        if record_undo:
            self._push_undo()
        self._pages, _ = move_items(self._pages, indices, to_index)
        self._dirty = True

    def move_up(self, indices: list[int]) -> None:
        if not indices:
            return
        ordered = sorted(set(indices))
        if ordered[0] == 0:
            return
        self.move_pages(ordered, ordered[0] - 1)

    def move_down(self, indices: list[int]) -> None:
        if not indices:
            return
        ordered = sorted(set(indices))
        if ordered[-1] >= len(self._pages) - 1:
            return
        self.move_pages(ordered, ordered[-1] + 2)

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append((tuple(self._pages), self._dirty))
        pages, dirty = self._undo_stack.pop()
        self._pages = list(pages)
        self._dirty = dirty
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append((tuple(self._pages), self._dirty))
        pages, dirty = self._redo_stack.pop()
        self._pages = list(pages)
        self._dirty = dirty
        return True

    def is_dirty(self) -> bool:
        return self._dirty

    def mark_saved(self, save_path: str) -> None:
        self._save_path = save_path
        self._dirty = False

    def _push_undo(self) -> None:
        self._undo_stack.append((tuple(self._pages), self._dirty))
        self._redo_stack.clear()
