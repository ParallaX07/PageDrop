from __future__ import annotations

from pathlib import Path

from pagedrop.utils.list_utils import move_items


class PdfMergeModel:
    """Ordered list of whole PDF files to merge."""

    def __init__(self) -> None:
        self._paths: list[str] = []

    def add_files(self, paths: list[str]) -> None:
        for path in paths:
            self._paths.append(str(Path(path).resolve()))

    def remove_at(self, index: int) -> None:
        del self._paths[index]

    def remove_indices(self, indices: list[int]) -> None:
        if not indices:
            return
        remove = set(indices)
        self._paths = [path for i, path in enumerate(self._paths) if i not in remove]

    def move_up(self, indices: list[int]) -> None:
        if not indices:
            return
        ordered = sorted(set(indices))
        if ordered[0] == 0:
            return
        self._paths, _ = move_items(self._paths, ordered, ordered[0] - 1)

    def move_down(self, indices: list[int]) -> None:
        if not indices:
            return
        ordered = sorted(set(indices))
        if ordered[-1] >= len(self._paths) - 1:
            return
        self._paths, _ = move_items(self._paths, ordered, ordered[-1] + 2)

    def reorder(self, from_index: int, to_index: int) -> None:
        if from_index == to_index:
            return
        item = self._paths.pop(from_index)
        self._paths.insert(to_index, item)

    def clear(self) -> None:
        self._paths.clear()

    def file_count(self) -> int:
        return len(self._paths)

    def path_at(self, index: int) -> str:
        return self._paths[index]

    def all_paths(self) -> list[str]:
        return list(self._paths)
