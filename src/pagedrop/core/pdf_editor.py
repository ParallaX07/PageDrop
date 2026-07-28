from __future__ import annotations

from dataclasses import dataclass

from pagedrop.utils.list_utils import move_items

# 50 snapshots is enough for heavy edit sessions; each entry holds a
# full PageRef tuple copy. Raise only with a measured memory complaint (or add
# coalescing) — unbounded growth was the prior ceiling.
MAX_UNDO = 50


@dataclass(frozen=True)
class PageRef:
    source_path: str
    source_index: int  # 0-based in that file
    rotation: int = 0  # additional degrees: 0, 90, 180, or 270


def normalize_rotation(degrees: int) -> int:
    """Snap to {0, 90, 180, 270}."""
    return ((degrees // 90) % 4) * 90


class PdfEditModel:
    """Logical page list decoupled from source PDF order."""

    def __init__(self, source_path: str, page_count: int) -> None:
        self._original_path = source_path
        self._save_path: str | None = None
        self._pages: list[PageRef] = [
            PageRef(source_path, index) for index in range(page_count)
        ]
        self._dirty = False
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

    def iter_pages(self) -> list[PageRef]:
        """Current logical page list (copy — safe to iterate while reading)."""
        return list(self._pages)

    def source_paths(self) -> set[str]:
        """Paths still needed for the current page list (plus original)."""
        paths = {self._original_path}
        paths.update(page.source_path for page in self._pages)
        return paths

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

    def rotate_pages(
        self, logical_indices: list[int], delta_degrees: int, *, record_undo: bool = True
    ) -> None:
        """Add *delta_degrees* (typically ±90) to each listed page's rotation."""
        if not logical_indices:
            return
        ordered = sorted(set(logical_indices))
        if record_undo:
            self._push_undo()
        for index in ordered:
            old = self._pages[index]
            self._pages[index] = PageRef(
                old.source_path,
                old.source_index,
                normalize_rotation(old.rotation + delta_degrees),
            )
        self._dirty = True

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
        self._append_undo_snapshot((tuple(self._pages), self._dirty))
        pages, dirty = self._redo_stack.pop()
        self._pages = list(pages)
        self._dirty = dirty
        return True

    def is_dirty(self) -> bool:
        return self._dirty

    def mark_saved(self, save_path: str) -> None:
        """Record save path, clear dirty, and establish a savepoint (no undo past save)."""
        self._save_path = save_path
        self._dirty = False
        self._undo_stack.clear()
        self._redo_stack.clear()

    def _append_undo_snapshot(
        self, snapshot: tuple[tuple[PageRef, ...], bool]
    ) -> None:
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > MAX_UNDO:
            del self._undo_stack[0 : len(self._undo_stack) - MAX_UNDO]

    def _push_undo(self) -> None:
        self._append_undo_snapshot((tuple(self._pages), self._dirty))
        self._redo_stack.clear()
