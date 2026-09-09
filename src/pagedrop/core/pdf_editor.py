from __future__ import annotations

from dataclasses import dataclass, field, replace
from uuid import uuid4

from pagedrop.utils.list_utils import move_items

# ponytail: undo depth 50 — each entry holds a full PageRef tuple copy.
# Raise only with a measured memory complaint (or add coalescing).
MAX_UNDO = 50


@dataclass(frozen=True)
class PageRef:
    source_path: str
    source_index: int  # 0-based in that file
    rotation: int = 0  # additional degrees: 0, 90, 180, or 270
    instance_id: str = field(default_factory=lambda: uuid4().hex, compare=False)

    def new_instance(self) -> PageRef:
        """Copy this source reference as a distinct logical page occurrence."""
        return replace(self, instance_id=uuid4().hex)


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
        self._protected_sources: set[str] = {source_path}
        self._dirty = False
        self._undo_stack: list[tuple[tuple[PageRef, ...], bool]] = []
        self._redo_stack: list[tuple[tuple[PageRef, ...], bool]] = []

    @classmethod
    def with_pages(cls, primary_path: str, pages: list[PageRef]) -> PdfEditModel:
        """Create a model whose logical list is exactly *pages* (e.g. blank-tab init)."""
        model = cls.__new__(cls)
        model._original_path = primary_path
        model._save_path = None
        model._pages = [page.new_instance() for page in pages]
        model._protected_sources = {primary_path, *(page.source_path for page in pages)}
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

    def logical_index_for_instance(self, instance_id: str) -> int | None:
        """Return a page occurrence's current logical position, if it remains."""
        return next(
            (i for i, page in enumerate(self._pages) if page.instance_id == instance_id),
            None,
        )

    def instance_id_at(self, logical_index: int) -> str:
        return self._pages[logical_index].instance_id

    def iter_pages(self) -> list[PageRef]:
        """Current logical page list (copy — safe to iterate while reading)."""
        return list(self._pages)

    def source_paths(self) -> set[str]:
        """Every source path ever admitted to this tab, protected from overwrite."""
        return set(self._protected_sources)

    def current_reference_paths(self) -> set[str]:
        """Paths still needed to render the current page list (plus original)."""
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
        # Every insertion is a new occurrence, including duplicate/cross-tab refs.
        self._pages[clamped:clamped] = [ref.new_instance() for ref in refs]
        self._protected_sources.update(ref.source_path for ref in refs)
        self._dirty = True

    def remove_pages(
        self, logical_indices: list[int], *, record_undo: bool = True
    ) -> set[str]:
        if not logical_indices:
            return set()
        if record_undo:
            self._push_undo()
        remove = set(logical_indices)
        removed = {
            page.instance_id for i, page in enumerate(self._pages) if i in remove
        }
        self._pages = [page for i, page in enumerate(self._pages) if i not in remove]
        self._dirty = True
        return removed

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
                old.instance_id,
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

    def rebase_saved_output(self, save_path: str) -> None:
        """Make a successfully written copy this model's new page baseline."""
        page_count = len(self._pages)
        self._original_path = save_path
        self._save_path = save_path
        self._protected_sources.add(save_path)
        self._pages = [PageRef(save_path, index) for index in range(page_count)]
        self._dirty = False
        self._undo_stack.clear()
        self._redo_stack.clear()

    def mark_saved(self, save_path: str) -> None:
        """Backward-compatible name for rebasing a successfully saved output."""
        self.rebase_saved_output(save_path)

    def _append_undo_snapshot(
        self, snapshot: tuple[tuple[PageRef, ...], bool]
    ) -> None:
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > MAX_UNDO:
            del self._undo_stack[0 : len(self._undo_stack) - MAX_UNDO]

    def _push_undo(self) -> None:
        self._append_undo_snapshot((tuple(self._pages), self._dirty))
        self._redo_stack.clear()
